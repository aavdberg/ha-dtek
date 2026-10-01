"""Constants for the DTEK integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "dtek"
MANUFACTURER: Final = "DTEK"

# Configuration keys
CONF_DSO: Final = "dso"
CONF_CITY: Final = "city"
CONF_STREET: Final = "street"
CONF_HOUSE_NUMBER: Final = "house_number"
CONF_GROUP: Final = "group"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_PHONE: Final = "phone"
CONF_PASSWORD: Final = "password"
CONF_ACCOUNT: Final = "account"
CONF_EIC: Final = "eic"

# Cabinet constants
CABINET_BASE_URL: Final = "https://ok.dtek-dnem.com.ua"

# Defaults
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)
DEFAULT_DSO: Final = "dtek-dnem"
DEFAULT_GROUP: Final = "GPV1.1"
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 60

# Regional Distribution System Operators (DSOs)
SUPPORTED_DSOS: Final[dict[str, dict[str, str]]] = {
    "dtek-dnem": {
        "name": "Dnipro Grids (ДТЕК Дніпровські електромережі)",
        "base_url": "https://www.dtek-dnem.com.ua",
        "region": "Dnipropetrovsk",
    },
    "dtek-kem": {
        "name": "Kyiv Grids (ДТЕК Київські електромережі)",
        "base_url": "https://www.dtek-kem.com.ua",
        "region": "Kyiv City",
    },
    "dtek-krem": {
        "name": "Kyiv Regional Grids (ДТЕК Київські регіональні електромережі)",
        "base_url": "https://www.dtek-krem.com.ua",
        "region": "Kyiv Oblast",
    },
    "dtek-oem": {
        "name": "Odesa Grids (ДТЕК Одеські електромережі)",
        "base_url": "https://www.dtek-oem.com.ua",
        "region": "Odesa",
    },
}

# Outage types & status
OUTAGE_TYPE_NONE: Final = "none"
OUTAGE_TYPE_PLANNED: Final = "planned"
OUTAGE_TYPE_EMERGENCY: Final = "emergency"
OUTAGE_TYPE_SCHEDULE: Final = "stabilization_schedule"

# Platforms
PLATFORMS: Final = ["binary_sensor", "sensor", "calendar"]
