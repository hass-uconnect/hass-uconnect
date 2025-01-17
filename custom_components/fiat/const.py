"""Constants for the Fiat integration"""

from pyfiat.brands import (
    FIAT_EU, FIAT_US, RAM_US, DODGE_US, JEEP_EU, JEEP_US
)

DOMAIN: str = "fiat"

CONF_BRAND_REGION: str = "brand_region"

BRAND_FIAT_EUROPE: str = "Fiat_Europe"
BRAND_FIAT_USA: str = "Fiat_USA"
BRAND_RAM_USA: str = "Ram_USA"
BRAND_DODGE_USA: str = "Dodge_USA"
BRAND_JEEP_EUROPE: str = "Jeep_Europe"
BRAND_JEEP_USA: str = "Jeep_USA"

BRANDS = {1: BRAND_FIAT_EUROPE, 2: BRAND_FIAT_USA, 3: BRAND_RAM_USA,
          4: BRAND_DODGE_USA, 5: BRAND_JEEP_EUROPE, 6: BRAND_JEEP_USA}

BRANDS_API = {
    BRAND_FIAT_EUROPE: FIAT_EU,
    BRAND_FIAT_USA: FIAT_US,
    BRAND_DODGE_USA: DODGE_US,
    BRAND_JEEP_EUROPE: JEEP_EU,
    BRAND_JEEP_USA: JEEP_US,
    BRAND_RAM_USA: RAM_US,
}

DEFAULT_PIN: str = ""
DEFAULT_SCAN_INTERVAL: int = 5

UNIT_DYNAMIC: str = "dynamic"
