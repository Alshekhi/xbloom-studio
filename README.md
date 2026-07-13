# xBloom Studio for Home Assistant

**Unofficial**, local-only [Home Assistant](https://www.home-assistant.io/) custom integration for the **xBloom Studio** coffee machine, communicating over Bluetooth Low Energy (BLE).

It gives you full control of the machine from Home Assistant — brew monitoring, recipe management, and standalone grinder / brewer / scale control — as entities, services, and automation blueprints. No cloud account, no polling; the machine is contacted over BLE on demand and released again so the official iOS app can still connect.

## Features

- **Live brew monitoring** — brew status, machine status, scale weight, and per-pour progress stream over BLE while a brew is running.
- **Recipe library** — store recipes locally in Home Assistant, import them from an xBloom share link, and create / edit / delete them from the integration's options flow.
- **One-tap brewing** — start, pause, resume, or cancel a brew; brew with pre-ground coffee; write a recipe to one of the machine's on-device slots.
- **Standalone control** — run the grinder or brewer on their own, tare the scale, switch water source, and change on-screen units.
- **Announcement blueprints** — ready-made automation blueprints that speak brew progress, live-control feedback, and machine faults through any TTS or notify service (e.g. Alexa).

## Requirements

- Home Assistant **2025.x** or newer.
- A Bluetooth adapter local to your Home Assistant host, **or** an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) within range of the machine. The integration routes through Home Assistant's built-in Bluetooth so either works.
- The xBloom Studio powered on and in BLE range during setup and while sending commands.

## Installation

### HACS (recommended)

This repository is installed as a HACS **custom repository**:

1. In Home Assistant, open **HACS**.
2. Open the menu (three dots, top right) → **Custom repositories**.
3. Add the URL `https://github.com/Alshekhi/xbloom-studio` and choose the category **Integration**.
4. Install **xBloom Studio**, then restart Home Assistant.

### Manual

Copy `custom_components/xbloom/` into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

## Configuration

With the machine powered on and in range, Home Assistant discovers it automatically over Bluetooth (it advertises as `XBLOOM …`). You will see a discovered device under **Settings → Devices & Services** — confirm it to finish setup. If it is not discovered, use **Add Integration → xBloom Studio**.

Recipes are managed after setup from the integration's **Configure** (options) menu: add from an xBloom share URL or share ID, or create, edit, and delete recipes by hand. The **Recipe** select entity always reflects the current local library.

## Entities

- **Sensors** — Brew Status, Machine Status, Scale Weight, and live readings: Current Recipe, Current Pour, Current Module, Grind Size, Grind Speed, Pour Pattern, Brew Temperature, Brew Ratio, Last Recipe Card.
- **Event** — Brew Event, fired for brew lifecycle changes (useful as an automation trigger).
- **Selects** — Recipe, Mode (auto / pro), Water Source (tank / tap), Temperature Unit (°C / °F), Weight Unit (g / oz / ml), Brew Pattern.
- **Numbers** — Grind Size, Grind Speed, Brew Volume, Brew Temperature, Brew Flow Rate.
- **Buttons** — Start Brew, Cancel Brew, Pause Brew, Resume Brew, Tare Scale, Back to Home, Grind, Brew (standalone), Refresh Recipes, plus BLE Connect / BLE Disconnect diagnostics.
- **Switches** — Use Grinder, Live Control.

## Services

The integration registers services under the `xbloom.` domain. Highlights:

- Brewing: `start_brew`, `stop_brew`, `brew_pause`, `brew_resume`, `brew_standalone`, `write_slot`.
- Machine control: `grind`, `tare`, `back_to_home`, `set_mode`, `set_water_source`, `set_temp_unit`, `set_weight_unit`.
- Recipe library: `list_recipes`, `get_recipe`, `add_recipe`, `update_recipe`, `delete_recipe`.
- Diagnostics: `ble_connect`, `ble_disconnect`, `dump_notifications`.

Each service, its parameters, and its BLE command are documented in `custom_components/xbloom/services.yaml` and appear in **Developer Tools → Actions**.

## Blueprints

Three automation blueprints live in `blueprints/automation/xbloom/`:

- `brew_announce.yaml` — announces brew progress and completion.
- `live_control_announce.yaml` — speaks feedback while you adjust the machine.
- `machine_fault_announce.yaml` — announces machine faults.

They target any TTS or notify service, so they work with Alexa, Google, or a local speaker. Import them from **Settings → Automations & Scenes → Blueprints → Import Blueprint** using the raw file URL, or copy them into your `config/blueprints/automation/` directory.

## Disclaimer

This is an unofficial, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. It talks to the machine over its local BLE protocol, which may change with firmware updates. Use at your own risk.

## License

Released under the [MIT License](LICENSE).
