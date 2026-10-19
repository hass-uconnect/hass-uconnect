"""Config, options and reauth flows."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PIN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from py_uconnect import AuthenticationError, UconnectConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.uconnect.const import (
    CONF_ADD_COMMAND_ENTITIES,
    CONF_BRAND_REGION,
    CONF_CHARGING_REFRESH_INTERVAL,
    CONF_DISABLE_TLS_VERIFICATION,
    DOMAIN,
)

from .conftest import FakeClient

USER_INPUT = {
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "secret",
    CONF_BRAND_REGION: 1,
    CONF_PIN: "1234",
    CONF_DISABLE_TLS_VERIFICATION: False,
}


@pytest.fixture
def mock_api() -> Iterator[MagicMock]:
    api = MagicMock()
    api.return_value.login = AsyncMock()
    with patch("custom_components.uconnect.config_flow.API", api):
        yield api


async def test_user_flow(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.uconnect.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FIAT_EU user@example.com"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id is not None

    kwargs = mock_api.call_args.kwargs
    assert kwargs["email"] == "user@example.com"
    assert kwargs["brand"].name == "FIAT_EU"
    mock_api.return_value.login.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AuthenticationError("Invalid LoginID"), "invalid_auth"),
        (UconnectConnectionError("timeout"), "cannot_connect"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_api: MagicMock, error: Exception, reason: str
) -> None:
    mock_api.return_value.login.side_effect = error

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    # The user can fix the input and retry
    mock_api.return_value.login.side_effect = None
    with patch("custom_components.uconnect.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_api: MagicMock
) -> None:
    for expected in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch("custom_components.uconnect.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], USER_INPUT
            )
        assert result["type"] is expected

    assert result["reason"] == "already_configured"


async def test_options_flow(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 10,
            CONF_PIN: "4321",
            CONF_CHARGING_REFRESH_INTERVAL: 5,
            CONF_ADD_COMMAND_ENTITIES: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    coordinator = setup_integration.runtime_data
    assert coordinator.update_interval.total_seconds() == 600
    # Raised to the minimum
    assert coordinator.charging_refresh_interval == 15
    assert fake_client.api.pin == "4321"


async def test_reauth_flow(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_client: FakeClient,
    mock_api: MagicMock,
) -> None:
    fake_client.refresh.side_effect = AuthenticationError("Invalid password")
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    fake_client.refresh.side_effect = fake_client._refresh
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PASSWORD: "new-secret"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "new-secret"
    assert config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(config_entry.entry_id)
