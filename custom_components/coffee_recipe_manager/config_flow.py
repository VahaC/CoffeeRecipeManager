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
    CONF_DRINK_OPTIONS,
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
    DRINK_OPTIONS,
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
                return await self.async_step_drinks()

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

    async def async_step_drinks(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Available drinks."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_faults()

        available = _get_machine_drink_options(self.hass, self._data.get(CONF_MACHINE_DRINK_SELECT))
        options = [selector.SelectOptionDict(value=d, label=d) for d in available]
        schema = vol.Schema({
            vol.Required(
                CONF_DRINK_OPTIONS,
                default=available,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(step_id="drinks", data_schema=schema)

    async def async_step_faults(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 3: Fault sensors."""
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
        """Step 4: Notification service + recipes file."""
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


def _get_machine_drink_options(hass, entity_id: str | None) -> list[str]:
    """Return drink options from the machine's select entity, falling back to DRINK_OPTIONS."""
    if entity_id:
        state = hass.states.get(entity_id)
        if state:
            opts = state.attributes.get("options", [])
            if opts:
                return list(opts)
    return list(DRINK_OPTIONS)


class CoffeeRecipeManagerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Coffee Recipe Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._edit_key: str | None = None
        # Recipe builder state
        self._recipe_name: str = ""
        self._recipe_description: str = ""
        self._recipe_steps: list[dict] = []
        self._step_prefill: list[dict] = []  # existing steps when editing
        self._step_index: int = 0

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

    async def _save_current_recipe(self) -> config_entries.FlowResult:
        """Validate drinks then save the accumulated recipe."""
        from .storage import RecipeStorage
        storage = self._get_storage()
        key = self._edit_key or re.sub(
            r"[^a-z0-9_]", "_", self._recipe_name.lower()
        ).strip("_")
        recipe = {
            "name": self._recipe_name,
            "description": self._recipe_description,
            "steps": self._recipe_steps,
        }

        # Validate drinks against configured list
        current_config = {**self._config_entry.data, **self._config_entry.options}
        allowed = current_config.get(CONF_DRINK_OPTIONS)
        if allowed:
            invalid = RecipeStorage.validate_drinks(recipe, allowed)
            if invalid:
                return self.async_abort(reason="invalid_drink_in_recipe")

        success = await storage.save_recipe(key, recipe)
        if success:
            return self.async_create_entry(title="", data={})
        return self.async_abort(reason="recipe_save_failed")

    # ------------------------------------------------------------------
    # Root menu
    # ------------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Root menu: machine settings or recipe management."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["machine_settings", "machine_drinks", "recipes_menu"],
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
                default=current.get(CONF_MACHINE_DOUBLE_SWITCH, ""),
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

    async def async_step_machine_drinks(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Options: update available drinks."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        available = _get_machine_drink_options(self.hass, current.get(CONF_MACHINE_DRINK_SELECT))
        options = [selector.SelectOptionDict(value=d, label=d) for d in available]
        schema = vol.Schema({
            vol.Required(
                CONF_DRINK_OPTIONS,
                default=current.get(CONF_DRINK_OPTIONS, available),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
        return self.async_show_form(step_id="machine_drinks", data_schema=schema)

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
    # Add recipe — step 1: name + description
    # ------------------------------------------------------------------

    async def async_step_recipe_add(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Add recipe: collect name and description."""
        if user_input is not None:
            self._recipe_name = user_input["name"].strip()
            self._recipe_description = user_input.get("description", "")
            self._recipe_steps = []
            self._step_prefill = []
            self._step_index = 0
            self._edit_key = None
            return await self.async_step_recipe_step()

        schema = vol.Schema({
            vol.Required("name"): selector.TextSelector(),
            vol.Optional("description", default=""): selector.TextSelector(),
        })
        return self.async_show_form(step_id="recipe_add", data_schema=schema)

    # ------------------------------------------------------------------
    # Shared step builder (add + edit reuse this)
    # ------------------------------------------------------------------

    async def async_step_recipe_step(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Collect one step (drink or switch), optionally loop for more."""
        errors: dict[str, str] = {}

        if user_input is not None:
            step_type = user_input.get("step_type", "drink")
            if step_type == "switch":
                switch_entity = (user_input.get("switch_entity") or "").strip()
                if not switch_entity:
                    errors["switch_entity"] = "switch_entity_required"
                elif not self.hass.states.get(switch_entity):
                    errors["switch_entity"] = "entity_not_found"
                else:
                    self._recipe_steps.append({
                        "switch": switch_entity,
                        "timeout": int(user_input.get("timeout", 300)),
                    })
            else:
                self._recipe_steps.append({
                    "drink": user_input["drink"],
                    "double": bool(user_input.get("double", False)),
                    "timeout": int(user_input.get("timeout", 300)),
                })

            if not errors:
                self._step_index += 1
                if user_input.get("add_another", False):
                    return await self.async_step_recipe_step()
                return await self._save_current_recipe()

        # Pre-fill with existing step when editing
        prefill: dict = {}
        if self._step_prefill and self._step_index < len(self._step_prefill):
            prefill = self._step_prefill[self._step_index]

        # Suggest "add another" if there are more existing steps to walk through
        more_exist = (
            self._step_prefill
            and self._step_index + 1 < len(self._step_prefill)
        )

        # Determine prefill step type
        is_switch_prefill = "switch" in prefill
        default_step_type = "switch" if is_switch_prefill else "drink"

        # Use configured drinks for this machine, fall back to machine entity options
        current_config = {**self._config_entry.data, **self._config_entry.options}
        configured_drinks = current_config.get(
            CONF_DRINK_OPTIONS,
            _get_machine_drink_options(self.hass, current_config.get(CONF_MACHINE_DRINK_SELECT)),
        )
        drink_options = [
            selector.SelectOptionDict(value=d, label=d) for d in configured_drinks
        ]
        default_drink = prefill.get("drink") or (configured_drinks[0] if configured_drinks else "Espresso")
        default_switch = prefill.get("switch", "") if is_switch_prefill else ""

        schema = vol.Schema({
            vol.Required("step_type", default=default_step_type):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="drink", label="Drink"),
                            selector.SelectOptionDict(value="switch", label="Switch"),
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            vol.Required("drink", default=default_drink):
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=drink_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            vol.Optional("double", default=bool(prefill.get("double", False))):
                selector.BooleanSelector(),
            vol.Optional("switch_entity", default=default_switch):
                selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
            vol.Optional("timeout", default=int(prefill.get("timeout", 300))):
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=3600, step=10,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            vol.Optional("add_another", default=bool(more_exist)):
                selector.BooleanSelector(),
        })

        return self.async_show_form(
            step_id="recipe_step",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "step_num": str(self._step_index + 1),
                "recipe_name": self._recipe_name,
            },
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
        """Edit: collect updated name and description, then step through steps."""
        storage = self._get_storage()
        existing = storage.get_recipe(self._edit_key) or {}

        if user_input is not None:
            self._recipe_name = user_input["name"].strip()
            self._recipe_description = user_input.get("description", "")
            self._recipe_steps = []
            self._step_prefill = list(existing.get("steps", []))
            self._step_index = 0
            return await self.async_step_recipe_step()

        schema = vol.Schema({
            vol.Required("name", default=existing.get("name", "")): selector.TextSelector(),
            vol.Optional("description", default=existing.get("description", "")): selector.TextSelector(),
        })
        return self.async_show_form(
            step_id="recipe_edit",
            data_schema=schema,
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
        )
