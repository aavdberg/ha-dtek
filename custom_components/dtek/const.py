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
CABINET_DEFAULT_SITE: Final = "dnem"

# Defaults
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)
DEFAULT_DSO: Final = "dtek-dnem"
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 60

# Regional Distribution System Operators (DSOs)
SUPPORTED_DSOS: Final[dict[str, dict[str, str]]] = {
    "dtek-dnem": {
        "name": "Dnipro Grids (ДТЕК Дніпровські електромережі)",
        "base_url": "https://www.dtek-dnem.com.ua",
        "cabinet_base_url": "https://ok.dtek-dnem.com.ua",
        "cabinet_site": "dnem",
        "region": "Dnipropetrovsk",
    },
    "dtek-kem": {
        "name": "Kyiv Grids (ДТЕК Київські електромережі)",
        "base_url": "https://www.dtek-kem.com.ua",
        "cabinet_base_url": "https://ok.dtek-kem.com.ua",
        "cabinet_site": "kem",
        "region": "Kyiv City",
    },
    "dtek-krem": {
        "name": "Kyiv Regional Grids (ДТЕК Київські регіональні електромережі)",
        "base_url": "https://www.dtek-krem.com.ua",
        "cabinet_base_url": "https://ok.dtek-krem.com.ua",
        "cabinet_site": "krem",
        "region": "Kyiv Oblast",
    },
    "dtek-oem": {
        "name": "Odesa Grids (ДТЕК Одеські електромережі)",
        "base_url": "https://www.dtek-oem.com.ua",
        "cabinet_base_url": "https://ok.dtek-oem.com.ua",
        "cabinet_site": "oem",
        "region": "Odesa",
    },
}


def cabinet_site_for_dso(dso: str) -> str:
    """Return the Personal Cabinet site identifier for a DSO."""
    return SUPPORTED_DSOS.get(dso, {}).get("cabinet_site", CABINET_DEFAULT_SITE)


def cabinet_base_url_for_dso(dso: str) -> str:
    """Return the Personal Cabinet base URL for a DSO."""
    return SUPPORTED_DSOS.get(dso, {}).get("cabinet_base_url", CABINET_BASE_URL)


# Outage types & status
OUTAGE_TYPE_NONE: Final = "none"
OUTAGE_TYPE_PLANNED: Final = "planned"
OUTAGE_TYPE_EMERGENCY: Final = "emergency"
OUTAGE_TYPE_SCHEDULE: Final = "stabilization_schedule"

# Platforms
PLATFORMS: Final = ["binary_sensor", "sensor", "calendar"]
