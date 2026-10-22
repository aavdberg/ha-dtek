"""Button platform for the DTEK integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER
from .coordinator import DtekDataUpdateCoordinator
from .models import DtekConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DtekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DTEK refresh button."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            DtekRefreshButton(
                runtime.coordinator,
                entry.entry_id,
                runtime.account,
                runtime.group,
            )
        ]
    )


class DtekRefreshButton(ButtonEntity):
    """Request an immediate update of the DTEK coordinator."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"
    _attr_translation_key = "refresh_data"

    def __init__(
        self,
        coordinator: DtekDataUpdateCoordinator,
        entry_id: str,
        account: str | None,
        group: str,
    ) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_refresh_data"
        device_name = f"DTEK Account {account}" if account else f"DTEK Grid ({group})"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": f"Queue {group}",
        }

    async def async_press(self) -> None:
        """Request a coordinator refresh immediately."""
        await self.coordinator.async_request_refresh()
