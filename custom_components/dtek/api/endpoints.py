"""Endpoints and AJAX method names for DTEK portals."""

from __future__ import annotations

from typing import Final

AJAX_PATH: Final = "/ua/ajax"
SHUTDOWNS_PATH: Final = "/ua/shutdowns"

# AJAX methods
METHOD_GET_HOME_NUM: Final = "getHomeNum"
METHOD_GET_SCHEDULE: Final = "getSchedule"
METHOD_GET_FACT: Final = "getFact"
METHOD_GET_PLAN: Final = "getPlan"
METHOD_GET_CURRENT_SCHEDULE: Final = "getCurrentSchedule"
