"""Constants for the Uconnect integration"""

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
    FIAT_US,
    JEEP_ASIA,
    JEEP_EU,
    JEEP_US,
    MASERATI_ASIA,
    MASERATI_EU,
    MASERATI_US_CANADA,
    RAM_US,
)

DOMAIN: str = "uconnect"

CONF_BRAND_REGION: str = "brand_region"
CONF_DISABLE_TLS_VERIFICATION: str = "disable_tls_verification"
CONF_ADD_COMMAND_ENTITIES: str = "add_command_entities"

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
}

DEFAULT_PIN: str = ""
DEFAULT_SCAN_INTERVAL: int = 5

UNIT_DYNAMIC: str = "dynamic"
