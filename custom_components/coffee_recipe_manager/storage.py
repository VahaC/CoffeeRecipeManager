"""Recipe storage - load and save recipes to YAML."""
from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STEP_SCHEMA = vol.Schema({
    vol.Required("drink"): str,
    vol.Optional("double", default=False): bool,
    vol.Optional("timeout", default=300): vol.All(int, vol.Range(min=10, max=3600)),
})

RECIPE_SCHEMA = vol.Schema({
    vol.Required("name"): str,
    vol.Required("steps"): vol.All(list, [STEP_SCHEMA]),
    vol.Optional("description", default=""): str,
})


class RecipeStorage:
    """Manages loading and saving recipes from/to YAML."""

    def __init__(self, hass: HomeAssistant, filepath: str) -> None:
        self.hass = hass
        self._filepath = filepath
        self._recipes: dict[str, dict] = {}
        self.on_recipes_changed: callable | None = None

    @property
    def recipes(self) -> dict[str, dict]:
        return self._recipes

    def get_recipe_names(self) -> list[str]:
        return list(self._recipes.keys())

    def get_recipe(self, name: str) -> dict | None:
        return self._recipes.get(name)

    async def load(self) -> None:
        """Load recipes from YAML file."""
        if not os.path.exists(self._filepath):
            _LOGGER.info("No recipes file found at %s, starting empty", self._filepath)
            await self._write_example()
            return

        try:
            with open(self._filepath, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

            recipes_raw = raw.get("recipes", {})
            loaded = {}
            for key, recipe in recipes_raw.items():
                try:
                    validated = RECIPE_SCHEMA(recipe)
                    loaded[key] = validated
                    _LOGGER.debug("Loaded recipe: %s", key)
                except vol.Invalid as exc:
                    _LOGGER.error("Invalid recipe '%s': %s", key, exc)

            self._recipes = loaded
            _LOGGER.info("Loaded %d recipes from %s", len(loaded), self._filepath)
            self._notify_changed()

        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to load recipes: %s", exc)

    async def save_recipe(self, key: str, recipe: dict) -> bool:
        """Add or update a recipe and save to file."""
        try:
            validated = RECIPE_SCHEMA(recipe)
            self._recipes[key] = validated
            await self._save_all()
            self._notify_changed()
            return True
        except vol.Invalid as exc:
            _LOGGER.error("Invalid recipe data: %s", exc)
            return False

    async def delete_recipe(self, key: str) -> bool:
        """Delete a recipe."""
        if key not in self._recipes:
            return False
        del self._recipes[key]
        await self._save_all()
        self._notify_changed()
        return True

    async def _save_all(self) -> None:
        """Write all recipes to YAML."""
        data = {"recipes": self._recipes}
        with open(self._filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        _LOGGER.debug("Saved recipes to %s", self._filepath)

    def _notify_changed(self) -> None:
        """Call on_recipes_changed callback if set."""
        if self.on_recipes_changed is not None:
            try:
                self.on_recipes_changed()
            except Exception:  # noqa: BLE001
                pass

    async def _write_example(self) -> None:
        """Write example recipes file."""
        example = {
            "recipes": {
                "macchiato_americano": {
                    "name": "Macchiato + Americano",
                    "description": "Double shot macchiato followed by americano",
                    "steps": [
                        {"drink": "LatteMacchiato", "double": False, "timeout": 300},
                        {"drink": "Americano", "double": False, "timeout": 300},
                    ],
                },
                "double_espresso_cappuccino": {
                    "name": "Double Espresso + Cappuccino",
                    "description": "Strong double espresso then a cappuccino",
                    "steps": [
                        {"drink": "Espresso", "double": True, "timeout": 180},
                        {"drink": "Cappuccino", "double": False, "timeout": 300},
                    ],
                },
            }
        }
        with open(self._filepath, "w", encoding="utf-8") as f:
            yaml.dump(example, f, allow_unicode=True, sort_keys=False)
        await self.load()
