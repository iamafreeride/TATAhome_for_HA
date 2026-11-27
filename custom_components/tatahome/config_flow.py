"""Config flow for TATAHome."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .cloud import CloudError, CloudSession
from .const import (
    CONF_EMAIL,
    CONF_HEARTBEAT,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_HEARTBEAT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_EMAIL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
)


class TATAHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the TATAHome cloud account flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cloud = CloudSession()
            try:
                result = await self.hass.async_add_executor_job(
                    cloud.login, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except CloudError:
                errors["base"] = "cannot_connect"
            else:
                if not result.ok:
                    errors["base"] = "invalid_auth"
                else:
                    await self.async_set_unique_id(str(result.uid))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=result.nickname or user_input[CONF_EMAIL],
                        data=user_input,
                        options={
                            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                            CONF_HEARTBEAT: DEFAULT_HEARTBEAT,
                        },
                    )
            finally:
                await self.hass.async_add_executor_job(cloud.close)
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            cloud = CloudSession()
            try:
                result = await self.hass.async_add_executor_job(
                    cloud.login,
                    reauth_entry.data[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
            except CloudError:
                errors["base"] = "cannot_connect"
            else:
                if not result.ok:
                    errors["base"] = "invalid_auth"
                else:
                    return self.async_update_reload_and_abort(
                        reauth_entry,
                        data={
                            **reauth_entry.data,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
            finally:
                await self.hass.async_add_executor_job(cloud.close)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            description_placeholders={"email": reauth_entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TATAHomeOptionsFlow()


class TATAHomeOptionsFlow(OptionsFlow):
    """Polling/heartbeat options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_HEARTBEAT,
                    default=options.get(CONF_HEARTBEAT, DEFAULT_HEARTBEAT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30,
                        max=600,
                        step=30,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
