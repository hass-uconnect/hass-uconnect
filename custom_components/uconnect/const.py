"""Constants for the Uconnect integration"""

from datetime import timedelta

from py_uconnect.brands import (
    ALFA_ROMEO_ASIA,
    ALFA_ROMEO_EU,
    ALFA_ROMEO_US_CANADA,
    CHRYSLER_CANADA,
    CHRYSLER_US,
    DODGE_US,
    FIAT_ASIA,
    FIAT_CANADA,
    FIAT_EU,
    FIAT_LATAM,
    FIAT_US,
    JEEP_ASIA,
    JEEP_EU,
    JEEP_LATAM,
    JEEP_US,
    MASERATI_ASIA,
    MASERATI_EU,
    MASERATI_US_CANADA,
    RAM_LATAM,
    RAM_US,
)
import stellantis_ssdp

DOMAIN: str = "uconnect"

CONF_BRAND_REGION: str = "brand_region"
CONF_DISABLE_TLS_VERIFICATION: str = "disable_tls_verification"
CONF_ADD_COMMAND_ENTITIES: str = "add_command_entities"
CONF_CHARGING_REFRESH_INTERVAL: str = "charging_refresh_interval"
# SSDP entries: tokens and inWebo soft token (stellantis_ssdp.State)
CONF_SSDP_STATE: str = "ssdp_state"
CONF_SMS_CODE: str = "sms_code"

BRANDS = {
    1: FIAT_EU.name,
    2: FIAT_US.name,
    3: RAM_US.name,
    4: DODGE_US.name,
    5: JEEP_EU.name,
    6: JEEP_US.name,
    7: MASERATI_ASIA.name,
    8: MASERATI_EU.name,
    9: MASERATI_US_CANADA.name,
    10: CHRYSLER_CANADA.name,
    11: CHRYSLER_US.name,
    12: ALFA_ROMEO_ASIA.name,
    13: ALFA_ROMEO_EU.name,
    14: ALFA_ROMEO_US_CANADA.name,
    15: FIAT_ASIA.name,
    16: FIAT_CANADA.name,
    17: JEEP_ASIA.name,
    # New entries get new numbers: config entries store the number
    18: JEEP_LATAM.name,
    19: FIAT_LATAM.name,
    20: RAM_LATAM.name,
    # Brands of the Stellantis SSDP cloud (the brands' "2.0" apps), served by
    # py-stellantis-ssdp instead of py-uconnect
    21: "JEEP_EU_SSDP",
    22: "PEUGEOT_EU_SSDP",
    23: "CITROEN_EU_SSDP",
    24: "OPEL_EU_SSDP",
    25: "VAUXHALL_EU_SSDP",
    26: "LANCIA_EU_SSDP",
}

SSDP_BRANDS: dict[int, stellantis_ssdp.Brand] = {
    21: stellantis_ssdp.JEEP_EU,
    22: stellantis_ssdp.PEUGEOT_EU,
    23: stellantis_ssdp.CITROEN_EU,
    24: stellantis_ssdp.OPEL_EU,
    25: stellantis_ssdp.VAUXHALL_EU,
    26: stellantis_ssdp.LANCIA_EU,
}


def is_ssdp_brand(brand_region: int) -> bool:
    """Whether the brand number is one of the SSDP cloud"""

    return brand_region in SSDP_BRANDS


DEFAULT_PIN: str = ""
DEFAULT_SCAN_INTERVAL: int = 5
DEFAULT_CHARGING_REFRESH_INTERVAL: int = 30
MIN_CHARGING_REFRESH_INTERVAL: int = 15

# How often the data that rarely changes (health report, maintenance, stolen
# vehicle status) is refreshed
EXTRA_DATA_INTERVAL = timedelta(minutes=30)

UNIT_DYNAMIC: str = "dynamic"
