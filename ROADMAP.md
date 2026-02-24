# 🗺️ Coffee Recipe Manager — Roadmap

## ✅ v0.2.x — Quick Wins *(completed)*

### 1. Richer recipe status sensor ✅
Added useful attributes to `sensor.coffee_recipe_status`:
- `current_step_drink` — drink being prepared right now
- `current_step_number` / `total_steps` — step progress (e.g. `2 / 3`)
- `last_completed_recipe` — name of last successfully brewed recipe
- `last_completed_at` — timestamp of last completion

### 2. `last_completed` persistent storage ✅
Last completed recipe name + timestamp stored in `hass.storage`
(survives HA restarts).

### 3. Drink validation on recipe save ✅
When saving a recipe via UI flow or service, an error is shown
if a step contains a drink not present in the configured `drink_options`.

### 4. Brew counter ✅
Per-recipe brew count stored persistently in `hass.storage`.
Exposed as `brew_count` attribute on `sensor.coffee_recipe_status`.

---

## ✅ v0.3.x — Recipe Capabilities *(completed)*

### v0.3.0 — Direct switch steps & reliable completion tracking ✅

- **Direct switch steps** — Recipe steps can now activate a switch entity directly
  (e.g. `switch.coffee_machine_milkfrothing`, `switch.coffee_machine_hotwaterdispensing`,
  `switch.coffee_machine_espressoshot`) without going through the drink select flow.
- **Start switch completion tracking** — `_wait_for_completion` now monitors
  `machine_start_switch` (ON → OFF cycle) instead of `machine_work_state` sensor.

---

### v0.3.1 — Switch steps in the recipe UI ✅

Step type selector (`Drink` / `Switch`) added to Add and Edit recipe step forms.

---

### v0.3.2 — Switch entity dropdown + multiple switches per step ✅

- Proper HA entity picker filtered to `switch` domain.
- Multiple switches per step, executed sequentially with fault monitoring.

---

### v0.3.3 — Recipe step UI redesign + auxiliary switch settings ✅

- Auxiliary switches configured once in Machine Settings, not per step.
- Drink dropdown (with *— None —* to skip), Double toggle, one **× count** field per
  configured switch (0 = skip, 1–10 = repeat N times).
- New YAML format: `switch_counts: {entity_id: N}`. Legacy formats still supported.

---

### v0.3.4 — v0.3.5 — Friendly names for auxiliary switch fields ✅

Auxiliary switch count field labels and descriptions now show the entity friendly name
(e.g. `Coffee Machine Milkfrothing (×)`) instead of `Switch 0 (×)`.

---

### v0.3.6 — Fix View Selected Recipe for all step types ✅

*View Selected Recipe* button and `get_recipe` service now render all step types
correctly. Previously crashed on non-drink steps.

---

### v0.3.7 — Fix auxiliary switch repeat count (listener timing) ✅

State listener now registered **before** calling `turn_on` so fast ON→OFF cycles on
momentary switches are never missed. New `_run_switch_once` helper.

---

### v0.3.8 — Fix "Change Drink to None" having no effect ✅

`— None —` drink option uses sentinel `"none"` instead of `""`. Handler converts it
to absent `drink` field; prefill maps missing drink back to `"none"` when re-editing.

---

### v0.3.9–v0.3.16 — Fix momentary-switch repeat reliability (stable) ✅

Extended diagnostic + fix cycle. Five root causes identified and resolved:

1. **Race condition** — listener registered after `turn_on`; ON+OFF events missed.
2. **Inter-run sleep too short** — machine still busy when next `turn_on` arrived.
3. **Wrong completion signal** — needed to also watch `machine_start_switch`.
4. **False completion on idle state** — both entities already OFF at start triggered
   done-event before the machine ran. Fixed with `unknown → on → done` state model.
5. **Single-entity done condition** — done now requires **both** aux switch AND
   `machine_start_switch` to complete ON→OFF transitions.

Final values: 5-second inter-run settle pause; `DEFAULT_STEP_TIMEOUT = 120s`.
`[CRM]` WARNING diagnostic logs demoted to DEBUG in v0.3.16.

---

### v0.3.17 — Edit Recipes button + fix drink=none display ✅

