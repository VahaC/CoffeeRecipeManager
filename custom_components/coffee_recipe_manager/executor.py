"""Coffee Recipe Executor - core state machine."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DEFAULT_STANDBY_STATE,
    DEFAULT_STEP_TIMEOUT,
    EXECUTOR_COMPLETED,
    EXECUTOR_ERROR,
    EXECUTOR_IDLE,
    EXECUTOR_RUNNING,
    EXECUTOR_WAITING_FAULT_CLEAR,
    EVENT_RECIPE_COMPLETED,
    EVENT_RECIPE_FAILED,
    EVENT_RECIPE_STARTED,
    EVENT_STEP_STARTED,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class RecipeExecutor:
    """Executes coffee recipes step by step with fault monitoring."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        on_state_change: Callable | None = None,
    ) -> None:
        self.hass = hass
        self.config = config
        self.on_state_change = on_state_change

        self._status = EXECUTOR_IDLE
        self._current_recipe: str | None = None
        self._current_step: int = 0
        self._total_steps: int = 0
        self._error: str | None = None
        self._last_recipe: str | None = None
        self._abort_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._fault_unsub = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    @property
    def current_recipe(self) -> str | None:
        return self._current_recipe

    @property
    def current_step(self) -> int:
        return self._current_step

    @property
    def total_steps(self) -> int:
        return self._total_steps

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def last_recipe(self) -> str | None:
        return self._last_recipe

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def brew(self, recipe_name: str, steps: list[dict]) -> None:
        """Start brewing a recipe. Aborts any running recipe first."""
        if self._status == EXECUTOR_RUNNING:
            await self.abort()

        self._abort_event.clear()
        self._current_recipe = recipe_name
        self._total_steps = len(steps)
        self._current_step = 0
        self._error = None
        self._set_status(EXECUTOR_RUNNING)

        self.hass.bus.async_fire(EVENT_RECIPE_STARTED, {"recipe": recipe_name})
        _LOGGER.info("Starting recipe: %s (%d steps)", recipe_name, len(steps))

        self._task = self.hass.async_create_task(
            self._run(recipe_name, steps)
        )

    async def abort(self) -> None:
        """Abort currently running recipe."""
        _LOGGER.info("Aborting recipe: %s", self._current_recipe)
        self._abort_event.set()
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._cleanup()
        self._set_status(EXECUTOR_IDLE)

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    async def _run(self, recipe_name: str, steps: list[dict]) -> None:
        """Main execution loop."""
        try:
            for idx, step in enumerate(steps):
                if self._abort_event.is_set():
                    _LOGGER.info("Recipe aborted before step %d", idx + 1)
                    self._set_status(EXECUTOR_IDLE)
                    return

                self._current_step = idx + 1
                self._set_status(EXECUTOR_RUNNING)
                self.hass.bus.async_fire(
                    EVENT_STEP_STARTED,
                    {"recipe": recipe_name, "step": idx + 1, "total": self._total_steps},
                )
                _LOGGER.info(
                    "Recipe '%s': step %d/%d — %s",
                    recipe_name, idx + 1, self._total_steps, step
                )

                success = await self._execute_step(step)

                if not success:
                    # _execute_step already set error and status
                    return

            # All steps done
            self._last_recipe = recipe_name
            self._set_status(EXECUTOR_COMPLETED)
            self.hass.bus.async_fire(EVENT_RECIPE_COMPLETED, {"recipe": recipe_name})
            _LOGGER.info("Recipe '%s' completed successfully", recipe_name)

        except asyncio.CancelledError:
            _LOGGER.info("Recipe task cancelled")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Unexpected error in recipe '%s'", recipe_name)
            await self._fail(str(exc))
        finally:
            self._cleanup()

    async def _execute_step(self, step: dict) -> bool:
        """Execute one step. Returns True if ok, False if failed/aborted."""
        drink = step.get("drink")
        double = step.get("double", False)
        timeout = step.get("timeout", DEFAULT_STEP_TIMEOUT)

        if not drink:
            _LOGGER.warning("Step has no 'drink' field, skipping: %s", step)
            return True

        # 1. Check faults BEFORE starting
        fault = self._get_active_fault()
        if fault:
            await self._fail(f"Fault before step: {fault}")
            return False

        # 2. Select drink
        drink_entity = self.config["machine_drink_select"]
        await self.hass.services.async_call(
            "select", "select_option",
            {"entity_id": drink_entity, "option": drink},
            blocking=True,
        )

        # 3. Set double if needed
        double_entity = self.config.get("machine_double_switch")
        if double_entity:
            service = "turn_on" if double else "turn_off"
            await self.hass.services.async_call(
                "switch", service,
                {"entity_id": double_entity},
                blocking=True,
            )

        # Small delay to let machine accept settings
        await asyncio.sleep(1)

        # 4. Start
        start_entity = self.config["machine_start_switch"]
        await self.hass.services.async_call(
            "switch", "turn_on",
            {"entity_id": start_entity},
            blocking=True,
        )

        # 5. Wait for standby OR fault OR abort
        result = await self._wait_for_completion(timeout)
        return result

    async def _wait_for_completion(self, timeout: int) -> bool:
        """
        Wait until machine returns to standby.
        Monitors: work_state -> standby, any fault sensor, abort event.
        Returns True if completed ok.
        """
        work_state_entity = self.config["machine_work_state"]
        standby_value = self.config.get("standby_state", DEFAULT_STANDBY_STATE)
        fault_sensors = self.config.get("fault_sensors", [])

        done_event = asyncio.Event()
        fault_detected: list[str] = []

        @callback
        def _state_listener(event):
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            if new_state is None:
                return

            if entity_id == work_state_entity:
                if new_state.state == standby_value:
                    done_event.set()

            elif entity_id in fault_sensors:
                if new_state.state == "on":
                    fault_detected.append(f"{entity_id} = on")
                    done_event.set()

        entities_to_watch = [work_state_entity] + list(fault_sensors)
        unsub = async_track_state_change_event(
            self.hass, entities_to_watch, _state_listener
        )

        try:
            # Also check current state immediately (machine may already be standby)
            current = self.hass.states.get(work_state_entity)
            if current and current.state == standby_value:
                return True

            # Check faults immediately
            fault = self._get_active_fault()
            if fault:
                await self._fail(f"Fault detected: {fault}")
                return False

            # Wait with timeout
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done, pending = await asyncio.wait(
                [abort_task, done_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if not done:
                # Timeout
                await self._fail(f"Timeout after {timeout}s waiting for machine")
                return False

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return False

            if fault_detected:
                fault_msg = ", ".join(fault_detected)
                await self._fail(f"Fault during brewing: {fault_msg}")
                return False

            return True

        finally:
            unsub()

    def _get_active_fault(self) -> str | None:
        """Return description of first active fault sensor, or None."""
        for sensor_id in self.config.get("fault_sensors", []):
            state = self.hass.states.get(sensor_id)
            if state and state.state == "on":
                friendly = state.attributes.get("friendly_name", sensor_id)
                return friendly
        return None

    async def _fail(self, reason: str) -> None:
        """Mark recipe as failed and send notifications."""
        _LOGGER.error(
            "Recipe '%s' failed at step %d/%d: %s",
            self._current_recipe, self._current_step, self._total_steps, reason
        )
        self._error = reason
        self._set_status(EXECUTOR_ERROR)

        self.hass.bus.async_fire(
            EVENT_RECIPE_FAILED,
            {
                "recipe": self._current_recipe,
                "step": self._current_step,
                "reason": reason,
            },
        )

        await self._notify(
            f"☕ Recipe failed: {self._current_recipe}\n"
            f"Step {self._current_step}/{self._total_steps}\n"
            f"Reason: {reason}"
        )

    async def _notify(self, message: str) -> None:
        """Send persistent notification + optional mobile push."""
        # Always send persistent notification
        await self.hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Coffee Recipe Manager",
                "message": message,
                "notification_id": f"{DOMAIN}_notification",
            },
            blocking=False,
        )

        # Mobile push if configured
        notify_service = self.config.get("notify_service", "")
        if notify_service and notify_service != "none":
            try:
                domain, service = notify_service.rsplit(".", 1)
                await self.hass.services.async_call(
                    domain, service,
                    {"title": "☕ Coffee Recipe Manager", "message": message},
                    blocking=False,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Failed to send mobile notification: %s", exc)

    def _set_status(self, status: str) -> None:
        self._status = status
        if self.on_state_change:
            self.on_state_change()

    def _cleanup(self) -> None:
        if self._fault_unsub:
            self._fault_unsub()
            self._fault_unsub = None
