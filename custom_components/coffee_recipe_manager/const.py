"""Constants for Coffee Recipe Manager."""

DOMAIN = "coffee_recipe_manager"
VERSION = "0.2.4"

# Config keys
CONF_MACHINE_DRINK_SELECT = "machine_drink_select"
CONF_MACHINE_START_SWITCH = "machine_start_switch"
CONF_MACHINE_WORK_STATE = "machine_work_state"
CONF_MACHINE_DOUBLE_SWITCH = "machine_double_switch"
CONF_FAULT_SENSORS = "fault_sensors"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_RECIPES_FILE = "recipes_file"
CONF_DRINK_OPTIONS = "drink_options"

# Defaults
DEFAULT_DRINK_SELECT = "select.coffee_machine_drink_set"
DEFAULT_START_SWITCH = "switch.coffee_machine_start"
DEFAULT_WORK_STATE = "sensor.coffee_machine_work_state"
DEFAULT_DOUBLE_SWITCH = "switch.coffee_machine_double"
DEFAULT_STANDBY_STATE = "standby"
DEFAULT_STEP_TIMEOUT = 300  # seconds
DEFAULT_START_TIMEOUT = 15  # seconds to wait for machine to leave standby after start command
DEFAULT_RECIPES_FILE = "coffee_recipes.yaml"

DEFAULT_FAULT_SENSORS = [
    "binary_sensor.coffee_machine_fault_water_empty",
    "binary_sensor.coffee_machine_fault_residual_full",
    "binary_sensor.coffee_machine_fault_milkcup_missing",
    "binary_sensor.coffee_machine_fault_trashcan_misplaced",
    "binary_sensor.coffee_machine_fault_watertank_misplaced",
    "binary_sensor.coffee_machine_fault_blocking",
    "binary_sensor.coffee_machine_fault_heating_fault",
    "binary_sensor.coffee_machine_fault_milkcup_missing",
    "binary_sensor.coffee_machine_fault_nic_fault",
]

DRINK_OPTIONS = [
    "Espresso",
    "Americano",
    "CafeLatte",
    "LatteMacchiato",
    "Ristretto",
    "Doppio",
    "EspressoMacchiato",
    "RistrettoBianco",
    "FlatWhite",
    "Cortado",
    "IcedAmericano",
    "IcedLatte",
    "Hotwater",
    "HotMilk",
    "TravelMug",
    "Cappuccino",
]

# Recipe executor states
EXECUTOR_IDLE = "idle"
EXECUTOR_RUNNING = "running"
EXECUTOR_WAITING_FAULT_CLEAR = "waiting_fault_clear"
EXECUTOR_ERROR = "error"
EXECUTOR_COMPLETED = "completed"

# Services
SERVICE_BREW_RECIPE = "brew_recipe"
SERVICE_ABORT_RECIPE = "abort_recipe"

# Events
EVENT_RECIPE_STARTED = f"{DOMAIN}_recipe_started"
EVENT_RECIPE_COMPLETED = f"{DOMAIN}_recipe_completed"
EVENT_RECIPE_FAILED = f"{DOMAIN}_recipe_failed"
EVENT_STEP_STARTED = f"{DOMAIN}_step_started"

# Attributes
ATTR_RECIPE_NAME = "recipe_name"
ATTR_CURRENT_STEP = "current_step"
ATTR_TOTAL_STEPS = "total_steps"
ATTR_STATUS = "status"
ATTR_ERROR = "error"
ATTR_LAST_RECIPE = "last_recipe"
ATTR_CURRENT_STEP_DRINK = "current_step_drink"
ATTR_LAST_COMPLETED_AT = "last_completed_at"
ATTR_BREW_COUNT = "brew_count"

# Persistent storage
BREW_STATS_STORE_KEY = f"{DOMAIN}.brew_stats"
BREW_STATS_STORE_VERSION = 1
