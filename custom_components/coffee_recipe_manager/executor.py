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

        # ── Switch step(s) ──────────────────────────────────────────────────
        # Supports three formats (newest first):
        #   switch_counts: {"entity_id": N, ...}  (UI / v0.3.3, per-switch repeat count)
        #   switches: ["entity1", ...]             (UI / v0.3.2, list, each run once)
        #   switch: "entity_id"                    (YAML / legacy, single, run once)
        #
        # Builds a list of (entity_id, count) pairs, then executes each
        # entity sequentially the specified number of times.
        switch_runs: list[tuple[str, int]] = []
        if step.get("switch_counts"):
            for entity_id, count in step["switch_counts"].items():
                n = int(count) if count else 0
                if n > 0:
                    switch_runs.append((entity_id, n))
        elif step.get("switches"):
            raw = step["switches"]
            entities = [raw] if isinstance(raw, str) else list(raw)
            switch_runs = [(e, 1) for e in entities]
        elif switch_entity:
            switch_runs = [(switch_entity, 1)]

        if switch_runs:
            # Validate all entities before starting
            for entity_id, _ in switch_runs:
                if self.hass.states.get(entity_id) is None:
                    await self._fail(
                        f"Switch entity '{entity_id}' not found. "
                        f"Check the entity ID in the recipe."
                    )
                    return False

            # Execute each switch the required number of times, in sequence
            for entity_id, count in switch_runs:
                _LOGGER.warning(
                    "[CRM] switch loop START: entity=%s count=%d timeout=%d recipe='%s' step=%d",
                    entity_id, count, timeout, self._current_recipe, self._current_step,
                )
                for run_num in range(count):
                    run_start = self.hass.loop.time()
                    _LOGGER.warning(
                        "[CRM] run %d/%d BEGIN entity=%s",
                        run_num + 1, count, entity_id,
                    )

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

                        self._current_step_drink = entity_id
                        self._set_status(EXECUTOR_RUNNING)

                        _LOGGER.warning(
                            "[CRM] calling _run_switch_once entity=%s run %d/%d",
                            entity_id, run_num + 1, count,
                        )
                        result = await self._run_switch_once(entity_id, timeout)
                        _LOGGER.warning(
                            "[CRM] _run_switch_once returned '%s' entity=%s run %d/%d",
                            result, entity_id, run_num + 1, count,
                        )

                        if result == "ok":
                            break  # next run / next switch
                        elif result == "retry":
                            _LOGGER.warning(
                                "[CRM] fault cleared, restarting switch '%s' (run %d/%d)",
                                entity_id, run_num + 1, count,
                            )
                            continue
                        else:
                            return False

                    run_elapsed = self.hass.loop.time() - run_start
                    _LOGGER.warning(
                        "[CRM] run %d/%d DONE entity=%s elapsed=%.2fs",
                        run_num + 1, count, entity_id, run_elapsed,
                    )

                    if run_num < count - 1:
                        # _run_switch_once already waited for full completion
                        # (both aux+machine_start ON→OFF), so just a short settle pause.
                        _LOGGER.warning(
                            "[CRM] inter-run settle 5s before run %d/%d entity=%s",
                            run_num + 2, count, entity_id,
                        )
                        await asyncio.sleep(5)

                _LOGGER.warning(
                    "[CRM] switch loop END: entity=%s all %d runs complete",
                    entity_id, count,
                )

        # ── Drink step ──────────────────────────────────────────────────────
        if not drink:
            if not switch_runs:
                _LOGGER.warning("Step has no 'drink' or switch action, skipping: %s", step)
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

    async def _run_switch_once(self, entity_id: str, timeout: int) -> str:
        """
        Turn on an auxiliary switch and wait for the machine to complete.

        Completion is signalled by EITHER:
          • the aux switch itself going OFF  (momentary / self-resetting switch), OR
          • machine_start_switch going OFF   (machine reports it finished the operation)
        whichever happens first.

        Stage 1 – send turn_on, then wait minimum 5s.
                  If either completion signal fires within 5s → fast complete.
        Stage 2 – wait up to `timeout` seconds for either completion signal.

        Returns: "ok" | "abort" | "timeout" | "retry"
        """
        machine_start_entity = self.config["machine_start_switch"]
        fault_sensors = self.config.get("fault_sensors", [])

        done_event = asyncio.Event()   # BOTH aux switch AND machine_start completed (ON→OFF)
        fault_detected: list[str] = []
        # Each entity transitions: unknown → on → done (off after being on).
        # An entity that starts OFF (idle) is "unknown", not "done".
        aux_state = "unknown"        # "unknown" | "on" | "done"
        machine_start_state = "unknown"

        @callback
        def _state_listener(event):
            nonlocal aux_state, machine_start_state
            entity = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            val = new_state.state
            _LOGGER.warning(
                "[CRM] state_listener: entity=%s old=%s new=%s aux_state=%s ms_state=%s",
                entity,
                event.data.get("old_state").state if event.data.get("old_state") else "?",
                val, aux_state, machine_start_state,
            )
            if entity == entity_id:
                if val == "on":
                    aux_state = "on"
                elif val == "off" and aux_state == "on":
                    aux_state = "done"
            elif entity == machine_start_entity:
                if val == "on":
                    machine_start_state = "on"
                elif val == "off" and machine_start_state == "on":
                    machine_start_state = "done"
            elif entity in fault_sensors and val == "on":
                fault_detected.append(f"{entity} = on")
                done_event.set()
                return
            if aux_state == "done" and machine_start_state == "done":
                _LOGGER.warning("[CRM] both aux and machine_start completed (ON→OFF) → done")
                done_event.set()

        entities_to_watch = [entity_id, machine_start_entity] + list(fault_sensors)
        unsub = async_track_state_change_event(self.hass, entities_to_watch, _state_listener)

        try:
            # Check faults before starting
            fault = self._get_active_fault()
            if fault:
                cleared = await self._wait_for_fault_clear(fault)
                return "retry" if cleared else "abort"

            ms = self.hass.states.get(machine_start_entity)
            aux = self.hass.states.get(entity_id)
            _LOGGER.warning(
                "[CRM] _run_switch_once PRE-CHECK entity=%s state=%s machine_start=%s",
                entity_id,
                aux.state if aux else "unavailable",
                ms.state if ms else "unavailable",
            )
            # If already ON before turn_on (e.g. machine is mid-operation from a
            # previous run) — mark as "on" so the upcoming OFF transition is recognised.
            if aux and aux.state == "on":
                aux_state = "on"
            if ms and ms.state == "on":
                machine_start_state = "on"
            # Note: if both are OFF (idle state) we leave states as "unknown" —
            # we must observe ON→OFF before counting as complete.

            # ── Turn the aux switch ON ──────────────────────────────────────
            _LOGGER.warning("[CRM] calling turn_on entity=%s", entity_id)
            await self.hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )
            ms_after = self.hass.states.get(machine_start_entity)
            aux_after = self.hass.states.get(entity_id)
            _LOGGER.warning(
                "[CRM] after turn_on entity=%s state=%s machine_start=%s",
                entity_id,
                aux_after.state if aux_after else "unavailable",
                ms_after.state if ms_after else "unavailable",
            )

            # ── Stage 1: wait minimum 5s (or either completion signal) ─────
            _LOGGER.warning(
                "[CRM] Stage 1: waiting 5s min (or aux/machine_start OFF) entity=%s",
                entity_id,
            )
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done_s1, pending = await asyncio.wait(
                [abort_task, done_task],
                timeout=5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            _LOGGER.warning(
                "[CRM] Stage 1 finished: abort=%s done_event=%s fault=%s",
                self._abort_event.is_set(), done_event.is_set(), fault_detected,
            )

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return "abort"

            if fault_detected:
                cleared = await self._wait_for_fault_clear(", ".join(fault_detected))
                return "retry" if cleared else "abort"

            if done_event.is_set():
                _LOGGER.warning("[CRM] fast complete in Stage 1 entity=%s", entity_id)
                return "ok"

            # ── Stage 2: wait for either completion signal ─────────────────
            _LOGGER.warning(
                "[CRM] Stage 2: waiting up to %ds for aux/machine_start OFF entity=%s",
                timeout, entity_id,
            )
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done_s2, pending = await asyncio.wait(
                [abort_task, done_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            _LOGGER.warning(
                "[CRM] Stage 2 finished: abort=%s done_s2_count=%d done_event=%s fault=%s",
                self._abort_event.is_set(), len(done_s2), done_event.is_set(), fault_detected,
            )

            if not done_s2:
                await self._fail(
                    f"Timeout after {timeout}s waiting for machine to finish '{entity_id}'"
                )
                return "timeout"

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return "abort"

            if fault_detected:
                cleared = await self._wait_for_fault_clear(", ".join(fault_detected))
                return "retry" if cleared else "abort"

            _LOGGER.warning("[CRM] Stage 2: done OK entity=%s", entity_id)
            return "ok"

        finally:
            unsub()

    async def _wait_for_completion(self, timeout: int, start_entity: str | None = None) -> str:
        """
        Wait until machine finishes brewing.

        Uses machine_start_switch as the completion signal:
          Stage 1 – wait minimum 5s; if machine_start goes OFF sooner → fast complete.
          Stage 2 – wait for machine_start to go OFF (brew finished). Uses per-step timeout.

        Monitors: machine_start_switch changes, fault sensors, abort event.
        Returns: "ok" | "abort" | "timeout" | "retry" (fault cleared, retry step).
        """
        if start_entity is None:
            start_entity = self.config["machine_start_switch"]
        fault_sensors = self.config.get("fault_sensors", [])

        done_event = asyncio.Event()   # start switch turned OFF → brew finished
        fault_detected: list[str] = []

        @callback
        def _state_listener(event):
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if new_state is None:
                return
            old_val = old_state.state if old_state else "?"
            new_val = new_state.state
            if entity_id == start_entity:
                _LOGGER.debug(
                    "start_switch changed: %s → %s  (recipe='%s' step=%d)",
                    old_val, new_val, self._current_recipe, self._current_step,
                )
                if new_val == "off":
                    done_event.set()
            elif entity_id in fault_sensors and new_val == "on":
                fault_detected.append(f"{entity_id} = on")
                done_event.set()

        entities_to_watch = [start_entity] + list(fault_sensors)
        unsub = async_track_state_change_event(self.hass, entities_to_watch, _state_listener)

        try:
            # Check faults immediately before waiting
            fault = self._get_active_fault()
            if fault:
                cleared = await self._wait_for_fault_clear(fault)
                return "retry" if cleared else "abort"

            # ── Stage 1: wait minimum 5s (or machine_start OFF) ─────────────
            _LOGGER.debug(
                "Stage 1: waiting 5s min (or start switch OFF)  (recipe='%s' step=%d)",
                self._current_recipe, self._current_step,
            )
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done_s1, pending = await asyncio.wait(
                [abort_task, done_task],
                timeout=5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return "abort"

            if fault_detected:
                cleared = await self._wait_for_fault_clear(", ".join(fault_detected))
                return "retry" if cleared else "abort"

            if done_event.is_set():
                _LOGGER.debug(
                    "Stage 1: start switch OFF (fast-dispense)  (recipe='%s' step=%d)",
                    self._current_recipe, self._current_step,
                )
                return "ok"

            # ── Stage 2: wait for start switch to turn OFF ───────────────────
            _LOGGER.debug(
                "Stage 2: waiting for start switch OFF  (recipe='%s' step=%d timeout=%ds)",
                self._current_recipe, self._current_step, timeout,
            )
            abort_task = self.hass.async_create_task(self._abort_event.wait())
            done_task = self.hass.async_create_task(done_event.wait())

            done_s2, pending = await asyncio.wait(
                [abort_task, done_task],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if not done_s2:
                await self._fail(f"Timeout after {timeout}s waiting for machine to finish")
                return "timeout"

            if self._abort_event.is_set():
                self._set_status(EXECUTOR_IDLE)
                return "abort"

            if fault_detected:
                cleared = await self._wait_for_fault_clear(", ".join(fault_detected))
                return "retry" if cleared else "abort"

            _LOGGER.debug(
                "Stage 2 done: start switch OFF  (recipe='%s' step=%d)",
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
