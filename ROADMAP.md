# 🗺️ Coffee Recipe Manager — Roadmap

## 🟢 v0.2.x — Quick Wins

### 1. Richer recipe status sensor
Add useful attributes to `sensor.coffee_recipe_status`:
- `current_step_drink` — drink being prepared right now
- `current_step_number` / `total_steps` — step progress (e.g. `2 / 3`)
- `last_completed_recipe` — name of last successfully brewed recipe
- `last_completed_at` — timestamp of last completion

Enables dashboard cards like:
```
☕ Running: LatteMacchiato  (step 1 of 3)
```

---

### 2. `last_completed` persistent storage
Store the last completed recipe name + timestamp in `hass.storage`  
(survives HA restarts). Useful for automations:
```yaml
condition:
  - condition: template
    value_template: >
      {{ (now() - state_attr('sensor.coffee_recipe_status', 'last_completed_at'))
         .total_seconds() > 1800 }}
```

---

### 3. Drink validation on recipe save
When saving a recipe (via UI flow or service), warn if a step contains  
a drink not present in the configured `drink_options` for this machine.  
Show an error in the flow instead of silently saving an invalid recipe.

---

## 🟡 v0.3.x — Mid-complexity Features

### 4. Fault wait timeout (max_fault_wait)
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
