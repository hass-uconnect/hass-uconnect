"""Config flow for Uconnect integration."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from py_uconnect import API, AuthenticationError, UconnectError
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME
import voluptuous as vol

from .const import (
    BRANDS,
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    DEFAULT_CHARGING_REFRESH_INTERVAL,
    DEFAULT_PIN,
    DEFAULT_SCAN_INTERVAL,
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
        vol.Optional(CONF_PIN, default=DEFAULT_PIN): str,
        vol.Required(
            CONF_CHARGING_REFRESH_INTERVAL,
            default=DEFAULT_CHARGING_REFRESH_INTERVAL,
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1440)),
        vol.Required(CONF_ADD_COMMAND_ENTITIES): bool,
    }
)


async def validate_input(hass: HomeAssistant, user_input: dict[str, Any]) -> None:
    """Validate the user input allows us to connect."""

    session = async_create_clientsession(
        hass,
        verify_ssl=not user_input.get(CONF_DISABLE_TLS_VERIFICATION),
        auto_cleanup=False,
    )

    try:
        api = API(
            email=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            pin=user_input.get(CONF_PIN),
            brand=BRANDS_BY_NAME[BRANDS[user_input[CONF_BRAND_REGION]]],
            session=session,
        )
        await api.login()
    except AuthenticationError as err:
        _LOGGER.warning("Authentication failed: %s", err)
        raise InvalidAuth from err
    except UconnectError as err:
        _LOGGER.warning("Unable to connect: %s", err)
        raise CannotConnect from err
    finally:
        session.detach()


class UconnectOptionFlowHandler(config_entries.OptionsFlow):
    """Handle an option flow for Uconnect"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Initiate options flow instance."""
        return UconnectOptionFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            if self.source == config_entries.SOURCE_REAUTH:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data=user_input
                )

            title = (
                f"{BRANDS[user_input[CONF_BRAND_REGION]]} {user_input[CONF_USERNAME]}"
            )
            await self.async_set_unique_id(
                hashlib.sha256(title.encode("utf-8")).hexdigest()
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
            )
        return await self.async_step_user()


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CannotConnect(HomeAssistantError):
    """Error to indicate the Uconnect servers could not be reached."""
