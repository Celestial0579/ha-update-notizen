"""Knopf: Bericht jetzt auslösen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NotizenEntitaet
from .sammler import Sammler


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([BerichtKnopf(entry.runtime_data)])


class BerichtKnopf(NotizenEntitaet, ButtonEntity):
    _attr_icon = "mdi:file-document-arrow-right"

    def __init__(self, sammler: Sammler) -> None:
        super().__init__(sammler, "bericht")

    async def async_press(self) -> None:
        await self._sammler.async_bericht_ausloesen(erzwingen=True)
