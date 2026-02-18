# ☕ Coffee Recipe Manager

A Home Assistant custom integration for brewing custom multi-step coffee recipes on Beko/Miele/Jura/similar smart coffee machines.

## Features

- 🧾 Define recipes with multiple steps (e.g. Macchiato → Americano)
- 🗂️ Manage recipes directly from the HA UI — no YAML editing required
- 🛡️ Fault monitoring — pauses recipe and **auto-resumes** after fault is cleared
- 📱 Notifications — persistent HA notification + optional mobile push
- 🖥️ Config Flow — full UI setup, no YAML editing required for setup
- 📝 Recipes also editable via `coffee_recipes.yaml` in your HA config directory
- 🎛️ Device page controls — Select Recipe dropdown + Brew/Abort buttons
- 🔧 HACS compatible

## Installation via HACS

1. Open HACS in Home Assistant
2. Go to **Integrations** → click the three-dot menu → **Custom repositories**
3. Add this repository URL and select category **Integration**
4. Click **Download**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration**
7. Search for **Coffee Recipe Manager**

## Setup

The config flow will guide you through 3 steps:

1. **Machine entities** — select your drink selector, start switch, and work state sensor
2. **Fault sensors** — select all binary sensors that indicate machine errors
3. **Notifications** — optional mobile push service + recipes file name

## Managing Recipes via UI

Go to **Settings → Devices & Services → Coffee Recipe Manager → Configure**.

The options menu has two sections:

### Machine settings
Update machine entities, fault sensors, and notification service.

### Manage recipes

Three actions are available:

#### ➕ Add new recipe

1. Click **Configure** on the integration card
2. Choose **Manage recipes → Add new recipe**
3. Fill in:
   - **Recipe name** — human-readable name (e.g. `Morning Boost`)
   - **Description** — optional
   - **Steps** — list of steps in YAML/object format:

```yaml
- drink: LatteMacchiato
  double: false
  timeout: 300
- drink: Americano
  double: false
  timeout: 300
```

4. Click **Submit** — the recipe is saved immediately

The recipe key (used in automations) is auto-generated from the name, e.g. `Morning Boost` → `morning_boost`.

#### ✏️ Edit recipe

1. Choose **Manage recipes → Edit recipe**
2. Select the recipe from the dropdown
3. Modify name, description, or steps
4. Click **Submit**

#### 🗑️ Delete recipe

1. Choose **Manage recipes → Delete recipe**
2. Select the recipe to remove
3. Click **Submit** — permanently deleted from the YAML file

---

## Recipes via YAML

Recipes are also editable directly in `<ha_config>/coffee_recipes.yaml`. An example file is created automatically on first run:

```yaml
recipes:
  macchiato_americano:
    name: "Macchiato + Americano"
    description: "Double macchiato followed by americano"
    steps:
      - drink: LatteMacchiato
        double: false
        timeout: 300
      - drink: Americano
        double: false
        timeout: 300
```

### Available drink options (Miele example)
`Espresso`, `Americano`, `CafeLatte`, `LatteMacchiato`, `Ristretto`, `Doppio`, `EspressoMacchiato`, `RistrettoBianco`, `FlatWhite`, `Cortado`, `IcedAmericano`, `IcedLatte`, `Hotwater`, `HotMilk`, `TravelMug`, `Cappuccino`

## Services

| Service | Description |
|---------|-------------|
| `coffee_recipe_manager.brew_recipe` | Start a recipe by key name |
| `coffee_recipe_manager.abort_recipe` | Abort current recipe |
| `coffee_recipe_manager.reload_recipes` | Reload YAML after manual edits |
| `coffee_recipe_manager.add_recipe` | Add/update recipe via service call |
| `coffee_recipe_manager.delete_recipe` | Delete a recipe by key |
| `coffee_recipe_manager.list_recipes` | Show all recipes with keys in a notification |
| `coffee_recipe_manager.get_recipe` | Show full details of one recipe in a notification |

### Managing recipes via Services

