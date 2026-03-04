"""Logbook support for Coffee Recipe Manager."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, EVENT_RECIPE_FAILED


def async_describe_events(
    hass: HomeAssistant,
    async_describe_event,
) -> None:
    """Describe logbook events so error reasons appear in the activity log."""

    @callback
    def async_describe_recipe_failed(event) -> dict:
        data = event.data
        recipe = data.get("recipe", "unknown")
        step = data.get("step", "?")
        reason = data.get("reason", "unknown error")
        return {
            "name": "Coffee Recipe Manager",
            "message": f"recipe '{recipe}' failed at step {step}: {reason}",
        }

    async_describe_event(DOMAIN, EVENT_RECIPE_FAILED, async_describe_recipe_failed)
