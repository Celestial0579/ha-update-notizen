"""Sammelt offene Updates samt Notizen und löst den Bericht im eingestellten Takt aus."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_filtered, TrackStates
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import quellen
from .const import (
    CONF_INTERVALL,
    CONF_MAX_ZEICHEN,
    CONF_NUR_AENDERUNG,
    CONF_UHRZEIT,
    DOMAIN,
    EREIGNIS_BERICHT,
    STANDARD_OPTIONEN,
)

_LOGGER = logging.getLogger(__name__)


class Sammler:
    """Eine Instanz je Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.letzter_bericht: datetime | None = None
        self.naechster_bericht: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._gemeldet: list[str] = []
        self._zwischenspeicher: dict[str, dict[str, Any]] = {}
        self._zuhoerer: list[Callable[[], None]] = []
        self._abmelden: list[CALLBACK_TYPE] = []
        self._zeitplan: CALLBACK_TYPE | None = None

    def opt(self, schluessel: str) -> Any:
        return self.entry.options.get(schluessel, STANDARD_OPTIONEN[schluessel])

    # ------------------------------------------------------------ Lebenszyklus
    async def async_start(self) -> None:
        daten = await self._store.async_load() or {}
        self._gemeldet = daten.get("gemeldet", [])
        if daten.get("letzter_bericht"):
            self.letzter_bericht = dt_util.parse_datetime(daten["letzter_bericht"])
        verfolgung = async_track_state_change_filtered(
            self.hass, TrackStates(False, set(), {"update"}), self._update_geaendert
        )
        self._abmelden.append(verfolgung.async_remove)
        self._planen()

    async def async_stop(self) -> None:
        for abmelden in self._abmelden:
            abmelden()
        self._abmelden.clear()
        if self._zeitplan is not None:
            self._zeitplan()
            self._zeitplan = None

    def zuhoerer_hinzufuegen(self, rueckruf: Callable[[], None]) -> Callable[[], None]:
        self._zuhoerer.append(rueckruf)
        return lambda: self._zuhoerer.remove(rueckruf)

    @callback
    def _melden(self) -> None:
        for rueckruf in list(self._zuhoerer):
            rueckruf()

    @callback
    def _update_geaendert(self, _ereignis: Any) -> None:
        self._melden()

    # ------------------------------------------------------------ Abfragen
    def offene(self) -> list[dict[str, str]]:
        """Alle Update-Entitäten mit verfügbarem Update."""
        ergebnis = []
        for zustand in self.hass.states.async_all("update"):
            if zustand.state != "on":
                continue
            ergebnis.append(
                {
                    "entity_id": zustand.entity_id,
                    "name": zustand.name,
                    "installiert": str(zustand.attributes.get("installed_version") or ""),
                    "neu": str(zustand.attributes.get("latest_version") or ""),
                    "url": str(zustand.attributes.get("release_url") or ""),
                }
            )
        return sorted(ergebnis, key=lambda e: e["name"].lower())

    def integrationen(self) -> list[str]:
        return sorted({eintrag.domain for eintrag in self.hass.config_entries.async_entries()})

    async def async_notizen(self, entity_ids: list[str] | None = None) -> dict[str, Any]:
        """Notizen zu den offenen Updates (oder den angegebenen)."""
        offene = [u for u in self.offene() if not entity_ids or u["entity_id"] in entity_ids]
        sitzung = async_get_clientsession(self.hass)
        register = er.async_get(self.hass)
        integrationen = self.integrationen()
        laenge = int(self.opt(CONF_MAX_ZEICHEN))
        updates: dict[str, Any] = {}
        for update in offene:
            schluessel = f"{update['entity_id']}|{update['neu']}"
            if schluessel not in self._zwischenspeicher:
                notizen, quelle = await self._eine_notiz(sitzung, register, update, integrationen, laenge)
                if not quelle.startswith("fehler"):
                    self._zwischenspeicher[schluessel] = {"notizen": notizen, "quelle": quelle}
                eintrag = {"notizen": notizen, "quelle": quelle}
            else:
                eintrag = self._zwischenspeicher[schluessel]
            updates[update["entity_id"]] = {**update, **eintrag}
        return {"anzahl": len(updates), "updates": updates, "integrationen": integrationen}

    async def _eine_notiz(
        self, sitzung: aiohttp.ClientSession, register: er.EntityRegistry, update: dict[str, str],
        integrationen: list[str], laenge: int,
    ) -> tuple[str, str]:
        eintrag = register.async_get(update["entity_id"])
        plattform = eintrag.platform if eintrag else None
        kennung = (eintrag.unique_id if eintrag else "") or ""
        try:
            if update["entity_id"] == "update.home_assistant_core_update":
                return await self._core(sitzung, update, integrationen, laenge), "github+blog"
            if (
                plattform == "hassio"
                and kennung.endswith("_version_latest")
                and not update["entity_id"].startswith("update.home_assistant_")
            ):
                text = await quellen.addon_aenderungen(sitzung, kennung[: -len("_version_latest")], update["installiert"])
                if text:
                    return quellen.kuerzen(text, laenge), "supervisor"
            if update["url"].startswith("https://github.com/"):
                text = await quellen.github_release(sitzung, update["url"])
                if text:
                    return quellen.kuerzen(text, laenge), "github"
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Notizen für %s nicht abrufbar: %s", update["entity_id"], err)
            return "", f"fehler: {type(err).__name__}"
        return "", "keine"

    async def _core(
        self, sitzung: aiohttp.ClientSession, update: dict[str, str], integrationen: list[str], laenge: int
    ) -> str:
        stuecke = []
        if update["installiert"].split(".")[:2] != update["neu"].split(".")[:2]:
            try:
                seite = await quellen.blog_html(sitzung)
                stuecke.append(await self.hass.async_add_executor_job(quellen.blog_brueche, seite, integrationen))
            except (aiohttp.ClientError, TimeoutError) as err:
                stuecke.append(f"Release-Blog nicht abrufbar ({type(err).__name__})")
        try:
            text = await quellen.github_release(
                sitzung, f"https://github.com/home-assistant/core/releases/tag/{update['neu']}"
            )
            if text and len(text) > 200:
                stuecke.append(f"Patch-Notizen {update['neu']}:\n{text[:2500]}")
        except (aiohttp.ClientError, TimeoutError):
            pass
        return quellen.kuerzen("\n\n".join(s for s in stuecke if s), max(laenge * 2, 7000))

    # ------------------------------------------------------------ Bericht
    async def async_bericht_ausloesen(self, erzwingen: bool = False) -> None:
        offene = self.offene()
        signatur = sorted(f"{u['entity_id']}|{u['neu']}" for u in offene)
        geaendert = signatur != self._gemeldet
        if erzwingen or geaendert or not self.opt(CONF_NUR_AENDERUNG):
            self.hass.bus.async_fire(
                EREIGNIS_BERICHT,
                {"anzahl": len(offene), "updates": [u["entity_id"] for u in offene], "geaendert": geaendert},
            )
            self._gemeldet = signatur
        self.letzter_bericht = dt_util.utcnow()
        self._store.async_delay_save(
            lambda: {"gemeldet": self._gemeldet, "letzter_bericht": self.letzter_bericht.isoformat()}, 2
        )
        self._melden()

    def _planen(self) -> None:
        if self._zeitplan is not None:
            self._zeitplan()
        jetzt = dt_util.now()
        stunde, minute, *_ = (int(x) for x in str(self.opt(CONF_UHRZEIT)).split(":"))
        anker = jetzt.replace(hour=stunde, minute=minute, second=0, microsecond=0)
        abstand = timedelta(hours=max(1, int(self.opt(CONF_INTERVALL))))
        while anker > jetzt:
            anker -= abstand
        while anker <= jetzt:
            anker += abstand
        self.naechster_bericht = anker

        @callback
        def _faellig(_zeit: datetime) -> None:
            self._zeitplan = None
            self.hass.async_create_background_task(self.async_bericht_ausloesen(), f"{DOMAIN}_bericht")
            self._planen()

        self._zeitplan = async_track_point_in_time(self.hass, _faellig, anker)
        self._melden()
