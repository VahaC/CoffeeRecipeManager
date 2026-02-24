"""Coffee Recipe Executor - core state machine."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    BREW_STATS_STORE_KEY,
    BREW_STATS_STORE_VERSION,
    DEFAULT_START_TIMEOUT,
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
        self._current_step_drink: str | None = None
        self._last_completed_at: str | None = None
        self._brew_count: dict[str, int] = {}
        self._abort_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._fault_unsub = None
        self._store = Store(hass, BREW_STATS_STORE_VERSION, BREW_STATS_STORE_KEY)

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

    @property
    def current_step_drink(self) -> str | None:
        return self._current_step_drink

    @property
    def last_completed_at(self) -> str | None:
        return self._last_completed_at

    @property
    def brew_count(self) -> dict[str, int]:
        return dict(self._brew_count)

    # ------------------------------------------------------------------
    # Initialization (persistent storage)
    # ------------------------------------------------------------------

    async def async_initialize(self) -> None:
        """Load persisted brew stats from storage."""
        data = await self._store.async_load()
        if data:
            self._last_recipe = data.get("last_recipe")
            self._last_completed_at = data.get("last_completed_at")
            self._brew_count = data.get("brew_count", {})
            _LOGGER.debug(
                "Loaded brew stats: last=%s, counts=%s",
                self._last_recipe, self._brew_count,
            )

    async def _save_stats(self) -> None:
        """Persist brew stats."""
        await self._store.async_save({
            "last_recipe": self._last_recipe,
            "last_completed_at": self._last_completed_at,
            "brew_count": self._brew_count,
        })

    async def brew(self, recipe_name: str, steps: list[dict]) -> None:
        """Start brewing a recipe. Aborts any running recipe first."""
        if self._status == EXECUTOR_RUNNING:
            await self.abort()

        self._abort_event.clear()
        self._current_recipe = recipe_name
        self._total_steps = len(steps)
        self._current_step = 0
        self._current_step_drink = None
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
            self._last_completed_at = datetime.now(timezone.utc).isoformat()
            self._brew_count[recipe_name] = self._brew_count.get(recipe_name, 0) + 1
            self._current_step_drink = None
            self._set_status(EXECUTOR_COMPLETED)
            self.hass.bus.async_fire(EVENT_RECIPE_COMPLETED, {"recipe": recipe_name})
            _LOGGER.info("Recipe '%s' completed successfully", recipe_name)
            self.hass.async_create_task(self._save_stats())

        except asyncio.CancelledError:
            _LOGGER.info("Recipe task cancelled")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("Unexpected error in recipe '%s'", recipe_name)
            await self._fail(str(exc))
        finally:
            self._cleanup()

    async def _execute_step(self, step: dict) -> bool:
        """Execute one step with automatic fault-wait-resume. Returns True if ok."""
        switch_entity = step.get("switch")
        drink = step.get("drink")
        double = step.get("double", False)
        timeout = step.get("timeout", DEFAULT_STEP_TIMEOUT)

        # ── Switch-only step ────────────────────────────────────────────────
        # A step can target a specific switch directly (e.g. milkfrothing,
        # hotwaterdispensing, espressoshot) instead of the normal drink flow.
        if switch_entity:
            if self.hass.states.get(switch_entity) is None:
                await self._fail(
                    f"Switch entity '{switch_entity}' not found. "
                    f"Check the entity ID in the recipe."
                )
                return False

            while True:
                if self._abort_event.is_set():
                    self._set_status(EXECUTOR_IDLE)
                    return False

                fault = self._get_active_fault()
                if fault:
                    cleared = await self._wait_for_fault_clear(fault)
                    if not cleared:
                        return False
                    continue

                self._current_step_drink = switch_entity
                self._set_status(EXECUTOR_RUNNING)
                await self.hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": switch_entity},
                    blocking=True,
                )

                result = await self._wait_for_completion(timeout, start_entity=switch_entity)

                if result == "ok":
                    return True
                elif result == "retry":
                    _LOGGER.info(
                        "Recipe '%s' step %d: fault cleared, restarting switch step",
                        self._current_recipe, self._current_step,
                    )
                    continue
                else:
                    return False

        # ── Drink step (default) ────────────────────────────────────────────
        if not drink:
            _LOGGER.warning("Step has no 'drink' or 'switch' field, skipping: %s", step)
            return True

        # Resolve drink name case-insensitively against the actual select entity options.
        # This tolerates minor capitalisation differences in recipes (e.g. "Hotmilk" vs "HotMilk").
        drink_entity = self.config["machine_drink_select"]
        drink = self._resolve_drink_option(drink, drink_entity)
        if drink is None:
            await self._fail(
                f"Drink '{step.get('drink')}' not found in select entity '{drink_entity}'. "
                f"Valid options: {self._get_drink_options(drink_entity)}"
            )
            return False

        while True:
            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return False

            # 1. Check faults BEFORE starting — wait until cleared
            fault = self._get_active_fault()
            if fault:
                cleared = await self._wait_for_fault_clear(fault)
                if not cleared:
                    return False
                continue

            # 2. Select drink
            self._current_step_drink = drink
            self._set_status(EXECUTOR_RUNNING)
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": drink_entity, "option": drink},
                blocking=True,
            )

            # 3. Set double if needed
            double_entity = self.config.get("machine_double_switch")
            if double_entity:
                if self.hass.states.get(double_entity) is None:
                    _LOGGER.warning(
                        "Double switch entity '%s' not found — skipping double setting",
                        double_entity,
                    )
                else:
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

            if result == "ok":
                return True
            elif result == "retry":
                _LOGGER.info(
                    "Recipe '%s' step %d: fault cleared, restarting step",
                    self._current_recipe, self._current_step,
                )
                continue
            else:  # "abort" or "timeout"
                return False

    async def _wait_for_completion(self, timeout: int, start_entity: str | None = None) -> str:
        """
        Wait until machine finishes brewing.

        Tracks the given switch entity (defaults to machine_start_switch):

          Stage 1 – wait for the switch to turn ON (confirm brew started).
                    Uses DEFAULT_START_TIMEOUT.

          Stage 2 – wait for the switch to turn OFF (brew finished).
                    Uses the per-step timeout.

        Monitors: switch changes, fault sensors, abort event.
        Returns: "ok" | "abort" | "timeout" | "retry" (fault cleared, retry step).
        """
        if start_entity is None:
            start_entity = self.config["machine_start_switch"]
        fault_sensors = self.config.get("fault_sensors", [])

        # stage1: start switch confirmed ON (brew started)
        start_event = asyncio.Event()
        # stage2: start switch turned OFF (brew finished)
        done_event = asyncio.Event()
        fault_detected: list[str] = []
        machine_started = False

        @callback
        def _state_listener(event):
            nonlocal machine_started
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if new_state is None:
                return

            old_val = old_state.state if old_state else "?"
            new_val = new_state.state

            if entity_id == start_entity:
                _LOGGER.debug(
                    "start_switch changed: %s → %s  (recipe='%s' step=%d machine_started=%s)",
                    old_val, new_val,
                    self._current_recipe, self._current_step, machine_started,
                )
                if new_val == "on":
                    # Start switch turned ON — brew started
                    machine_started = True
                    start_event.set()
                elif new_val == "off":
                    # Start switch turned OFF — brew finished.
                    # Retroactively mark as started — handles the case where HA
                    # missed the off→on transition (fast-dispensing drinks like
                    # Hotwater) but did catch the on→off one.
                    machine_started = True
                    start_event.set()
                    _LOGGER.debug(
                        "start_switch → off: signalling done  (recipe='%s' step=%d)",
                        self._current_recipe, self._current_step,
                    )
                    done_event.set()

            elif entity_id in fault_sensors:
                if new_val == "on":
                    fault_detected.append(f"{entity_id} = on")
                    # Unblock both stages
                    start_event.set()
                    done_event.set()

        entities_to_watch = [start_entity] + list(fault_sensors)
        unsub = async_track_state_change_event(
            self.hass, entities_to_watch, _state_listener
        )

        try:
            # Check faults immediately before waiting
            fault = self._get_active_fault()
            if fault:
                cleared = await self._wait_for_fault_clear(fault)
                return "retry" if cleared else "abort"

            # Check if start switch is already ON before listener was registered
            current = self.hass.states.get(start_entity)
            current_val = current.state if current else "unavailable"
            _LOGGER.debug(
                "wait_for_completion: current start_switch='%s'  (recipe='%s' step=%d)",
                current_val, self._current_recipe, self._current_step,
            )
            if current and current.state == "on":
                machine_started = True
                start_event.set()
                _LOGGER.debug(
                    "Start switch already ON before listener registered  (recipe='%s' step=%d)",
                    self._current_recipe, self._current_step,
                )

            # ── Stage 1: wait for start switch to turn ON ───────────────────
            if not machine_started:
                _LOGGER.debug(
                    "Stage 1: waiting for start switch to turn ON  (recipe='%s' step=%d timeout=%ds)",
                    self._current_recipe, self._current_step, DEFAULT_START_TIMEOUT,
                )
                abort_task = self.hass.async_create_task(self._abort_event.wait())
                start_task = self.hass.async_create_task(start_event.wait())
                # Also watch done_event: fast-dispensing drinks may complete
                # before HA polls the ON state, so the switch fires only once —
                # for the on→off transition.
                done_task_s1 = self.hass.async_create_task(done_event.wait())

                done_s1, pending_s1 = await asyncio.wait(
                    [abort_task, start_task, done_task_s1],
                    timeout=DEFAULT_START_TIMEOUT,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending_s1:
                    t.cancel()

                if self._abort_event.is_set():
                    self._set_status(EXECUTOR_IDLE)
                    return "abort"

                if not done_s1:
                    # Start switch never turned ON within the timeout.
                    if start_entity == self.config.get("machine_start_switch"):
                        # Most likely cause: invalid drink name that the machine
                        # silently ignored (select option mismatch).
                        drink_entity = self.config["machine_drink_select"]
                        drink_state = self.hass.states.get(drink_entity)
                        current_option = drink_state.state if drink_state else "unknown"
                        await self._fail(
                            f"Machine did not start within {DEFAULT_START_TIMEOUT}s for step "
                            f"{self._current_step} (drink='{self._current_step_drink}'). "
                            f"Current select option is '{current_option}'. "
                            f"Check that the drink name in the recipe exactly matches the machine's option."
                        )
                    else:
                        await self._fail(
                            f"Switch '{start_entity}' did not turn ON within {DEFAULT_START_TIMEOUT}s "
                            f"for step {self._current_step}. "
                            f"Check that the entity ID is correct and the machine is responsive."
                        )
                    return "timeout"

                # If done_event fired in Stage 1 (switch already back OFF),
                # the brew completed during Stage 1 — skip Stage 2.
                if done_event.is_set() and not fault_detected:
                    _LOGGER.debug(
                        "Stage 1: drink completed before Stage 2 (fast-dispense)  (recipe='%s' step=%d)",
                        self._current_recipe, self._current_step,
                    )
                    return "ok"

                _LOGGER.debug(
                    "Stage 1 done: start switch turned ON  (recipe='%s' step=%d)",
                    self._current_recipe, self._current_step,
                )

                if fault_detected:
                    fault_msg = ", ".join(fault_detected)
                    cleared = await self._wait_for_fault_clear(fault_msg)
                    return "retry" if cleared else "abort"

            # ── Stage 2: wait for start switch to turn OFF ──────────────────
            _LOGGER.debug(
                "Stage 2: waiting for start switch to turn OFF  (recipe='%s' step=%d timeout=%ds)",
                self._current_recipe, self._current_step, timeout,
            )
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done_s2, pending_s2 = await asyncio.wait(
                [abort_task, done_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending_s2:
                t.cancel()

            if not done_s2:
                await self._fail(f"Timeout after {timeout}s waiting for machine to finish")
                return "timeout"

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return "abort"

            if fault_detected:
                fault_msg = ", ".join(fault_detected)
                cleared = await self._wait_for_fault_clear(fault_msg)
                return "retry" if cleared else "abort"

            _LOGGER.debug(
                "Stage 2 done: start switch turned OFF  (recipe='%s' step=%d)",
                self._current_recipe, self._current_step,
            )
            return "ok"

        finally:
            unsub()

    async def _wait_for_fault_clear(self, fault_description: str) -> bool:
        """
        Pause recipe execution and wait until all fault sensors turn off.
        Sends a notification to the user. Returns True when cleared, False if aborted.
        """
        _LOGGER.warning(
            "Recipe '%s' paused at step %d/%d — fault: %s. Waiting for resolution...",
            self._current_recipe, self._current_step, self._total_steps, fault_description,
        )
        self._set_status(EXECUTOR_WAITING_FAULT_CLEAR)

        await self._notify(
            f"⚠️ Recipe paused: {self._current_recipe}\n"
            f"Step {self._current_step}/{self._total_steps}\n"
            f"Fault: {fault_description}\n"
            f"Fix the issue and brewing will resume automatically."
        )

        fault_sensors = self.config.get("fault_sensors", [])
        clear_event = asyncio.Event()

        @callback
        def _fault_clear_listener(event):
            # Fire the event only when all faults are gone
            if not self._get_active_fault():
                clear_event.set()

        unsub = async_track_state_change_event(
            self.hass, fault_sensors, _fault_clear_listener
        )

        try:
            # Already clear?
            if not self._get_active_fault():
                return True

            abort_task = self.hass.async_create_task(self._abort_event.wait())
            clear_task = self.hass.async_create_task(clear_event.wait())

            done, pending = await asyncio.wait(
                [abort_task, clear_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if self._abort_event.is_set():
                return False

            # Fault cleared — small delay then resume
            _LOGGER.info(
                "Fault cleared for recipe '%s' step %d, resuming in 2s...",
                self._current_recipe, self._current_step,
            )
            await asyncio.sleep(2)
            self._set_status(EXECUTOR_RUNNING)

            await self._notify(
                f"✅ Fault resolved. Resuming recipe: {self._current_recipe}\n"
                f"Step {self._current_step}/{self._total_steps}"
            )
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

    def _get_drink_options(self, drink_entity: str) -> list[str]:
        """Return the list of valid options from the select entity."""
        state = self.hass.states.get(drink_entity)
        if state:
            return list(state.attributes.get("options", []))
        return []

    def _resolve_drink_option(self, drink: str, drink_entity: str) -> str | None:
        """
        Return the correctly-cased option name for *drink* from the select entity.
        Tries exact match first, then case-insensitive. Returns None if not found.
        """
        options = self._get_drink_options(drink_entity)
        if not options:
            # Entity unavailable — can't validate; pass through as-is and let HA decide
            _LOGGER.warning(
                "Could not read options from '%s' — using drink name as-is: %s",
                drink_entity, drink,
            )
            return drink
        # Exact match
        if drink in options:
            return drink
        # Case-insensitive match
        drink_lower = drink.lower()
        for opt in options:
            if opt.lower() == drink_lower:
                _LOGGER.warning(
                    "Drink name '%s' matched to '%s' (case-insensitive). "
                    "Update the recipe to use the exact name.",
                    drink, opt,
                )
                return opt
        return None

    def _cleanup(self) -> None:
        self._current_step_drink = None
        if self._fault_unsub:
            self._fault_unsub()
            self._fault_unsub = None
