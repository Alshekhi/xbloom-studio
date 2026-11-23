# Entities and actions

## Entities

- **Sensors** — Brew Status, Brew Stage (pouring, waiting between pours, or draining after the last; waits are known when Home Assistant started or prepared the brew), Next Pour (when the next pour starts, while waiting), Brew Story (during a brew, a line about the pour under way in `now`, and a story about the coffee in `story`: its bag, coffee's history, or how brewing works, ending on a teaser for the next cup), Machine Status, Scale Weight, Brew Time, Water Poured (the water the brew in progress has poured, in ml, with the recipe's beside it when Home Assistant started or prepared the brew), and live readings: Current Recipe, Current Pour, Current Module, Grind Size, Grind Speed, Pour Pattern, Brew Temperature, Brew Ratio, Last Recipe Card, Status Updated.
- **Binary sensors** — In Range: on while Home Assistant's Bluetooth can see the machine, off once it drops it. The status sensors keep the last thing the machine reported, so this is the one that says a machine switched off is gone. Recipe Ready: on while the machine holds the picked recipe, ready to start at once. Machine Status carries `water_left_ml`, `water_needed_ml` and `water_enough_to_finish` while a brew's low-water switch has tripped; see [Events](events.md). Brew Paused: on while a brew is paused, from Home Assistant or at the machine, or waiting for the tank to be refilled; its `reason` is `water` then. See [Brewing](brewing.md).
- **Event** — Brew Event, fired on brew lifecycle changes (useful as an automation trigger).
- **Selects** — Recipe, Recipe to Manage (archive or delete it; picking one never prepares the machine), Archived Recipe, Mode (auto / pro), Water Source (tank / tap), Temperature Unit (°C / °F), Weight Unit (g / oz / ml), Brew Pattern, Taste (balanced / less sour / less bitter: moves Brew Grind Size from the picked recipe's), Brew Stories (off / built-in / agent: an AI task chosen in Configure → Brew stories writes each brew's stories, one request when the brew starts; pour lines stay built-in, and a brew the AI task does not answer shows pour lines only), Story language (English / Arabic: the language the next brew's stories are told in; until one is picked, Home Assistant's language if it is one of these, otherwise English).
- **Numbers** — Grind Size, Grind Speed, Brew Volume, Brew Temperature, Brew Flow Rate, and the brew-customizer overrides: Brew Dose, Brew Ratio, Brew Grind Size.
- **Text** — New Recipe Name (used by the brew customizer's Save as New Recipe), Community Search.
- **Community** — Browse (which list the Community tab shows), Community Search, Community Origin, Community Sort, Community Recipe, Community Matches, and the Search, Suggest and Add Community Recipe buttons; for the Brew tab, Drink (any / hot / iced), Suggest Recipe, Suggested Recipe and Use Suggested Recipe; signed in to the xBloom account, For You, Trending Recipes, Tea Recipes, Another For You, their Add buttons, and Show xPod Recipes. See [Recipes](recipes.md#community-recipes).
- **Coffee Lab** — while it is on, Coffee bag, xPod box and Tea, Recipe kind, and the counting, rating, version and suggestion entities. See [Coffee Lab](coffee-lab.md).
- **Buttons** — Start Brew, Cancel Brew, Pause Brew, Resume Brew, Cancel Preparation, Tare Scale, Back to Home, Grind, Brew (standalone), Refresh Recipes, Save as New Recipe, Archive Recipe, Archive and Remove from xBloom Cloud, Delete Recipe, Restore Archived Recipe, plus BLE Connect / BLE Disconnect diagnostics.
- **Switches** — Use Grinder, Connect (opens a live session that holds the BLE link and streams machine events for sensors, the dashboard, and optional spoken announcements). Machine Control: off, every action that starts, prepares or changes something on the machine is refused; stopping, pausing, cancelling, disconnecting and all recipe work still run.
- **Update** — Firmware (installed vs latest, with an Install button; available when signed in to the xBloom cloud).

## Services

The integration registers its services under the `xbloom.` domain:

- **Brewing** — `prepare_brew`, `cancel_preparation`, `start_brew`, `stop_brew`, `brew_pause`, `brew_resume`, `brew_standalone`, `write_slot`.
- **Machine settings and modules** — `grind`, `tare`, `back_to_home`, `set_mode`, `set_water_source`, `set_temp_unit`, `set_weight_unit`.
- **Recipe library** — `list_recipes`, `get_recipe`, `build_recipe`, `add_recipe`, `update_recipe`, `delete_recipe`, `save_scaled_recipe`, `archive_recipe`, `restore_recipe`, `list_archived_recipes`.
- **Community hub** — `search_community`, `get_community_recipe`, `suggest_community`; signed in to the xBloom account, `xbloom_picks`; and `save_shared_recipe`, for any xBloom share link.
- **Coffee Lab**, while it is on — `add_bean`, `update_bean`, `set_active_bean`, `consume`, `start_tracking`, `finish_bag`, `rate_brew`.
- **Diagnostics** — `ble_connect`, `ble_disconnect`, `refresh_status`.

Each service, its fields, and examples appear in **Developer Tools → Actions**, and are documented in `custom_components/xbloom/services.yaml`.
