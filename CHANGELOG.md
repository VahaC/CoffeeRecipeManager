# Changelog

All notable changes to Coffee Recipe Manager are documented here.

---

## [0.3.2] — 2026-02-24

### Improvements

- **Switch entity dropdown in the recipe UI** — The `switch_entities` field in
  the recipe step form is now a proper **entity selector** (dropdown) rather than
  a plain text input. Entities are filtered to domain `switch`, so only relevant
  switches appear in the list.

- **Multiple switches per step** — The switch step now supports selecting
  **multiple switch entities** from the UI (or via `switches: [...]` in YAML).
  Switches are executed sequentially within the step, each with full fault
  monitoring and retry-on-fault-clear. The old single-entity `switch:` field
  in YAML remains supported for backward compatibility.

- **Fix: raw field labels in the step form** — Field keys `step_type` and
  `switch_entity` were displayed as raw identifiers instead of their translated
  labels. Translation strings have been cleaned up and the field renamed to
  `switch_entities` to match the new multi-select behaviour.

---

## [0.3.1] — 2026-02-24

### Improvements

- **Switch steps available in the UI** — The recipe step form now includes a
  **Step type** selector (`Drink` / `Switch`). When `Switch` is selected, a
  plain text field accepts any switch entity ID (e.g.
  `switch.coffee_machine_milkfrothing`, `switch.coffee_machine_hotwaterdispensing`,
  `switch.coffee_machine_espressoshot`). The entity is validated against
  `hass.states` before the step is saved — a descriptive inline error is shown
  if the entity is not found. The existing drink/double/timeout fields remain
  unchanged for `Drink` steps.

  Both **Add recipe** and **Edit recipe** flows support the new step type,
  including correct pre-filling when editing an existing switch step.

---

## [0.3.0] — 2026-02-24

### New Features

- **Direct switch steps in recipes** — Recipe steps can now activate a specific
  switch entity directly, without going through the drink select flow. This
  enables full control over auxiliary machine functions:

  ```yaml
  steps:
    - switch: switch.coffee_machine_milkfrothing
      timeout: 60
    - drink: Espresso
      double: true
      timeout: 180
    - switch: switch.coffee_machine_espressoshot
      timeout: 120
  ```

  Supported fields for a switch step:
  | Field | Required | Default | Description |
  |-------|----------|---------|-------------|
  | `switch` | ✅ | — | Full entity ID of the switch to activate |
  | `timeout` | ❌ | 300 s | Max time to wait for the switch to turn OFF |

  The executor turns the switch ON and waits for it to turn OFF using the same
  two-stage completion logic as drink steps, including fault monitoring and
  retry-on-fault-clear. If the entity is not found, the recipe fails
  immediately with a descriptive notification.

### Improvements

- **Brew completion now tracked via start switch** — `_wait_for_completion`
  previously monitored the `machine_work_state` sensor (standby ↔ non-standby
  transitions). It now tracks the `machine_start_switch` entity (OFF → ON →
  OFF cycle) instead.

  This is more reliable because:
  - The start switch is a first-class HA entity that changes state atomically.
  - It does not depend on polling intervals of a sensor.
  - Works uniformly for both drink steps and the new direct switch steps.

  Stage 1 waits for the tracked switch to turn **ON** (brew confirmed started).
  Stage 2 waits for it to turn **OFF** (brew finished). Fast-dispensing drinks
  that complete before HA polls the ON state are still handled correctly — if
  only the ON→OFF transition is observed, the step is immediately marked done.

- **Context-aware timeout error messages** — When Stage 1 times out, the error
  message now distinguishes between the main start switch (hints at a possible
  drink name mismatch) and a recipe-level switch entity (hints at a wrong
  entity ID).

---

## [0.2.4] — 2026-02-19

### Bug Fixes

- **Recipe failed immediately on step 2 with "Option X is not valid"** —
  When a recipe used a drink name with different capitalisation than the
  machine's select entity (e.g. `HotMilk` in the recipe vs `Hotmilk` on
  the machine), HA raised `ServiceValidationError` on the very first service
  call of that step, causing an immediate recipe failure.

  The executor now resolves drink names against the machine's select entity
  options before calling the service:
  - **Exact match** → used as-is.
  - **Case-insensitive match** → the correctly-cased option is used and a
    `WARNING` is logged advising the user to update the recipe.
  - **No match at all** → recipe fails immediately with a clear notification
    listing all valid options.

- **`machine_double_switch` not truly optional** — Initial config flow was
  pre-filling the double switch field with a default entity id, so users who
  left it blank still ended up with a potentially non-existent entity in
  their config. Now the field starts empty; empty/missing values are
  normalised to `None` before reaching the executor. The executor also
  validates entity existence via `hass.states.get()` before calling the
  switch service and logs a warning instead of failing silently.

