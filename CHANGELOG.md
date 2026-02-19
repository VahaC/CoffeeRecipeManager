# Changelog

All notable changes to Coffee Recipe Manager are documented here.

---

## [0.2.3] — 2026-02-19

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
