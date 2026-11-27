"""Brand selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from py_uconnect.brands import BRANDS as BRANDS_BY_NAME
import stellantis_ssdp

from custom_components.uconnect.const import BRANDS, DOMAIN, SSDP_BRANDS, is_ssdp_brand

from .test_config_flow import USER_INPUT

# Config entries store the number of the selected brand, so the existing
# numbers must keep their meaning
RELEASED_BRANDS = {
    1: "FIAT_EU",
    2: "FIAT_US",
    3: "RAM_US",
    4: "DODGE_US",
    5: "JEEP_EU",
    6: "JEEP_US",
    7: "MASERATI_ASIA",
    8: "MASERATI_EU",
    9: "MASERATI_US_CANADA",
    10: "CHRYSLER_CANADA",
    11: "CHRYSLER_US",
    12: "ALFA_ROMEO_ASIA",
    13: "ALFA_ROMEO_EU",
    14: "ALFA_ROMEO_US_CANADA",
    15: "FIAT_ASIA",
    16: "FIAT_CANADA",
    17: "JEEP_ASIA",
}


def test_brand_numbers_are_stable() -> None:
    assert {k: v for k, v in BRANDS.items() if k in RELEASED_BRANDS} == (
        RELEASED_BRANDS
    )


def test_brands_exist_in_the_library() -> None:
    uconnect = {n: name for n, name in BRANDS.items() if n not in SSDP_BRANDS}
    assert set(uconnect.values()) <= set(BRANDS_BY_NAME)
    assert len(set(BRANDS.values())) == len(BRANDS)


def test_ssdp_brands() -> None:
    expected = {
        21: ("JEEP_EU_SSDP", stellantis_ssdp.JEEP_EU),
        22: ("PEUGEOT_EU_SSDP", stellantis_ssdp.PEUGEOT_EU),
        23: ("CITROEN_EU_SSDP", stellantis_ssdp.CITROEN_EU),
        24: ("OPEL_EU_SSDP", stellantis_ssdp.OPEL_EU),
        25: ("VAUXHALL_EU_SSDP", stellantis_ssdp.VAUXHALL_EU),
        26: ("LANCIA_EU_SSDP", stellantis_ssdp.LANCIA_EU),
    }

    assert {n: (BRANDS[n], SSDP_BRANDS[n]) for n in SSDP_BRANDS} == expected
    assert all(is_ssdp_brand(n) for n in expected)
    assert not any(is_ssdp_brand(n) for n in range(1, 21))
    # No Uconnect brand name is reused
    assert not set(BRANDS_BY_NAME) & {name for name, _ in expected.values()}


def test_latam_brands() -> None:
    assert {BRANDS[n] for n in (18, 19, 20)} == {
        "JEEP_LATAM",
        "FIAT_LATAM",
        "RAM_LATAM",
    }


async def test_user_flow_latam(hass: HomeAssistant) -> None:
    api = MagicMock()
    api.return_value.login = AsyncMock()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with (
        patch("custom_components.uconnect.config_flow.API", api),
        patch("custom_components.uconnect.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, "brand_region": 18}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "JEEP_LATAM user@example.com"
    assert api.call_args.kwargs["brand"].name == "JEEP_LATAM"
