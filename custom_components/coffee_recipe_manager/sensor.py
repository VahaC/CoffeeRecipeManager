"""Sensor platform for Coffee Recipe Manager."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CURRENT_STEP,
    ATTR_ERROR,
    ATTR_LAST_RECIPE,
    ATTR_RECIPE_NAME,
    ATTR_STATUS,
    ATTR_TOTAL_STEPS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    executor = hass.data[DOMAIN][entry.entry_id]["executor"]
    async_add_entities([CoffeeRecipeStatusSensor(entry, executor)])


class CoffeeRecipeStatusSensor(SensorEntity):
    """Sensor showing current recipe execution status."""

    _attr_has_entity_name = True
    _attr_name = "Recipe Status"
    _attr_icon = "mdi:coffee-maker"

    def __init__(self, entry: ConfigEntry, executor) -> None:
        self._entry = entry
        self._executor = executor
        self._attr_unique_id = f"{entry.entry_id}_recipe_status"
        # Register callback so executor can push updates
        executor.on_state_change = self._push_update

    def _push_update(self) -> None:
        """Called by executor when state changes."""
        self.schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        return self._executor.status

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_RECIPE_NAME: self._executor.current_recipe,
            ATTR_CURRENT_STEP: self._executor.current_step,
            ATTR_TOTAL_STEPS: self._executor.total_steps,
            ATTR_ERROR: self._executor.error,
            ATTR_LAST_RECIPE: self._executor.last_recipe,
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Coffee Recipe Manager",
            "manufacturer": "VahaC",
            "model": "Recipe Manager",
        }
