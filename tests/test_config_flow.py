"""Unit tests for DTEK config flow."""

from __future__ import annotations

from custom_components.dtek.config_flow import DtekConfigFlow


def test_config_flow_instantiation() -> None:
    """Test config flow can be imported and initialized."""
    flow = DtekConfigFlow()
    assert flow.VERSION == 1
    assert flow._dso == "dtek-dnem"