- **Edit Recipes button** (`button.coffee_recipe_edit_recipes`) — sends a persistent
  notification with a deep-link to the integration configuration page
  (`/config/integrations/integration/coffee_recipe_manager`) so recipes can be
  edited in one tap from any dashboard.
- Dashboard Lovelace alternative (no notification) documented in README.
- **Fix: `drink: none` shown as "☕ none"** — switch-only steps render without a
  drink line in View Recipe, `get_recipe`, and `list_recipes`. `list_recipes` no
  longer raises `KeyError` on switch-only steps.

---

## 🟡 v0.3.x — Remaining

### Fault wait timeout (`max_fault_wait`)
Currently waits indefinitely when a fault occurs.
Add configurable `max_fault_wait` (minutes, default: 30).
If not resolved within the timeout → abort recipe + notify.

Config option in Options Flow → Machine settings.

---

### Schedule / auto-brew
Allow scheduling a recipe at a specific time directly from the integration,
without needing manual HA automations.

UI: Options Flow → new "Schedule" menu
- Select recipe
- Set time (HH:MM)
- Days of week checkboxes
- Enable/disable toggle

Internally creates a time-based trigger via `hass.services`.

---

## 🔴 v0.4.x — Advanced Features

### Retry limit for faults
Add `max_fault_retries` — abort instead of resuming if the same fault triggers
more than N times during a single recipe run.

---

### Recipe import / export
- `export_recipes` service → writes `coffee_recipes_export.yaml` to HA config dir
- `import_recipes` service → reads from a specified path, merges or overwrites
- UI button in Options Flow → "Export all recipes"

---

### Multi-machine support
Refactor services to accept an optional `device_id` parameter:
```yaml
service: coffee_recipe_manager.brew_recipe
data:
  recipe_name: morning_boost
  device_id: abc123  # optional, defaults to first machine
```

---

## 🚀 v1.0.x — Custom UI

### Custom Lovelace card
A JavaScript Lovelace card (`www/coffee-recipe-card.js`) with:
- Full recipe list with click-to-expand details
- Inline recipe editor (name, description, add/remove/reorder steps)
- Brew button per recipe
- Live status display (current step, progress bar)

Built with LitElement. Registered automatically — no manual resource setup.

---

## 📋 Completed

| Version | Feature |
|---------|---------|
| v0.0.1 | Initial release — recipe executor, config flow, YAML storage |
| v0.0.2 | Fault auto-pause and auto-resume |
| v0.0.3 | UI Options Flow for recipe management (Add / Edit / Delete) |
| v0.0.4 | Step-by-step drink UI (no YAML editor) |
| v0.0.5 | Configurable drink list per machine |
| v0.0.6–v0.0.9 | Select + Button entities on device page, icon attempts, bug fixes |
| v0.1.0 | `list_recipes` and `get_recipe` services, dynamic drinks from machine entity |
| v0.1.1 | "View Selected Recipe" button on device page |
| v0.2.0 | Richer status sensor, persistent brew stats, drink validation |
| v0.2.1 | Integration icon added to HACS (`hacs.json`) |
| v0.2.2 | Restore `icon.png` and `icon@2x.png` |
| v0.2.3 | Fix premature recipe completion and skipped steps |
| v0.2.4 | Fix drink name case mismatch, fix optional double switch, detailed logging |
| v0.3.0 | Direct switch steps, completion tracking via start switch |
| v0.3.1 | Switch step type added to recipe UI |
| v0.3.2 | Switch entity dropdown, multiple switches per step |
| v0.3.3 | Recipe step UI redesign: per-switch repeat count, auxiliary switches in machine settings |
| v0.3.4–v0.3.5 | Friendly names as labels/descriptions for auxiliary switch count fields |
| v0.3.6 | Fix View Selected Recipe / `get_recipe` for switch steps |
| v0.3.7 | Fix aux switch repeat: listener registered before `turn_on` |
| v0.3.8 | Fix "Change Drink to None": `"none"` sentinel |
| v0.3.9–v0.3.15 | Fix momentary-switch repeat reliability (beta diagnostic+fix cycle) |
| v0.3.16 | Stable aux switch repeat fix; demote `[CRM]` diagnostic logs to DEBUG |
| v0.3.17 | Edit Recipes button (deep-link to config); fix `drink: none` display |
