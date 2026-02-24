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

---

## 🟡 v0.3.x — Recipe Capabilities

### ✅ v0.3.0 — Direct switch steps & reliable completion tracking *(released 2026-02-24)*

- **Direct switch steps** — Recipe steps can now activate a switch entity
  directly (e.g. `switch.coffee_machine_milkfrothing`,
  `switch.coffee_machine_hotwaterdispensing`,
  `switch.coffee_machine_espressoshot`) without going through the drink
  select flow.

- **Start switch completion tracking** — `_wait_for_completion` now monitors
  the `machine_start_switch` entity (ON → OFF cycle) instead of the
  `machine_work_state` sensor. More reliable, polling-independent, and works
  uniformly for both drink and switch steps.

---

### ✅ v0.3.1 — Switch steps in the recipe UI *(released 2026-02-24)*

- **Step type selector in the recipe form** — The Add and Edit recipe step
  forms now have a `Drink` / `Switch` selector. When `Switch` is chosen, a
  text field accepts any switch entity ID with live validation. Existing switch
  steps pre-fill correctly when editing.

---

### ✅ v0.3.2 — Switch entity dropdown + multiple switches per step *(released 2026-02-24)*

- **Entity selector dropdown** — `switch_entities` is now a proper HA entity
  picker filtered to `switch` domain.
- **Multiple switches per step** — Select several switches in one step;
  they execute sequentially with fault monitoring between each one.
  YAML: `switches: [entity1, entity2]` (old `switch: entity` still works).
- **Fix raw label names** — `step_type` and `switch_entity` now display
  their proper translated labels.

---

### ✅ v0.3.3 — Recipe step UI redesign + auxiliary switch settings *(released 2026-02-24)*

- **Auxiliary switches in machine settings** — Configured once
  (`auxiliary_switches`) in the initial setup wizard and Machine Settings
  options. No longer entered per step.
- **No more Step type selector** — The `Drink` / `Switch` radio removed.
  Every step form shows: Drink dropdown (with *— None —* to skip), Double
  toggle, one **× count** number field per configured auxiliary switch
  (0 = skip, 1–10 = repeat that many times).
- **Per-switch repeat count** — Each auxiliary switch can be triggered N
  times per step, each run with full fault monitoring.
- **Executor `switch_counts` format** — New YAML/storage format
  `switch_counts: {entity_id: N}`. Old `switch:` and `switches:` still work.

---

### ✅ v0.3.4 — Friendly names for auxiliary switch fields *(released 2026-02-24)*

- **Auxiliary switch friendly names in recipe step form** — The `Switch 0 (×)`,
  `Switch 1 (×)`, `Switch 2 (×)` fields now display the entity's **friendly name**
  as a description below each field (e.g. "Coffee Machine Milkfrothing").
  Fallback: entity ID last segment prettified if the entity isn't loaded yet.

---

### ✅ v0.3.5 — Friendly names as field labels *(released 2026-02-24)*

- **Labels renamed to friendly names** — The field label itself (not just the
  description below) now shows the entity friendly name, e.g.
  `Coffee Machine Milkfrothing (×)` instead of `Switch 0 (×)`.

---

### ✅ v0.3.6 — Fix View Selected Recipe for all step types *(released 2026-02-24)*

- **View Selected Recipe button and `get_recipe` service** now correctly render
  all step types: drink steps, `switch_counts` (new format), legacy `switches`
  list, legacy `switch` single entity, and combined drink + switch steps.
  Friendly names resolved from `hass.states`. Previously crashed on non-drink steps.

---

### 4. Fault wait timeout (`max_fault_wait`)
Currently the integration waits forever when a fault occurs.  
Add configurable `max_fault_wait` (minutes, default: 30).  
If the fault is not resolved within the timeout → abort recipe + send notification.

Config option in Options Flow → Machine settings.

---

### 5. Brew counter sensor
Track how many times each recipe has been brewed.  
Store in `hass.storage` (persistent).  
Expose as `sensor.coffee_brew_count` with per-recipe breakdown in attributes:
```
total: 42
recipes:
  morning_boost: 18
  macchiato_americano: 24
```
Useful for: statistics, filter replacement reminders, automations.

---

### 6. Schedule / auto-brew
Allow scheduling a recipe at a specific time directly from the integration,  
without needing manual automations.

UI: Options Flow → new "Schedule" menu  
- Select recipe  
- Set time (HH:MM)  
- Days of week (Mon–Sun checkboxes)  
- Enable/disable toggle

Internally creates a time-based automation via `hass.services`.

---

## 🔴 v0.4.x — Advanced Features

### 7. Retry limit for faults
Related to #4. Add `max_fault_retries` — if the same fault triggers  
more than N times during a single recipe run → abort instead of resuming.  
Prevents infinite loops on hardware failures.

---

### 8. Recipe import / export
- `export_recipes` service → writes a downloadable YAML/JSON  
  to HA config dir (e.g. `coffee_recipes_export.yaml`)
- `import_recipes` service → reads from a specified file path,  
  merges or overwrites existing recipes
- UI button in Options Flow → "Export all recipes"

---

### 9. Multi-machine support
Currently `_get_first_entry_id()` always picks the first configured machine.  
Refactor services to accept an optional `device_id` parameter  
so users with multiple machines can target each independently:
```yaml
service: coffee_recipe_manager.brew_recipe
data:
  recipe_name: morning_boost
  device_id: abc123  # optional, defaults to first machine
```

---

## 🚀 v1.0.x — Custom UI

### 10. Custom Lovelace card
A JavaScript Lovelace card (`www/coffee-recipe-card.js`) with:
- Full recipe list with click-to-expand details
- Inline recipe editor (name, description, add/remove/reorder steps)
- Brew button per recipe
- Live status display (current step, progress bar)

Built with LitElement (same framework HA uses for its own cards).  
Registered automatically by the integration — no manual resource setup.

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
| v0.2.0 | Richer status sensor (step drink, last_completed_at, brew_count), persistent brew stats, drink validation |
| v0.2.1 | Integration icon added to HACS (`hacs.json`), icon submitted to home-assistant/brands |
| v0.2.2 | Restore `icon.png` and `icon@2x.png` |
| v0.2.3 | Fix premature recipe completion and skipped steps (two-stage completion wait) |
| v0.2.4 | Fix drink name case mismatch, fix `machine_double_switch` not truly optional, add detailed debug logging |
| v0.3.0 | Direct switch steps in recipes (`switch:` field), completion tracking via start switch instead of work state sensor |
| v0.3.1 | Switch step type added to the recipe UI (Add / Edit flows) |
| v0.3.2 | Switch entity dropdown (EntitySelector), multiple switches per step, fix raw label names |
| v0.3.3 | Recipe step UI redesign: remove Step type, per-switch repeat count, auxiliary switches moved to machine settings |
| v0.3.4 | Show entity friendly names under auxiliary switch count fields in recipe step form |
| v0.3.5 | Use friendly names as field labels (not just descriptions) for auxiliary switch count fields |
| v0.3.6 | Fix View Selected Recipe / get_recipe service to correctly render switch steps and switch_counts format |
