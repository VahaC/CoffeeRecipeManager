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


def _format_step(i: int, step: dict, hass=None) -> str:
    """Return a human-readable line for one recipe step."""
    parts: list[str] = []

    # Drink
    drink = step.get("drink")
    if drink and drink.lower() != "none":
        double = " (double)" if step.get("double") else ""
        parts.append(f"☕ {drink}{double}")

    def _switch_name(entity_id: str) -> str:
        if hass:
            state = hass.states.get(entity_id)
            if state and state.name:
                return state.name
        return entity_id.split(".")[-1].replace("_", " ").title()

    # switch_counts (v0.3.3+ format)
    switch_counts: dict = step.get("switch_counts") or {}
    if switch_counts:
        for entity_id, count in switch_counts.items():
            count = int(count) if count else 0
            if count <= 0:
                continue
            times = f"×{count}"
            parts.append(f"⇄ {_switch_name(entity_id)} {times}")
    # Legacy: switches list
    elif step.get("switches"):
        raw = step["switches"]
        entities = [raw] if isinstance(raw, str) else list(raw)
        for entity_id in entities:
            parts.append(f"⇄ {_switch_name(entity_id)}")
    # Legacy: single switch
    elif step.get("switch"):
        parts.append(f"⇄ {_switch_name(step['switch'])}")

    timeout = step.get("timeout", 300)
    content = ", ".join(parts) if parts else "(empty step)"
    return f"{i}. {content} — {timeout}s"


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
        CoffeeEditRecipeButton(entry, hass),
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
        lines = [_format_step(i, step, self._hass) for i, step in enumerate(steps, 1)]

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

class CoffeeEditRecipeButton(ButtonEntity):
    """Button that sends a persistent notification with a link to the recipe editor."""

    _attr_has_entity_name = True
    _attr_name = "Edit Recipes"
    _attr_icon = "mdi:pencil-box"

    def __init__(self, entry: ConfigEntry, hass: HomeAssistant) -> None:
        self._entry = entry
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_edit_recipe_button"

    async def async_press(self) -> None:
        """Create a notification with a deep-link to the integration's config page."""
        path = f"/config/integrations/integration/{DOMAIN}"
        await self._hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Coffee Recipe Manager",
                "message": (
                    "Tap the link below to open the recipe editor:\n\n"
                    f"[✏️ Open Recipe Editor]({path})"
                ),
                "notification_id": f"{DOMAIN}_edit_shortcut",
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
