"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .sammler import Sammler


class NotizenEntitaet(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, sammler: Sammler, schluessel: str) -> None:
        self._sammler = sammler
        self._attr_translation_key = schluessel
        self._attr_unique_id = f"{sammler.entry.entry_id}_{schluessel}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sammler.entry.entry_id)},
            name="Update-Notizen",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._sammler.zuhoerer_hinzufuegen(self._aktualisieren))

    @callback
    def _aktualisieren(self) -> None:
        self.async_write_ha_state()
