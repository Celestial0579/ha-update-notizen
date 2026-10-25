"""Update-Notizen: Änderungsnotizen zu offenen Updates und ein einstellbarer Berichtstakt."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DIENST_ABRUFEN, DOMAIN
from .sammler import Sammler

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type UpdateNotizenConfigEntry = ConfigEntry[Sammler]

ABRUFEN_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def abrufen(aufruf: ServiceCall) -> ServiceResponse:
        eintraege = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
        if not eintraege:
            raise ServiceValidationError("Update-Notizen ist nicht eingerichtet.")
        sammler: Sammler = eintraege[0].runtime_data
        return await sammler.async_notizen(aufruf.data.get(ATTR_ENTITY_ID))

    hass.services.async_register(
        DOMAIN, DIENST_ABRUFEN, abrufen, schema=ABRUFEN_SCHEMA, supports_response=SupportsResponse.ONLY
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: UpdateNotizenConfigEntry) -> bool:
    sammler = Sammler(hass, entry)
    entry.runtime_data = sammler
    await sammler.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_optionen_geaendert))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UpdateNotizenConfigEntry) -> bool:
    if ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return ok


async def _optionen_geaendert(hass: HomeAssistant, entry: UpdateNotizenConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
