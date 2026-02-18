# ☕ Coffee Recipe Manager

A Home Assistant custom integration for brewing custom multi-step coffee recipes on Beko/Miele/Jura/similar smart coffee machines.

## Features

- 🧾 Define recipes with multiple steps (e.g. Macchiato → Americano)
- 🛡️ Fault monitoring — stops recipe if water/milk/container fault detected
- 📱 Notifications — persistent HA notification + optional mobile push
- 🖥️ Config Flow — full UI setup, no YAML editing required for setup
- 📝 Recipes stored in `coffee_recipes.yaml` in your HA config directory
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

## Recipes

Recipes are stored in `<ha_config>/coffee_recipes.yaml`. An example file is created automatically on first run:

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

### Status attributes
- `recipe_name` — currently running recipe
- `current_step` / `total_steps` — progress
- `error` — error message if status is `error`
- `last_recipe` — last successfully completed recipe

## Fault Handling

If any fault sensor turns `on` during brewing:
1. Recipe stops immediately
2. Persistent notification appears in HA
3. Mobile push sent (if configured)
4. `sensor.coffee_recipe_status` → `error` with fault description

After you fix the fault, you can restart the recipe manually.

## Notes

- Only one recipe can run at a time. Starting a new one aborts the current.
- The integration checks for faults **before** each step and **during** brewing.
- `timeout` per step defaults to 300s (5 min). Adjust for slow machines.
