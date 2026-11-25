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

# Re-authentication keeps the account and brand of the entry, they are part of
# its title and unique ID
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})

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


def entry_title(brand_region: int, username: str) -> str:
    """Return the title of an entry for the given brand and username"""

    return f"{BRANDS[brand_region]} {username}"


def entry_unique_id(brand_region: int, username: str) -> str:
    """Return the unique ID of an entry for the given brand and username"""

    return hashlib.sha256(
        entry_title(brand_region, username).encode("utf-8")
    ).hexdigest()


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


async def async_try_login(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Log in with the given entry data, return the errors to show in the form"""

    try:
        await validate_input(hass, data)
    except InvalidAuth:
        return {"base": "invalid_auth"}
    except CannotConnect:
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return {"base": "unknown"}

    return {}


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

        if not (errors := await async_try_login(self.hass, user_input)):
            brand_region = user_input[CONF_BRAND_REGION]
            username = user_input[CONF_USERNAME]

            await self.async_set_unique_id(entry_unique_id(brand_region, username))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=entry_title(brand_region, username), data=user_input
            )

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
        """Ask for the password of the account the entry was set up with.

        The username and brand are kept. When the form asked for them again,
        an entry could end up using another brand or account while keeping
        its title, and get no vehicles.
        """

        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            if not (errors := await async_try_login(self.hass, data)):
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "username": entry.data[CONF_USERNAME],
                "brand": BRANDS[entry.data[CONF_BRAND_REGION]],
            },
        )


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CannotConnect(HomeAssistantError):
    """Error to indicate the Uconnect servers could not be reached."""
