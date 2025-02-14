"""Config flow for Uconnect integration."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from py_uconnect.api import API
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME

from .const import (
    BRANDS,
    CONF_BRAND_REGION,
    CONF_DISABLE_TLS_VERIFICATION,
    CONF_ADD_COMMAND_ENTITIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PIN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_BRAND_REGION): vol.In(BRANDS),
        vol.Optional(CONF_PIN, default=DEFAULT_PIN): str,
        vol.Required(CONF_DISABLE_TLS_VERIFICATION, default=False): bool,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=DEFAULT_SCAN_INTERVAL,
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=999)),
        vol.Required(CONF_ADD_COMMAND_ENTITIES): bool,
    }
)


async def validate_input(hass: HomeAssistant, user_input: dict[str, Any]):
    """Validate the user input allows us to connect."""

    try:
        api = API(
            email=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            pin=user_input[CONF_PIN],
            brand=BRANDS_BY_NAME[BRANDS[user_input[CONF_BRAND_REGION]]],
            disable_tls_verification=user_input[CONF_DISABLE_TLS_VERIFICATION],
        )

        await hass.async_add_executor_job(api.login)
    except Exception as e:
        _LOGGER.exception(f"Authentication failed: {e}")
        raise InvalidAuth


class UconnectOptionFlowHandler(config_entries.OptionsFlow):
    """Handle an option flow for Uconnect"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options init setup."""

        if user_input is not None:
            return self.async_create_entry(
                title=self.config_entry.title, data=user_input
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Uconnect"""

    VERSION = 1
    reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Initiate options flow instance."""
        return UconnectOptionFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""

        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            await validate_input(self.hass, user_input)
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            if self.reauth_entry is None:
                title = f"{BRANDS[user_input[CONF_BRAND_REGION]]} {
                    user_input[CONF_USERNAME]}"
                await self.async_set_unique_id(
                    hashlib.sha256(title.encode("utf-8")).hexdigest()
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=user_input)
            else:
                self.hass.config_entries.async_update_entry(
                    self.reauth_entry, data=user_input
                )
                await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input=None):
        """Perform reauth upon an API authentication error."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
            )
        self._reauth_config = True
        return await self.async_step_user()


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
