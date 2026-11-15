"""Ausgenommene Updates, Erkennung über das Register und Längen nach max_zeichen (#10, #11, #12)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.update_notizen import quellen
from custom_components.update_notizen.const import (
    CONF_AUSGENOMMEN,
    CONF_INTERVALL,
    CONF_MAX_ZEICHEN,
    CONF_NUR_AENDERUNG,
    CONF_UHRZEIT,
    DOMAIN,
    EREIGNIS_BERICHT,
)
from custom_components.update_notizen.sammler import Sammler

GRUNDWERTE = {CONF_UHRZEIT: "10:00:00", CONF_INTERVALL: 24, CONF_NUR_AENDERUNG: True, CONF_MAX_ZEICHEN: 3500}


def _update(hass: HomeAssistant, entity_id: str, plattform: str, kennung: str, url: str = "") -> er.RegistryEntry:
    eintrag = er.async_get(hass).async_get_or_create(
        "update", plattform, kennung, suggested_object_id=entity_id.split(".")[1]
    )
    hass.states.async_set(
        eintrag.entity_id, "on", {"installed_version": "2026.9.3", "latest_version": "2026.11.1", "release_url": url}
    )
    return eintrag


async def _einrichten(hass: HomeAssistant, **optionen) -> MockConfigEntry:
    eintrag = MockConfigEntry(domain=DOMAIN, version=1, minor_version=2, options={**GRUNDWERTE, **optionen})
    eintrag.add_to_hass(hass)
    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await hass.async_block_till_done()
    return eintrag


async def test_optionen_speichern_register_id_und_filtern(hass: HomeAssistant) -> None:
    nextcloud = _update(hass, "update.cloud", "nextcloud", "nc1")
    _update(hass, "update.anderes", "hacs", "h1")
    eintrag = await _einrichten(hass)

    ablauf = await hass.config_entries.options.async_init(eintrag.entry_id)
    assert ablauf["type"] is FlowResultType.FORM
    ergebnis = await hass.config_entries.options.async_configure(
        ablauf["flow_id"], {**GRUNDWERTE, CONF_AUSGENOMMEN: ["update.cloud"]}
    )
    assert ergebnis["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert eintrag.options[CONF_AUSGENOMMEN] == [nextcloud.id]  # Register-ID, nicht die Entitäts-ID
    assert eintrag.state is ConfigEntryState.LOADED

    sammler: Sammler = eintrag.runtime_data
    assert [u["entity_id"] for u in sammler.offene()] == ["update.anderes"]
    notizen = await sammler.async_notizen(["update.cloud", "update.anderes"])
    assert list(notizen["updates"]) == ["update.anderes"]
    assert hass.states.get("sensor.update_notizen_pending_updates").state == "1"

    # Umbenennen hebt die Ausnahme nicht auf, und das Formular zeigt den neuen Namen.
    er.async_get(hass).async_update_entity("update.cloud", new_entity_id="update.nextcloud")
    hass.states.async_remove("update.cloud")
    hass.states.async_set("update.nextcloud", "on", {"latest_version": "2"})
    await hass.async_block_till_done()
    assert [u["entity_id"] for u in sammler.offene()] == ["update.anderes"]
    ablauf = await hass.config_entries.options.async_init(eintrag.entry_id)
    vorschlag = [k.description["suggested_value"] for k in ablauf["data_schema"].schema if k == CONF_AUSGENOMMEN]
    assert vorschlag == [["update.nextcloud"]]
    await hass.config_entries.options.async_configure(ablauf["flow_id"], {**GRUNDWERTE})  # Feld geleert
    await hass.async_block_till_done()
    assert eintrag.options[CONF_AUSGENOMMEN] == []


async def test_bericht_und_signatur_ohne_ausgenommene(hass: HomeAssistant) -> None:
    nextcloud = _update(hass, "update.cloud", "nextcloud", "nc1")
    _update(hass, "update.anderes", "hacs", "h1")
    eintrag = await _einrichten(hass, **{CONF_AUSGENOMMEN: [nextcloud.id]})
    sammler: Sammler = eintrag.runtime_data
    ereignisse = async_capture_events(hass, EREIGNIS_BERICHT)

    await sammler.async_bericht_ausloesen()
    # Neue Fassung des ausgenommenen Updates: mit „nur bei Änderung“ kein neuer Bericht.
    hass.states.async_set("update.cloud", "on", {"latest_version": "99"})
    await sammler.async_bericht_ausloesen()
    await hass.async_block_till_done()
    assert len(ereignisse) == 1
    assert ereignisse[0].data["updates"] == ["update.anderes"]


async def test_migration_ergaenzt_leere_ausnahmeliste(hass: HomeAssistant) -> None:
    eintrag = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, options=dict(GRUNDWERTE))
    eintrag.add_to_hass(hass)
    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await hass.async_block_till_done()
    assert eintrag.minor_version == 2
    assert eintrag.options == {**GRUNDWERTE, CONF_AUSGENOMMEN: []}

    neuer = MockConfigEntry(domain=DOMAIN, version=2, options={})
    neuer.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(neuer.entry_id)
    assert neuer.state is ConfigEntryState.MIGRATION_ERROR


async def test_system_updates_nur_ueber_das_register(hass: HomeAssistant) -> None:
    eintrag = MockConfigEntry(domain=DOMAIN)
    eintrag.add_to_hass(hass)
    sammler = Sammler(hass, eintrag)
    _update(hass, "update.os", "hassio", "home_assistant_os_version_latest", "https://github.com/home-assistant/operating-system/releases/tag/17.0")
    _update(hass, "update.mosquitto", "hassio", "core_mosquitto_version_latest")
    # Ohne Registereintrag zählt die Standard-Entitäts-ID nicht mehr als Core.
    hass.states.async_set(
        "update.home_assistant_core_update", "on", {"installed_version": "2026.9.3", "latest_version": "2026.11.1"}
    )
    addon = AsyncMock(return_value="## neu")
    with (
        patch.object(quellen, "addon_aenderungen", addon),
        patch.object(quellen, "github_release", AsyncMock(return_value="OS-Notizen")),
        patch.object(quellen, "blog_html", AsyncMock()) as blog,
    ):
        antwort = (await sammler.async_notizen())["updates"]
    assert antwort["update.os"]["quelle"] == "github"
    assert antwort["update.mosquitto"]["quelle"] == "supervisor"
    assert antwort["update.home_assistant_core_update"]["quelle"] == "keine"
    addon.assert_awaited_once()
    assert addon.await_args.args[1] == "core_mosquitto"
    blog.assert_not_awaited()


async def test_core_laengen_folgen_max_zeichen(hass: HomeAssistant) -> None:
    eintrag = MockConfigEntry(domain=DOMAIN, options={CONF_MAX_ZEICHEN: 1000})
    eintrag.add_to_hass(hass)
    sammler = Sammler(hass, eintrag)
    _update(hass, "update.core", "hassio", "home_assistant_core_version_latest")
    blog = "<title>B</title><h2>Backward-incompatible changes</h2>" + "".join(
        f"<details><summary>Teil{n}</summary><p>{'y' * 3000}</p></details>" for n in range(10)
    )
    with (
        patch.object(quellen, "blog_html", AsyncMock(return_value=blog)),
        patch.object(quellen, "github_release", AsyncMock(return_value="x" * 5000)),
    ):
        text = (await sammler.async_notizen())["updates"]["update.core"]["notizen"]
    assert len(text) <= 2000 + len(" […]")  # früher nie unter 7000
    assert "x" * (1000 * 5 // 7 + 1) not in text


def test_blog_eintraege_nach_max_zeichen() -> None:
    seite = (
        "<h2>Backward-incompatible changes</h2>"
        f"<details><summary>Ecovacs</summary><p>{'a' * 2000}</p></details>"
        f"<details><summary>Automations</summary><p>{'b' * 2000}</p></details>"
    )
    kurz = quellen.blog_brueche(seite, ["ecovacs"], 1000)
    assert "a" * 200 in kurz and "a" * 201 not in kurz
    assert "b" * 142 in kurz and "b" * 143 not in kurz
    vorgabe = quellen.blog_brueche(seite, ["ecovacs"])
    assert "a" * 700 in vorgabe and "a" * 701 not in vorgabe  # Vorgabe 3500 ergibt die bisherigen Längen
    assert "b" * 500 in vorgabe and "b" * 501 not in vorgabe