Useful from **Developer Tools → Actions** or in automations/scripts:

```yaml
# 1. See all available recipe keys
service: coffee_recipe_manager.list_recipes

# 2. See full steps of a specific recipe
service: coffee_recipe_manager.get_recipe
data:
  recipe_name: morning_boost

# 3. Add or update a recipe
service: coffee_recipe_manager.add_recipe
data:
  name: "Morning Boost"
  description: "Quick start"
  steps:
    - drink: Espresso
      double: false
      timeout: 120
    - drink: Americano
      double: false
      timeout: 300

# 4. Delete a recipe
service: coffee_recipe_manager.delete_recipe
data:
  recipe_name: morning_boost
```

### Example automation

```yaml
automation:
  - alias: "Morning coffee"
    trigger:
      - platform: time
        at: "07:30:00"
    action:
      - service: coffee_recipe_manager.brew_recipe
        data:
          recipe_name: macchiato_americano
```

## Entities

| Entity | Description |
|--------|-------------|
| `sensor.coffee_recipe_status` | Current status: `idle`, `running`, `completed`, `error` |
| `select.coffee_recipe_select_recipe` | Dropdown to pick which recipe to brew |
| `button.coffee_recipe_brew_selected_recipe` | Brew the currently selected recipe |
| `button.coffee_recipe_view_selected_recipe` | Show selected recipe details in a notification |
| `button.coffee_recipe_abort_recipe` | Abort the current recipe |

### Status sensor attributes
- `recipe_name` — currently running recipe
- `current_step` / `total_steps` — step progress
- `current_step_drink` — drink being prepared right now (e.g. `LatteMacchiato`)
- `last_recipe` — name of last completed recipe
- `last_completed_at` — ISO timestamp of last completion (persisted across restarts)
- `brew_count` — dict of how many times each recipe was brewed (persisted)
- `error` — error message if status is `error`

### How to view sensor attributes

**Option 1 — Developer Tools:**
Go to **Developer Tools → States**, search for `coffee_recipe_status` — all attributes are listed there.

**Option 2 — Dashboard card:**
Add a Markdown card to any dashboard:
```yaml
type: markdown
content: |
  ## ☕ Coffee Recipe Manager
  **Status:** {{ states('sensor.coffee_recipe_manager_recipe_status') }}
  **Recipe:** {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'recipe_name') }}
  **Step:** {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'current_step') }} / {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'total_steps') }}
  **Now brewing:** {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'current_step_drink') }}
  **Last brew:** {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'last_recipe') }} at {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'last_completed_at') | as_datetime | as_local }}
  **Brew counts:** {{ state_attr('sensor.coffee_recipe_manager_recipe_status', 'brew_count') }}
```

**Option 3 — Automation condition (example):**
```yaml
condition:
  - condition: template
    value_template: >
      {{ (now() - state_attr('sensor.coffee_recipe_manager_recipe_status', 'last_completed_at') | as_datetime)
         .total_seconds() > 1800 }}
```

## Fault Handling

If any fault sensor turns `on` during brewing (e.g. water empty, tray full):

1. Recipe **pauses** immediately
2. `sensor.coffee_recipe_status` → `waiting_fault_clear`
3. Persistent notification appears in HA: ⚠️ *Recipe paused — fix the issue and brewing will resume automatically*
4. Mobile push sent (if configured)

Once the fault is resolved (sensor turns `off`):

1. Integration detects the change automatically
2. Waits 2 seconds for the machine to stabilise
3. **Restarts the current step** from the beginning (re-selects drink, re-starts machine)
4. Sends a ✅ *Fault resolved. Resuming recipe...* notification
5. `sensor.coffee_recipe_status` → `running`

> You can call `coffee_recipe_manager.abort_recipe` at any time to cancel instead of waiting.

## Notes

- Only one recipe can run at a time. Starting a new one aborts the current.
- The integration checks for faults **before** each step and **during** brewing.
- `timeout` per step defaults to 300s (5 min). Adjust for slow machines.
