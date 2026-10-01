"""Endpoints and AJAX method names for DTEK portals."""

from __future__ import annotations

from typing import Final

AJAX_PATH: Final = "/ua/ajax"
SHUTDOWNS_PATH: Final = "/ua/shutdowns"

# AJAX methods
METHOD_GET_HOME_NUM: Final = "getHomeNum"
METHOD_GET_STREETS: Final = "getStreets"
METHOD_GET_SCHEDULE: Final = "getSchedule"
METHOD_GET_FACT: Final = "getFact"
METHOD_GET_PLAN: Final = "getPlan"
METHOD_GET_CURRENT_SCHEDULE: Final = "getCurrentSchedule"

# Cabinet REST API paths
PATH_CABINET_AUTH_PERSON: Final = "/api/auth/person"
PATH_CABINET_POWERTRACK: Final = "/api/post-powertrack-api"
PATH_CABINET_OBJECTS_INFO: Final = "/api/person/objects/info"
PATH_CABINET_BALANCE: Final = "/api/person/itm_balance"
PATH_CABINET_CHOICE_APART: Final = "/api/choice-apart"
PATH_CABINET_CHOICE_ACCOUNT: Final = "/api/entity/choice-account"
