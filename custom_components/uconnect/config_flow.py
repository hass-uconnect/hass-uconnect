"""Config flow for Uconnect integration."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlowResult
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from py_uconnect import API, AuthenticationError, UconnectError
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME
import stellantis_ssdp
from stellantis_ssdp import (
    RemoteAuthenticationError,
    SSDPError,
    State,
    Token,
    password_login,
)
import voluptuous as vol

from .const import (
    BRANDS,
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    CONF_SMS_CODE,
    CONF_SSDP_STATE,
    DEFAULT_CHARGING_REFRESH_INTERVAL,
    DEFAULT_PIN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SSDP_BRANDS,
    is_ssdp_brand,
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

# Options of the entries of SSDP brands: no deep refresh while charging
SSDP_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=DEFAULT_SCAN_INTERVAL,
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=999)),
        vol.Optional(CONF_PIN, default=DEFAULT_PIN): str,
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


async def async_try_ssdp_login(
    data: dict[str, Any],
) -> tuple[dict[str, str], Token | None]:
    """Log in to an SSDP brand with the entry data, return the form errors and
    the account token"""

    try:
        token = await password_login(
            SSDP_BRANDS[data[CONF_BRAND_REGION]],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
    except stellantis_ssdp.AuthenticationError as err:
        _LOGGER.warning("Authentication failed: %s", err)
        return {"base": "invalid_auth"}, None
    except SSDPError as err:
        _LOGGER.warning("Unable to connect: %s", err)
        return {"base": "cannot_connect"}, None
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return {"base": "unknown"}, None

    return {}, token


def ssdp_enroll_schema(pin: str) -> vol.Schema:
    """Form asking for the SMS code and the PIN"""

    return vol.Schema(
        {
            vol.Required(CONF_SMS_CODE): str,
            vol.Required(CONF_PIN, default=pin): str,
        }
    )


async def async_ssdp_send_sms(client: stellantis_ssdp.Client) -> dict[str, str]:
    """Send the SMS with the activation code, return the form errors"""

    try:
        await client.enroll_start()
    except SSDPError as err:
        _LOGGER.warning("Unable to send the SMS: %s", err)
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected exception")
        return {"base": "unknown"}

    return {}


async def async_ssdp_enroll(
    client: stellantis_ssdp.Client, user_input: dict[str, Any]
) -> dict[str, str]:
    """Set up remote commands with the SMS code and the PIN, return the form
    errors"""

    try:
        await client.enroll_finish(
            user_input[CONF_SMS_CODE].strip(), user_input[CONF_PIN].strip()
        )
    except RemoteAuthenticationError as err:
        _LOGGER.warning("Remote command setup failed: %s", err)
        return {"base": "invalid_code"}
    except SSDPError as err:
        _LOGGER.warning("Unable to connect: %s", err)
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

        if is_ssdp_brand(self.config_entry.data[CONF_BRAND_REGION]):
            return await self.async_step_ssdp_menu()

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

    async def async_step_ssdp_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Options menu of an entry of an SSDP brand"""

        return self.async_show_menu(
            step_id="ssdp_menu", menu_options=["ssdp_settings", "ssdp_send_sms"]
        )

    async def async_step_ssdp_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Options of an entry of an SSDP brand"""

        if user_input is not None:
            return self.async_create_entry(
                title=self.config_entry.title,
                data={**self.config_entry.options, **user_input},
            )

        return self.async_show_form(
            step_id="ssdp_settings",
            data_schema=self.add_suggested_values_to_schema(
                SSDP_OPTIONS_SCHEMA, self.config_entry.options
            ),
        )

    def _ssdp_client(self) -> stellantis_ssdp.Client | None:
        """The client of the running entry: remote commands are set up with
        it, so that its state is saved"""

        entry = self.config_entry
        coordinator = getattr(entry, "runtime_data", None)
        if entry.state is not ConfigEntryState.LOADED or coordinator is None:
            return None
        return getattr(coordinator, "client", None)

    async def async_step_ssdp_send_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send the SMS with the code that sets up remote commands"""

        if (client := self._ssdp_client()) is None:
            return self.async_abort(reason="not_loaded")

        if errors := await async_ssdp_send_sms(client):
            return self.async_show_form(
                step_id="ssdp_send_sms", data_schema=vol.Schema({}), errors=errors
            )

        return await self.async_step_ssdp_enroll()

    async def async_step_ssdp_enroll(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the SMS code and the PIN, set up remote commands"""

        if (client := self._ssdp_client()) is None:
            return self.async_abort(reason="not_loaded")

        entry = self.config_entry
        pin = entry.options.get(CONF_PIN) or entry.data.get(CONF_PIN) or DEFAULT_PIN
        errors: dict[str, str] = {}

        if user_input is not None:
            if not (errors := await async_ssdp_enroll(client, user_input)):
                # The command entities are added by the reload that the
                # coordinator schedules when it sees the change
                return self.async_create_entry(
                    title=entry.title,
                    data={
                        **entry.options,
                        CONF_PIN: user_input[CONF_PIN].strip(),
                        CONF_ADD_COMMAND_ENTITIES: True,
                    },
                )
            pin = user_input[CONF_PIN]

        return self.async_show_form(
            step_id="ssdp_enroll", data_schema=ssdp_enroll_schema(pin), errors=errors
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Uconnect"""

    VERSION = 1

    def __init__(self) -> None:
        # Data of an SSDP entry being set up, and its client
        self._ssdp_data: dict[str, Any] = {}
        self._ssdp_client: stellantis_ssdp.Client | None = None

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

        if is_ssdp_brand(user_input[CONF_BRAND_REGION]):
            return await self._async_ssdp_user(user_input)

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

    async def _async_ssdp_user(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Log in to an SSDP brand, then offer to set up remote commands"""

        errors, token = await async_try_ssdp_login(user_input)
        if errors or token is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        # Before an SMS is sent
        await self.async_set_unique_id(
            entry_unique_id(user_input[CONF_BRAND_REGION], user_input[CONF_USERNAME])
        )
        self._abort_if_unique_id_configured()

        self._ssdp_data = {
            **user_input,
            CONF_SSDP_STATE: State(token=token).to_dict(),
        }
        return await self.async_step_ssdp_remote()

    async def async_step_ssdp_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to set up remote commands"""

        return self.async_show_menu(
            step_id="ssdp_remote", menu_options=["ssdp_send_sms", "ssdp_finish"]
        )

    def _async_create_ssdp_entry(
        self, options: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        data = self._ssdp_data
        return self.async_create_entry(
            title=entry_title(data[CONF_BRAND_REGION], data[CONF_USERNAME]),
            data=data,
            options=options or {},
        )

    async def async_step_ssdp_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry without remote commands"""

        return self._async_create_ssdp_entry()

    async def async_step_ssdp_send_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send the SMS with the code that sets up remote commands"""

        data = self._ssdp_data
        if self._ssdp_client is None:
            self._ssdp_client = stellantis_ssdp.Client(
                SSDP_BRANDS[data[CONF_BRAND_REGION]],
                State.from_dict(data[CONF_SSDP_STATE]),
                session=async_get_clientsession(
                    self.hass, verify_ssl=not data.get(CONF_DISABLE_TLS_VERIFICATION)
                ),
            )

        if errors := await async_ssdp_send_sms(self._ssdp_client):
            return self.async_show_form(
                step_id="ssdp_send_sms", data_schema=vol.Schema({}), errors=errors
            )

        return await self.async_step_ssdp_enroll()

    async def async_step_ssdp_enroll(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the SMS code and the PIN, set up remote commands"""

        client = self._ssdp_client
        assert client is not None
        pin = self._ssdp_data.get(CONF_PIN) or DEFAULT_PIN
        errors: dict[str, str] = {}

        if user_input is not None:
            if not (errors := await async_ssdp_enroll(client, user_input)):
                self._ssdp_data = {
                    **self._ssdp_data,
                    CONF_PIN: user_input[CONF_PIN].strip(),
                    CONF_SSDP_STATE: client.state.to_dict(),
                }
                return self._async_create_ssdp_entry({CONF_ADD_COMMAND_ENTITIES: True})
            pin = user_input[CONF_PIN]

        return self.async_show_form(
            step_id="ssdp_enroll", data_schema=ssdp_enroll_schema(pin), errors=errors
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
            if is_ssdp_brand(entry.data[CONF_BRAND_REGION]):
                errors, token = await async_try_ssdp_login(data)
                if not errors and token is not None:
                    data[CONF_SSDP_STATE] = ssdp_state_with_token(
                        entry.data.get(CONF_SSDP_STATE), token
                    ).to_dict()
                    return self.async_update_reload_and_abort(entry, data=data)
            elif not (errors := await async_try_login(self.hass, data)):
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


def ssdp_state_with_token(old: dict[str, Any] | None, token: Token) -> State:
    """The state of an SSDP entry after a new login: the remote-command setup
    of the same account is kept, it can only be redone with an SMS"""

    state = State(token=token)
    try:
        previous = State.from_dict(old) if old else None
    except ValueError:
        previous = None

    if previous is not None and previous.token.user_id == token.user_id:
        state.soft_token = previous.soft_token
        state.remote_token = previous.remote_token

    return state


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CannotConnect(HomeAssistantError):
    """Error to indicate the Uconnect servers could not be reached."""
