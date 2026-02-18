"""Config flow for Coffee Recipe Manager."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FAULT_SENSORS,
    CONF_MACHINE_DOUBLE_SWITCH,
    CONF_MACHINE_DRINK_SELECT,
    CONF_MACHINE_START_SWITCH,
    CONF_MACHINE_WORK_STATE,
    CONF_NOTIFY_SERVICE,
    CONF_RECIPES_FILE,
    DEFAULT_DOUBLE_SWITCH,
    DEFAULT_DRINK_SELECT,
    DEFAULT_FAULT_SENSORS,
    DEFAULT_RECIPES_FILE,
    DEFAULT_START_SWITCH,
    DEFAULT_WORK_STATE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CoffeeRecipeManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Coffee Recipe Manager."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: Machine entities."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate that entities exist
            for key in [
                CONF_MACHINE_DRINK_SELECT,
                CONF_MACHINE_START_SWITCH,
                CONF_MACHINE_WORK_STATE,
            ]:
                entity_id = user_input.get(key, "")
                if not self.hass.states.get(entity_id):
                    errors[key] = "entity_not_found"

            if not errors:
                self._data = user_input
                return await self.async_step_faults()

        schema = vol.Schema({
            vol.Required(
                CONF_MACHINE_DRINK_SELECT,
                default=DEFAULT_DRINK_SELECT,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="select")
            ),
            vol.Required(
                CONF_MACHINE_START_SWITCH,
                default=DEFAULT_START_SWITCH,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Required(
                CONF_MACHINE_WORK_STATE,
                default=DEFAULT_WORK_STATE,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_select"])
            ),
            vol.Optional(
                CONF_MACHINE_DOUBLE_SWITCH,
                default=DEFAULT_DOUBLE_SWITCH,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "docs_url": "https://github.com/vahac/coffee-recipe-manager"
            },
        )

    async def async_step_faults(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Fault sensors."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_notify()

        schema = vol.Schema({
            vol.Optional(
                CONF_FAULT_SENSORS,
                default=DEFAULT_FAULT_SENSORS,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="faults",
            data_schema=schema,
        )

    async def async_step_notify(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 3: Notification service + recipes file."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Coffee Recipe Manager",
                data=self._data,
            )

        schema = vol.Schema({
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                default="none",
            ): str,
            vol.Optional(
                CONF_RECIPES_FILE,
                default=DEFAULT_RECIPES_FILE,
            ): str,
        })

        return self.async_show_form(
            step_id="notify",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return options flow."""
        return CoffeeRecipeManagerOptionsFlow(config_entry)


_DEFAULT_STEPS_EXAMPLE = [
    {"drink": "Espresso", "double": False, "timeout": 300},
]


class CoffeeRecipeManagerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Coffee Recipe Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._edit_key: str | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_storage(self):
        return self.hass.data[DOMAIN][self._config_entry.entry_id]["storage"]

    def _recipe_options(self) -> list[selector.SelectOptionDict]:
        storage = self._get_storage()
        return [
            selector.SelectOptionDict(value=key, label=f"{data['name']} ({key})")
            for key, data in storage.recipes.items()
        ]

    # ------------------------------------------------------------------
    # Root menu
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Root menu: machine settings or recipe management."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["machine_settings", "recipes_menu"],
        )

    # ------------------------------------------------------------------
    # Machine settings
    # ------------------------------------------------------------------

    async def async_step_machine_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Options: update machine settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}

        schema = vol.Schema({
            vol.Required(
                CONF_MACHINE_DRINK_SELECT,
                default=current.get(CONF_MACHINE_DRINK_SELECT, DEFAULT_DRINK_SELECT),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="select")
            ),
            vol.Required(
                CONF_MACHINE_START_SWITCH,
                default=current.get(CONF_MACHINE_START_SWITCH, DEFAULT_START_SWITCH),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Required(
                CONF_MACHINE_WORK_STATE,
                default=current.get(CONF_MACHINE_WORK_STATE, DEFAULT_WORK_STATE),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_select"])
            ),
            vol.Optional(
                CONF_MACHINE_DOUBLE_SWITCH,
                default=current.get(CONF_MACHINE_DOUBLE_SWITCH, DEFAULT_DOUBLE_SWITCH),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(
                CONF_FAULT_SENSORS,
                default=current.get(CONF_FAULT_SENSORS, DEFAULT_FAULT_SENSORS),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                default=current.get(CONF_NOTIFY_SERVICE, "none"),
            ): str,
        })

        return self.async_show_form(step_id="machine_settings", data_schema=schema)

    # ------------------------------------------------------------------
    # Recipe management menu
    # ------------------------------------------------------------------

    async def async_step_recipes_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Recipe sub-menu: add / edit / delete."""
        return self.async_show_menu(
            step_id="recipes_menu",
            menu_options=["recipe_add", "recipe_edit_select", "recipe_delete_select"],
        )

    # ------------------------------------------------------------------
    # Add recipe
    # ------------------------------------------------------------------

    async def async_step_recipe_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Form: add a new recipe."""
        errors: dict[str, str] = {}

        if user_input is not None:
            storage = self._get_storage()
            name = user_input["name"].strip()
            key = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
            steps = user_input.get("steps", _DEFAULT_STEPS_EXAMPLE)

            if not isinstance(steps, list) or not steps:
                errors["steps"] = "steps_invalid"
            else:
                recipe = {
                    "name": name,
                    "description": user_input.get("description", ""),
                    "steps": steps,
                }
                success = await storage.save_recipe(key, recipe)
                if success:
                    return self.async_create_entry(title="", data={})
                errors["base"] = "recipe_save_failed"

        schema = vol.Schema({
            vol.Required("name"): selector.TextSelector(),
            vol.Optional("description", default=""): selector.TextSelector(),
            vol.Required("steps", default=_DEFAULT_STEPS_EXAMPLE): selector.ObjectSelector(),
        })

        return self.async_show_form(
            step_id="recipe_add",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Edit recipe
    # ------------------------------------------------------------------

    async def async_step_recipe_edit_select(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select which recipe to edit."""
        options = self._recipe_options()
        if not options:
            return self.async_abort(reason="no_recipes")

        if user_input is not None:
            self._edit_key = user_input["recipe_key"]
            return await self.async_step_recipe_edit()

        schema = vol.Schema({
            vol.Required("recipe_key"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options)
            ),
        })

        return self.async_show_form(step_id="recipe_edit_select", data_schema=schema)

    async def async_step_recipe_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Form: edit the selected recipe."""
        storage = self._get_storage()
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"].strip()
            steps = user_input.get("steps", [])

            if not isinstance(steps, list) or not steps:
                errors["steps"] = "steps_invalid"
            else:
                recipe = {
                    "name": name,
                    "description": user_input.get("description", ""),
                    "steps": steps,
                }
                success = await storage.save_recipe(self._edit_key, recipe)
                if success:
                    return self.async_create_entry(title="", data={})
                errors["base"] = "recipe_save_failed"

        existing = storage.get_recipe(self._edit_key) or {}
        schema = vol.Schema({
            vol.Required("name", default=existing.get("name", "")): selector.TextSelector(),
            vol.Optional("description", default=existing.get("description", "")): selector.TextSelector(),
            vol.Required("steps", default=existing.get("steps", _DEFAULT_STEPS_EXAMPLE)): selector.ObjectSelector(),
        })

        return self.async_show_form(
            step_id="recipe_edit",
            data_schema=schema,
            errors=errors,
            description_placeholders={"recipe_key": self._edit_key},
        )

    # ------------------------------------------------------------------
    # Delete recipe
    # ------------------------------------------------------------------

    async def async_step_recipe_delete_select(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Select and delete a recipe."""
        options = self._recipe_options()
        if not options:
            return self.async_abort(reason="no_recipes")

        if user_input is not None:
            storage = self._get_storage()
            await storage.delete_recipe(user_input["recipe_key"])
            return self.async_create_entry(title="", data={})

        schema = vol.Schema({
            vol.Required("recipe_key"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options)
            ),
        })

        return self.async_show_form(
            step_id="recipe_delete_select",
            data_schema=schema,
            description_placeholders={},
        )
