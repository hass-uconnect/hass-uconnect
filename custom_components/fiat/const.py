"""Constants for the Fiat integration"""

from pyfiat.brands import *

DOMAIN: str = "fiat"

CONF_BRAND_REGION: str = "brand_region"

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
    16: FIAT_CAN.name,
}

DEFAULT_PIN: str = ""
DEFAULT_SCAN_INTERVAL: int = 5

UNIT_DYNAMIC: str = "dynamic"
