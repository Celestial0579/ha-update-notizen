"""Sensor: offene Updates."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import NotizenEntitaet
from .sammler import Sammler


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([OffeneSensor(entry.runtime_data)])


class OffeneSensor(NotizenEntitaet, SensorEntity):
    _attr_icon = "mdi:package-up"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, sammler: Sammler) -> None:
        super().__init__(sammler, "offene")

    @property
    def native_value(self) -> int:
        return len(self._sammler.offene())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "updates": [f"{u['name']}: {u['installiert']} → {u['neu']}" for u in self._sammler.offene()],
            "letzter_bericht": self._sammler.letzter_bericht.isoformat() if self._sammler.letzter_bericht else None,
            "naechster_bericht": self._sammler.naechster_bericht.isoformat() if self._sammler.naechster_bericht else None,
        }