- **Diagnostic: machine ignored start command** — If the machine never
  leaves standby within `DEFAULT_START_TIMEOUT` (15 s) after the start
  switch is turned on, the executor now calls `_fail()` with a message that
  shows the current select option value — making it easy to spot an invalid
  drink name even without debug logging enabled.

### Improvements

- **Detailed debug logging in `_wait_for_completion`** — Every `work_state`
  transition (old → new), stage entry/exit, and the current state at entry
  are now logged at `DEBUG` level. Enable with:
  ```yaml
  logger:
    logs:
      custom_components.coffee_recipe_manager: debug
  ```

---

## [0.2.3] — 2026-02-19

### Bug Fixes

- **Premature recipe completion** — After the start command was issued the
  executor immediately checked whether the machine was in standby. Because the
  machine had not yet transitioned out of standby, this check returned `"ok"`
  instantly and the recipe was marked as completed within seconds, without
  actually waiting for the drink to be prepared.

- **Subsequent steps skipped** — As a direct consequence of the above, in
  multi-step recipes (e.g. *LatteMacchiato → HotMilk*) all steps after the
  first were dispatched to the machine while it was still brewing. The commands
  were silently ignored by the machine, so only the first drink was made.

### How It Was Fixed

`RecipeExecutor._wait_for_completion` was rewritten with a **two-stage**
monitoring approach:

| Stage | Waits for | Timeout |
|-------|-----------|---------|
| 1 | Machine **leaves** standby — confirms the brew actually started | `DEFAULT_START_TIMEOUT` (15 s) |
| 2 | Machine **returns** to standby — confirms the brew finished | per-step `timeout` (default 300 s) |

A new constant `DEFAULT_START_TIMEOUT = 15` was added to `const.py`.

---

## [0.2.2] — 2026-02-15

- HACS: restore `icon.png` and `icon@2x.png`.

## [0.2.1] — 2026-02-15

- HACS: add icon reference in `hacs.json`, update features list.

## [0.2.0] — 2026-02-13

- Richer `sensor.recipe_status` attributes (`current_step_drink`,
  `current_step`, `total_steps`, `last_recipe`, `last_completed_at`,
  `brew_count`).
- Persistent brew statistics (survive HA restarts).
- Drink validation when saving a recipe via UI.

## [0.1.1] — earlier

- Add `view_selected_recipe` button entity.

## [0.1.0] — earlier

- Initial release: `brew_recipe` / `abort_recipe` services, step execution,
  fault monitoring, persistent notifications.


### Bug Fixes

- **Premature recipe completion** — After the start command was issued the
  executor immediately checked whether the machine was in standby. Because the
  machine had not yet transitioned out of standby, this check returned `"ok"`
  instantly and the recipe was marked as completed within seconds, without
  actually waiting for the drink to be prepared.

- **Subsequent steps skipped** — As a direct consequence of the above, in
  multi-step recipes (e.g. *LatteMacchiato → Hotmilk*) all steps after the
  first were dispatched to the machine while it was still brewing. The commands
  were silently ignored by the machine, so only the first drink was made.

### How It Was Fixed

`RecipeExecutor._wait_for_completion` was rewritten with a **two-stage**
monitoring approach:

| Stage | Waits for | Timeout |
|-------|-----------|---------|
| 1 | Machine **leaves** standby — confirms the brew actually started | `DEFAULT_START_TIMEOUT` (15 s) |
| 2 | Machine **returns** to standby — confirms the brew finished | per-step `timeout` (default 300 s) |

The `done_event` is now only set when the machine state changes
`working → standby`, not when it is already in standby at the moment the
method is entered.

If the machine never leaves standby within the Stage 1 window (e.g. instant
command or a missed transition), a warning is logged and the step is treated as
completed — preserving backward compatibility.

A new constant `DEFAULT_START_TIMEOUT = 15` was added to `const.py`.

---

## [0.2.2] — 2026-02-15

- HACS: restore `icon.png` and `icon@2x.png`.

## [0.2.1] — 2026-02-15

- HACS: add icon reference in `hacs.json`, update features list.

## [0.2.0] — 2026-02-13

- Richer `sensor.recipe_status` attributes (`current_step_drink`,
  `current_step`, `total_steps`, `last_recipe`, `last_completed_at`,
  `brew_count`).
- Persistent brew statistics (survive HA restarts).
- Drink validation when saving a recipe via UI.

## [0.1.1] — earlier

- Add `view_selected_recipe` button entity.

## [0.1.0] — earlier

- Initial release: `brew_recipe` / `abort_recipe` services, step execution,
  fault monitoring, persistent notifications.
