"""Coffee Recipe Manager integration."""
from __future__ import annotations

import logging
import os
import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_FAULT_SENSORS,
    CONF_MACHINE_DOUBLE_SWITCH,
    CONF_MACHINE_DRINK_SELECT,
    CONF_MACHINE_START_SWITCH,
    CONF_MACHINE_WORK_STATE,
    CONF_NOTIFY_SERVICE,
    CONF_RECIPES_FILE,
    DEFAULT_FAULT_SENSORS,
    DEFAULT_RECIPES_FILE,
    DEFAULT_STANDBY_STATE,
    DOMAIN,
    SERVICE_ABORT_RECIPE,
    SERVICE_BREW_RECIPE,
)
from .executor import RecipeExecutor
from .storage import RecipeStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "select", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Coffee Recipe Manager from config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = {**entry.data, **entry.options}

    # Build recipes file path
    recipes_filename = config.get(CONF_RECIPES_FILE, DEFAULT_RECIPES_FILE)
    recipes_path = hass.config.path(recipes_filename)

    # Init storage
    storage = RecipeStorage(hass, recipes_path)
    await storage.load()

    # Init executor
    executor = RecipeExecutor(
        hass=hass,
        config={
            "machine_drink_select": config[CONF_MACHINE_DRINK_SELECT],
            "machine_start_switch": config[CONF_MACHINE_START_SWITCH],
            "machine_work_state": config[CONF_MACHINE_WORK_STATE],
            "machine_double_switch": config.get(CONF_MACHINE_DOUBLE_SWITCH),
            "fault_sensors": config.get(CONF_FAULT_SENSORS, DEFAULT_FAULT_SENSORS),
            "notify_service": config.get(CONF_NOTIFY_SERVICE, "none"),
            "standby_state": DEFAULT_STANDBY_STATE,
        },
    )

    hass.data[DOMAIN][entry.entry_id] = {
        "executor": executor,
        "storage": storage,
        "config": config,
    }

    # Refresh select entity whenever recipes change (UI flow saves go through storage directly)
    def _on_recipes_changed():
        _refresh_select(hass, entry.entry_id)

    storage.on_recipes_changed = _on_recipes_changed

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_BREW_RECIPE):
        _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, {})
        executor: RecipeExecutor = data.get("executor")
        if executor:
            await executor.abort()

    # Remove services if no more entries
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_BREW_RECIPE)
        hass.services.async_remove(DOMAIN, SERVICE_ABORT_RECIPE)
        for svc in ("reload_recipes", "add_recipe", "delete_recipe", "list_recipes", "get_recipe"):
            hass.services.async_remove(DOMAIN, svc)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register all integration services."""

    async def handle_brew_recipe(call: ServiceCall) -> None:
        """Service: brew_recipe."""
        recipe_name = call.data["recipe_name"]
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            _LOGGER.error("No Coffee Recipe Manager entry found")
            return

        data = hass.data[DOMAIN][entry_id]
        storage: RecipeStorage = data["storage"]
        executor: RecipeExecutor = data["executor"]

        recipe = storage.get_recipe(recipe_name)
        if not recipe:
            _LOGGER.error("Recipe not found: '%s'. Available: %s", recipe_name, storage.get_recipe_names())
            await hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "Coffee Recipe Manager",
                    "message": f"Recipe not found: '{recipe_name}'\nAvailable: {', '.join(storage.get_recipe_names())}",
                    "notification_id": f"{DOMAIN}_notification",
                },
            )
            return

        await executor.brew(recipe["name"], recipe["steps"])

    async def handle_abort_recipe(call: ServiceCall) -> None:
        """Service: abort_recipe."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        executor: RecipeExecutor = hass.data[DOMAIN][entry_id]["executor"]
        await executor.abort()

    async def handle_reload_recipes(call: ServiceCall) -> None:
        """Service: reload_recipes."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        data = hass.data[DOMAIN][entry_id]
        storage: RecipeStorage = data["storage"]
        await storage.load()
        _refresh_select(hass, entry_id)
        _LOGGER.info("Recipes reloaded")

    async def handle_add_recipe(call: ServiceCall) -> None:
        """Service: add_recipe - add/update recipe via service call."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        storage: RecipeStorage = hass.data[DOMAIN][entry_id]["storage"]

        recipe_name = call.data["name"]
        # Generate key from name
        key = re.sub(r"[^a-z0-9_]", "_", recipe_name.lower()).strip("_")

        recipe = {
            "name": recipe_name,
            "description": call.data.get("description", ""),
            "steps": call.data["steps"],
        }
        success = await storage.save_recipe(key, recipe)
        if success:
            _refresh_select(hass, entry_id)
            _LOGGER.info("Recipe '%s' saved as '%s'", recipe_name, key)
        else:
            _LOGGER.error("Failed to save recipe '%s'", recipe_name)

    async def handle_delete_recipe(call: ServiceCall) -> None:
        """Service: delete_recipe."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        storage: RecipeStorage = hass.data[DOMAIN][entry_id]["storage"]
        await storage.delete_recipe(call.data["recipe_name"])
        _refresh_select(hass, entry_id)

    async def handle_list_recipes(call: ServiceCall) -> None:
        """Service: list_recipes — show all recipes in a persistent notification."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        storage: RecipeStorage = hass.data[DOMAIN][entry_id]["storage"]
        recipes = storage.recipes
        if not recipes:
            msg = "No recipes found."
        else:
            lines = []
            for key, data in recipes.items():
                steps_summary = ", ".join(
                    f"{s['drink']}{'×2' if s.get('double') else ''}"
                    for s in data.get("steps", [])
                )
                lines.append(f"**{data['name']}** (`{key}`)  \n{steps_summary}")
            msg = "\n\n".join(lines)
        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Coffee Recipes",
                "message": msg,
                "notification_id": f"{DOMAIN}_list",
            },
        )

    async def handle_get_recipe(call: ServiceCall) -> None:
        """Service: get_recipe — show a single recipe's full details."""
        entry_id = _get_first_entry_id(hass)
        if not entry_id:
            return
        storage: RecipeStorage = hass.data[DOMAIN][entry_id]["storage"]
        key = call.data["recipe_name"]
        recipe = storage.get_recipe(key)
        if not recipe:
            msg = f"Recipe `{key}` not found.\n\nAvailable keys: {', '.join(f'`{k}`' for k in storage.recipes)}"
        else:
            import yaml as _yaml
            steps_yaml = _yaml.dump(recipe.get("steps", []), allow_unicode=True, default_flow_style=False)
            msg = (
                f"**{recipe['name']}** (`{key}`)\n"
                f"{recipe.get('description', '')}\n\n"
                f"```yaml\n{steps_yaml}```"
            )
        await hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Coffee Recipe Detail",
                "message": msg,
                "notification_id": f"{DOMAIN}_detail_{key}",
            },
        )


    hass.services.async_register(
        DOMAIN,
        SERVICE_BREW_RECIPE,
        handle_brew_recipe,
        schema=vol.Schema({vol.Required("recipe_name"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ABORT_RECIPE,
        handle_abort_recipe,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "reload_recipes",
        handle_reload_recipes,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "add_recipe",
        handle_add_recipe,
        schema=vol.Schema({
            vol.Required("name"): cv.string,
            vol.Optional("description", default=""): cv.string,
            vol.Required("steps"): vol.All(
                list,
                [{
                    vol.Required("drink"): cv.string,
                    vol.Optional("double", default=False): cv.boolean,
                    vol.Optional("timeout", default=300): vol.All(int, vol.Range(min=10, max=3600)),
                }]
            ),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        "delete_recipe",
        handle_delete_recipe,
        schema=vol.Schema({vol.Required("recipe_name"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        "list_recipes",
        handle_list_recipes,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "get_recipe",
        handle_get_recipe,
        schema=vol.Schema({vol.Required("recipe_name"): cv.string}),
    )


def _get_first_entry_id(hass: HomeAssistant) -> str | None:
    entries = list(hass.data.get(DOMAIN, {}).keys())
    return entries[0] if entries else None


def _refresh_select(hass: HomeAssistant, entry_id: str) -> None:
    """Tell the recipe select entity to refresh its options."""
    select_entity = hass.data.get(DOMAIN, {}).get(entry_id, {}).get("recipe_select")
    if select_entity is not None:
        select_entity.reload_options()
