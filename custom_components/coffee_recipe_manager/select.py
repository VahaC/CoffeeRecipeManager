"""Select platform for Coffee Recipe Manager — recipe picker."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .storage import RecipeStorage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    storage: RecipeStorage = hass.data[DOMAIN][entry.entry_id]["storage"]
    entity = CoffeeRecipeSelect(entry, storage)
    async_add_entities([entity])
    # Store reference so button + storage can notify it
    hass.data[DOMAIN][entry.entry_id]["recipe_select"] = entity


class CoffeeRecipeSelect(SelectEntity):
    """Dropdown to pick which recipe to brew."""

    _attr_has_entity_name = True
    _attr_name = "Select Recipe"
    _attr_icon = "mdi:coffee-outline"

    def __init__(self, entry: ConfigEntry, storage: RecipeStorage) -> None:
        self._entry = entry
        self._storage = storage
        self._attr_unique_id = f"{entry.entry_id}_recipe_select"
        self._current_option: str | None = None

    # ------------------------------------------------------------------

    def reload_options(self) -> None:
        """Re-read recipe list from storage and refresh entity."""
        self.schedule_update_ha_state()

    @property
    def options(self) -> list[str]:
        names = [r["name"] for r in self._storage.recipes.values()]
        if not names:
            return ["— no recipes —"]
        return names

    @property
    def current_option(self) -> str | None:
        names = self.options
        if self._current_option in names:
            return self._current_option
        return names[0] if names else None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()

    def get_selected_key(self) -> str | None:
        """Return the recipe key matching the currently selected name."""
        target = self.current_option
        for key, data in self._storage.recipes.items():
            if data["name"] == target:
                return key
        return None

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Coffee Recipe Manager",
            "manufacturer": "VahaC",
            "model": "Recipe Manager",
        }
