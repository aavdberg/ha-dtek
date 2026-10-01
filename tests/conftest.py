"""Pytest fixtures and lightweight stubs for Home Assistant modules."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def _install_homeassistant_stubs() -> None:
    """Install minimal stubs for homeassistant modules."""
    ha = _ensure_module("homeassistant")
    ha.__path__ = []

    core = _ensure_module("homeassistant.core")

    class HomeAssistant:
        """Stand-in for HomeAssistant core."""

        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.config_entries = None

    def callback(func: Any) -> Any:
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    config_entries = _ensure_module("homeassistant.config_entries")

    class ConfigEntry:
        def __init__(
            self,
            version: int = 1,
            domain: str = "dtek",
            title: str = "DTEK",
            data: dict[str, Any] | None = None,
            options: dict[str, Any] | None = None,
            entry_id: str = "test_entry_id",
        ) -> None:
            self.version = version
            self.domain = domain
            self.title = title
            self.data = data or {}
            self.options = options or {}
            self.entry_id = entry_id
            self.runtime_data = None

        def add_update_listener(self, listener: Any) -> Any:
            return lambda: None

        def async_on_unload(self, callback_func: Any) -> None:
            pass

    class ConfigFlow:
        def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            cls._domain = domain

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def async_show_form(
            self, step_id: str, data_schema: Any = None, errors: dict[str, str] | None = None
        ) -> dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

        def async_create_entry(self, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    class OptionsFlow:
        def __init__(self, config_entry: Any = None) -> None:
            self.config_entry = config_entry

        def async_show_form(self, step_id: str, data_schema: Any = None) -> dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema}

        def async_create_entry(self, title: str, data: dict[str, Any]) -> dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.OptionsFlow = OptionsFlow

    helpers = _ensure_module("homeassistant.helpers")
    helpers.__path__ = []

    aiohttp_client = _ensure_module("homeassistant.helpers.aiohttp_client")

    def async_get_clientsession(hass: Any) -> Any:
        return getattr(hass, "session", None)

    aiohttp_client.async_get_clientsession = async_get_clientsession

    update_coordinator = _ensure_module("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, key: Any) -> Any:
            return cls

        def __init__(self, hass: Any, logger: Any, name: str, update_interval: Any = None) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None

        async def async_config_entry_first_refresh(self) -> None:
            pass

    class CoordinatorEntity:
        def __class_getitem__(cls, key: Any) -> Any:
            return cls

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity

    entity_platform = _ensure_module("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = Any

    components = _ensure_module("homeassistant.components")
    components.__path__ = []

    from dataclasses import dataclass

    # binary_sensor
    binary_sensor = _ensure_module("homeassistant.components.binary_sensor")

    class BinarySensorDeviceClass:
        POWER = "power"

    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription:
        key: str
        translation_key: str = ""
        device_class: str = ""
        icon: str = ""

    class BinarySensorEntity:
        @property
        def unique_id(self) -> str | None:
            return getattr(self, "_attr_unique_id", None)

    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    binary_sensor.BinarySensorEntityDescription = BinarySensorEntityDescription
    binary_sensor.BinarySensorEntity = BinarySensorEntity

    # sensor
    sensor = _ensure_module("homeassistant.components.sensor")

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        translation_key: str = ""
        device_class: str = ""
        icon: str = ""
        native_unit_of_measurement: str | None = None

    class SensorEntity:
        pass

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorEntity = SensorEntity

    # calendar
    calendar = _ensure_module("homeassistant.components.calendar")

    class CalendarEvent:
        def __init__(self, start: Any, end: Any, summary: str, description: str = "") -> None:
            self.start = start
            self.end = end
            self.summary = summary
            self.description = description

    class CalendarEntity:
        pass

    calendar.CalendarEvent = CalendarEvent
    calendar.CalendarEntity = CalendarEntity


_install_homeassistant_stubs()


@pytest.fixture
def mock_html_with_csrf() -> str:
    """Return mock HTML containing a DTEK CSRF token meta tag."""
    return """<!DOCTYPE html>
<html>
<head>
    <meta name="csrf-token" content="test_dtek_csrf_token_1234567890">
    <title>Графіки відключень | ДТЕК</title>
</head>
<body>
    <div id="app"></div>
</body>
</html>"""


@pytest.fixture
def mock_home_num_response() -> dict[str, Any]:
    """Return mock response for getHomeNum matching DTEK street investigation."""
    return {
        "result": True,
        "showCurOutageParam": True,
        "showCurSchedule": True,
        "showTableSchedule": True,
        "showTablePlan": False,
        "showTableFact": True,
        "showUserGroup": True,
        "1": {
            "sub_type": "",
            "start_date": "",
            "end_date": "",
            "type": "",
            "sub_type_reason": ["GPV1.2"],
        },
        "2": {
            "sub_type": "",
            "start_date": "",
            "end_date": "",
            "type": "",
            "sub_type_reason": ["GPV1.1"],
        },
    }
