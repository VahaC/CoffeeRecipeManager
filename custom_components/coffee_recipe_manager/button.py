"""Button platform for Coffee Recipe Manager — brew & abort."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .executor import RecipeExecutor
from .storage import RecipeStorage

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    executor: RecipeExecutor = hass.data[DOMAIN][entry.entry_id]["executor"]
    storage: RecipeStorage = hass.data[DOMAIN][entry.entry_id]["storage"]
    async_add_entities([
        CoffeeBrewButton(entry, hass, executor, storage),
        CoffeeAbortButton(entry, executor),
        CoffeeViewRecipeButton(entry, hass, storage),
    ])


# ---------------------------------------------------------------------------

class CoffeeBrewButton(ButtonEntity):
    """Button that starts the recipe chosen in the Select entity."""

    _attr_has_entity_name = True
    _attr_name = "Brew Selected Recipe"
    _attr_icon = "mdi:play-circle"

    def __init__(
        self,
        entry: ConfigEntry,
        hass: HomeAssistant,
        executor: RecipeExecutor,
        storage: RecipeStorage,
    ) -> None:
        self._entry = entry
        self._hass = hass
        self._executor = executor
        self._storage = storage
        self._attr_unique_id = f"{entry.entry_id}_brew_button"

    async def async_press(self) -> None:
        """Start the selected recipe."""
        select_entity = self._hass.data[DOMAIN][self._entry.entry_id].get("recipe_select")
        if select_entity is None:
            _LOGGER.error("Recipe select entity not found")
            return

        key = select_entity.get_selected_key()
        if not key:
            _LOGGER.warning("No recipe selected")
            return

        recipe = self._storage.get_recipe(key)
        if not recipe:
            _LOGGER.error("Recipe key '%s' not found in storage", key)
            return

        _LOGGER.info("Brew button pressed: starting recipe '%s'", key)
        await self._executor.brew(recipe["name"], recipe["steps"])

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Coffee Recipe Manager",
            "manufacturer": "VahaC",
            "model": "Recipe Manager",
        }


class CoffeeViewRecipeButton(ButtonEntity):
    """Button that shows the selected recipe's details in a notification."""

    _attr_has_entity_name = True
    _attr_name = "View Selected Recipe"
    _attr_icon = "mdi:text-box-search-outline"

    def __init__(
        self,
        entry: ConfigEntry,
        hass: HomeAssistant,
        storage: RecipeStorage,
    ) -> None:
        self._entry = entry
        self._hass = hass
        self._storage = storage
        self._attr_unique_id = f"{entry.entry_id}_view_recipe_button"

    async def async_press(self) -> None:
        """Show selected recipe details as a persistent notification."""
        select_entity = self._hass.data[DOMAIN][self._entry.entry_id].get("recipe_select")
        key = select_entity.get_selected_key() if select_entity else None

        if not key:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": "Coffee Recipe Manager", "message": "No recipe selected.",
                 "notification_id": f"{DOMAIN}_view"},
            )
            return

        recipe = self._storage.get_recipe(key)
        if not recipe:
            await self._hass.services.async_call(
                "persistent_notification", "create",
                {"title": "Coffee Recipe Manager", "message": f"Recipe `{key}` not found.",
                 "notification_id": f"{DOMAIN}_view"},
            )
            return

        steps = recipe.get("steps", [])
        lines = []
        for i, step in enumerate(steps, 1):
            double = " (double)" if step.get("double") else ""
            timeout = step.get("timeout", 300)
            lines.append(f"{i}. **{step['drink']}**{double} — timeout: {timeout}s")

        description = recipe.get("description", "")
        msg = f"### {recipe['name']}\n"
        if description:
            msg += f"*{description}*\n\n"
        msg += "\n".join(lines)

        await self._hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": f"Recipe: {recipe['name']}",
                "message": msg,
                "notification_id": f"{DOMAIN}_view",
            },
        )

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Coffee Recipe Manager",
            "manufacturer": "VahaC",
            "model": "Recipe Manager",
        }


# ---------------------------------------------------------------------------

class CoffeeAbortButton(ButtonEntity):
    """Button that aborts the currently running recipe."""

    _attr_has_entity_name = True
    _attr_name = "Abort Recipe"
    _attr_icon = "mdi:stop-circle"

    def __init__(self, entry: ConfigEntry, executor: RecipeExecutor) -> None:
        self._entry = entry
        self._executor = executor
        self._attr_unique_id = f"{entry.entry_id}_abort_button"

    async def async_press(self) -> None:
        """Abort current recipe."""
        _LOGGER.info("Abort button pressed")
        await self._executor.abort()

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Coffee Recipe Manager",
            "manufacturer": "VahaC",
            "model": "Recipe Manager",
        }
