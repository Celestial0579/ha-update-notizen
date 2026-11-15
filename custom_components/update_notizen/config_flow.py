"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_AUSGENOMMEN,
    CONF_INTERVALL,
    CONF_MAX_ZEICHEN,
    CONF_NUR_AENDERUNG,
    CONF_UHRZEIT,
    DOMAIN,
    STANDARD_OPTIONEN,
)


class UpdateNotizenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichten bestätigen."""

    VERSION = 1
    MINOR_VERSION = 2  # 1.2: Option „ausgenommen“

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Update-Notizen", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UpdateNotizenOptionsFlow()


class UpdateNotizenOptionsFlow(OptionsFlow):
    """Takt, Umfang und ausgenommene Updates einstellen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        register = er.async_get(self.hass)
        if user_input is not None:
            # Als Register-ID speichern: Die Ausnahme bleibt, wenn die Entität umbenannt wird.
            ids = []
            for entity_id in user_input.get(CONF_AUSGENOMMEN, []):
                eintrag = register.async_get(entity_id)
                ids.append(eintrag.id if eintrag else entity_id)
            return self.async_create_entry(data={**user_input, CONF_AUSGENOMMEN: ids})
        o = {**STANDARD_OPTIONEN, **self.config_entry.options}
        ausgenommen = [e for k in o[CONF_AUSGENOMMEN] if (e := er.async_resolve_entity_id(register, k))]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UHRZEIT, default=o[CONF_UHRZEIT]): selector.TimeSelector(),
                    vol.Required(CONF_INTERVALL, default=o[CONF_INTERVALL]): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=168, step=1, unit_of_measurement="h", mode=selector.NumberSelectorMode.BOX)
                    ),
                    vol.Required(CONF_NUR_AENDERUNG, default=o[CONF_NUR_AENDERUNG]): bool,
                    vol.Required(CONF_MAX_ZEICHEN, default=o[CONF_MAX_ZEICHEN]): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=500, max=20000, step=100, mode=selector.NumberSelectorMode.BOX)
                    ),
                    # Vorschlag statt Vorgabe, sonst ließe sich die Liste nicht leeren.
                    vol.Optional(CONF_AUSGENOMMEN, description={"suggested_value": ausgenommen}): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="update", multiple=True)
                    ),
                }
            ),
        )
