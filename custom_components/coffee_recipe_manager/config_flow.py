"""Config flow for Coffee Recipe Manager."""
from __future__ import annotations

import logging
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


class CoffeeRecipeManagerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Coffee Recipe Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
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

        return self.async_show_form(step_id="init", data_schema=schema)
