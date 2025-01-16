"""Constants for the Fiat integration"""

DOMAIN: str = "fiat"

CONF_BRAND: str = "brand"
CONF_DEEP_REFRESH_INTERVAL: str = "deep_refresh"

BRAND_FIAT_EUROPE: str = "Fiat_Europe"
BRAND_FIAT_USA: str = "Fiat_USA"
BRAND_RAM_USA: str = "Ram_USA"
BRAND_DODGE_USA: str = "Dodge_USA"
BRAND_JEEP_EUROPE: str = "Jeep_Europe"
BRAND_JEEP_USA: str = "Jeep_USA"

BRANDS = {1: BRAND_FIAT_EUROPE, 2: BRAND_FIAT_USA, 3: BRAND_RAM_USA,
          4: BRAND_DODGE_USA, 5: BRAND_JEEP_EUROPE, 6: BRAND_JEEP_USA}

DEFAULT_PIN: str = ""
DEFAULT_SCAN_INTERVAL: int = 30
DEFAULT_DEEP_REFRESH_INTERVAL: int = 600
