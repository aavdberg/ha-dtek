"""Tests for config entry setup helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.dtek import _async_persist_discovered_data


def test_persist_discovered_data_updates_stale_values() -> None:
    """Stale queue group and empty address fields are refreshed."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"group": "GPV1.1", "eic": "", "city": "", "account": "12345678"}

    _async_persist_discovered_data(
        hass,
        entry,
        {
            "group": "GPV1.2",
            "eic": "62Z1234567890123",
            "city": "с-ще Тестове",
            "account": "12345678",
        },
    )

    hass.config_entries.async_update_entry.assert_called_once()
    _, kwargs = hass.config_entries.async_update_entry.call_args
    assert kwargs["data"]["group"] == "GPV1.2"
    assert kwargs["data"]["eic"] == "62Z1234567890123"
    assert kwargs["data"]["city"] == "с-ще Тестове"


def test_persist_discovered_data_skips_when_unchanged() -> None:
    """No write happens when nothing new was discovered."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"group": "GPV1.2", "eic": "62Z1234567890123"}

    _async_persist_discovered_data(hass, entry, {"group": "GPV1.2", "eic": None, "city": None})

    hass.config_entries.async_update_entry.assert_not_called()
