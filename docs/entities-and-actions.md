# Entities and actions

## Entities

- **Sensors** — Brew Status, Machine Status, Scale Weight, Brew Time, and live readings: Current Recipe, Current Pour, Current Module, Grind Size, Grind Speed, Pour Pattern, Brew Temperature, Brew Ratio, Last Recipe Card, Status Updated.
- **Binary sensors** — In Range: on while Home Assistant's Bluetooth can see the machine, off once it drops it. The status sensors keep the last thing the machine reported, so this is the one that says a machine switched off is gone. Recipe Ready: on while the machine holds the picked recipe, ready to start at once. Brew Paused: on while a brew is paused, from Home Assistant or at the machine. See [Brewing](brewing.md).
- **Event** — Brew Event, fired on brew lifecycle changes (useful as an automation trigger).
- **Selects** — Recipe, Recipe Action, Archived Recipe, Mode (auto / pro), Water Source (tank / tap), Temperature Unit (°C / °F), Weight Unit (g / oz / ml), Brew Pattern.
- **Numbers** — Grind Size, Grind Speed, Brew Volume, Brew Temperature, Brew Flow Rate, and the brew-customizer overrides: Brew Dose, Brew Ratio, Brew Grind Size.
- **Text** — New Recipe Name (used by the brew customizer's Save as New Recipe).
- **Buttons** — Start Brew, Cancel Brew, Pause Brew, Resume Brew, Cancel Preparation, Tare Scale, Back to Home, Grind, Brew (standalone), Refresh Recipes, Save as New Recipe, Run Recipe Action, Restore Archived Recipe, Delete Selected Recipe, plus BLE Connect / BLE Disconnect diagnostics.
- **Switches** — Use Grinder, Connect (opens a live session that holds the BLE link and streams machine events for sensors, the dashboard, and optional spoken announcements).
- **Update** — Firmware (installed vs latest, with an Install button; available when signed in to the xBloom cloud).

## Services

The integration registers its services under the `xbloom.` domain:

- **Brewing** — `prepare_brew`, `cancel_preparation`, `start_brew`, `stop_brew`, `brew_pause`, `brew_resume`, `brew_standalone`, `write_slot`.
- **Machine control** — `grind`, `tare`, `back_to_home`, `set_mode`, `set_water_source`, `set_temp_unit`, `set_weight_unit`.
- **Recipe library** — `list_recipes`, `get_recipe`, `build_recipe`, `add_recipe`, `update_recipe`, `delete_recipe`, `save_scaled_recipe`, `archive_recipe`, `restore_recipe`, `list_archived_recipes`.
- **Diagnostics** — `ble_connect`, `ble_disconnect`, `refresh_status`.

Each service, its fields, and examples appear in **Developer Tools → Actions**, and are documented in `custom_components/xbloom/services.yaml`.
