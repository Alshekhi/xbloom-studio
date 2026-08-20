# xBloom Studio for Home Assistant

A community-built, local-first [Home Assistant](https://www.home-assistant.io/) integration for the **xBloom Studio** coffee machine. It talks to the machine directly over Bluetooth Low Energy (BLE) and turns it into ordinary Home Assistant entities, services, and automation blueprints, so you can brew, monitor, and manage recipes from a dashboard, an automation, or your voice.

Two ideas drove it, equally:

- **Local control.** Brewing and machine control run entirely over BLE, on your own hardware. No cloud account is required, and nothing depends on xBloom's servers to make coffee. Home Assistant contacts the machine only when it needs to and releases it again afterwards, so the official iOS app keeps working alongside it.
- **Accessibility.** The machine is driven by three physical knobs and gives no spoken feedback, and the official app isn't accessible to screen readers, so a blind or low-vision owner can't really tell what the machine is doing or drive it independently. Exposing it as Home Assistant entities, with spoken announcements for brew progress, live feedback, and faults through any TTS or notify service, makes the xBloom legible and operable by keyboard, screen reader, and voice.

An **optional** xBloom account adds cloud recipe sync and a firmware-update check on top. Everything else works without it.

> ⚠️ **Not affiliated with xBloom.** This is an independent, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. It communicates with the machine over its local BLE protocol, worked out for interoperability, which may change with firmware updates. Use at your own risk.

## Features

- **Live brew monitoring** — brew status, machine status, scale weight, and per-pour progress stream over BLE while a brew runs.
- **Recipe library** — keep recipes locally in Home Assistant, import them from an xBloom share link, and create, edit, or delete them from the integration's Configure menu.
- **Brew customizer** — scale a saved recipe on the fly (dose, ratio, grind size) for a one-off brew, or save the scaled result as a brand-new recipe.
- **Optional cloud sync** — sign in with your xBloom account to make the cloud the home for your recipes. Your account's recipes appear in Home Assistant (both your own and ones you saved from shared links, tagged with a `shared` attribute), and create/edit/delete write straight back to the cloud, so they show up in the iOS app too. On first sign-in, choose to upload your existing local recipes or discard them. Sign out any time to fall back to the local library.
- **Firmware update** *(cloud + Bluetooth)* — when signed in, a Firmware entity compares the machine's installed firmware (read over Bluetooth) against the latest version xBloom publishes, with release notes. Pressing **Install** downloads the firmware from xBloom, verifies its MD5, and flashes it over Bluetooth, acknowledged block by block and verified byte-for-byte against a real captured update. ⚠️ Firmware flashing is inherently risky: a dropped Bluetooth link mid-update can brick the machine. Keep it close and powered, and don't flash while brewing. It's off until you enable it in the Configure menu.
- **One-tap brewing** — start, pause, resume, or cancel a brew; brew with pre-ground coffee; write a recipe to one of the machine's on-device slots.
- **Standalone control** — run the grinder or brewer on their own, tare the scale, switch water source, and change the machine's on-screen units.
- **Announcement blueprints** — ready-made blueprints that speak brew progress, live-control feedback, and machine faults through any TTS or notify service (Alexa, Google, or a local speaker).

## Requirements

- Home Assistant **2025.1** or newer.
- A Bluetooth adapter on your Home Assistant host, **or** an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) within range of the machine. The integration goes through Home Assistant's built-in Bluetooth, so either works.
- The xBloom Studio powered on and in Bluetooth range during setup and while sending commands.

## Installation

### HACS (recommended)

Install it as a HACS **custom repository**:

1. In Home Assistant, open **HACS**.
2. Open the menu (three dots, top right) → **Custom repositories**.
3. Add the URL `https://github.com/Alshekhi/xbloom-studio` and choose the category **Integration**.
4. Install **xBloom Studio**, then restart Home Assistant.

### Manual

Copy `custom_components/xbloom/` into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

## Setup

With the machine powered on and in range, Home Assistant discovers it automatically over Bluetooth (it advertises as `XBLOOM …`). A discovered device appears under **Settings → Devices & Services**; confirm it to finish setup. If it isn't discovered, use **Add Integration → xBloom Studio** and pick it from the list or type its BLE name.

Recipes are managed after setup from the integration's **Configure** menu: add one from an xBloom share link, or create, edit, and delete recipes by hand. The **Recipe** select entity always reflects the current library.

### Optional: xBloom cloud sign-in

The same **Configure** menu has **Sign in to xBloom cloud**. Sign in with your xBloom account to sync recipes: once signed in, the cloud becomes the home for your recipes and every create, edit, and delete is written back to your account. If you already have local recipes, you'll be asked whether to upload them or discard them.

Tick **Remember my credentials** to store your password locally (in `.storage`, next to the session token) so the session refreshes itself when the token expires. It's only ever sent to xBloom's sign-in endpoint. Leave it unticked for more privacy: only the token is kept, and you'll be prompted to sign in again when it expires. Use **Sign out of xBloom cloud** to clear everything and return to the local library (your synced recipes stay cached locally). The cloud is entirely optional; leaving it out keeps the integration BLE-only.

Recipe sync is event-driven, not polled: changes you make in Home Assistant apply immediately, and the Configure recipe lists pull fresh from the cloud each time you open them. A recipe you added or edited on your phone shows up in the dashboard dropdowns after you press the **Refresh Recipes** button.

## Entities

- **Sensors** — Brew Status, Machine Status, Scale Weight, and live readings: Current Recipe, Current Pour, Current Module, Grind Size, Grind Speed, Pour Pattern, Brew Temperature, Brew Ratio, Last Recipe Card, Status Updated.
- **Event** — Brew Event, fired on brew lifecycle changes (useful as an automation trigger).
- **Selects** — Recipe, Mode (auto / pro), Water Source (tank / tap), Temperature Unit (°C / °F), Weight Unit (g / oz / ml), Brew Pattern.
- **Numbers** — Grind Size, Grind Speed, Brew Volume, Brew Temperature, Brew Flow Rate, and the brew-customizer overrides: Brew Dose, Brew Ratio, Brew Grind Size.
- **Text** — New Recipe Name (used by the brew customizer's Save as New Recipe).
- **Buttons** — Start Brew, Cancel Brew, Pause Brew, Resume Brew, Tare Scale, Back to Home, Grind, Brew (standalone), Refresh Recipes, Save as New Recipe, plus BLE Connect / BLE Disconnect diagnostics.
- **Switches** — Use Grinder, Connect (opens a live session that holds the BLE link and streams machine events for sensors, the dashboard, and optional spoken announcements).
- **Update** — Firmware (installed vs latest, with an Install button; available when signed in to the xBloom cloud).

## Services

The integration registers its services under the `xbloom.` domain:

- **Brewing** — `start_brew`, `stop_brew`, `brew_pause`, `brew_resume`, `brew_standalone`, `write_slot`.
- **Machine control** — `grind`, `tare`, `back_to_home`, `set_mode`, `set_water_source`, `set_temp_unit`, `set_weight_unit`.
- **Recipe library** — `list_recipes`, `get_recipe`, `add_recipe`, `update_recipe`, `delete_recipe`, `save_scaled_recipe`.
- **Diagnostics** — `ble_connect`, `ble_disconnect`, `refresh_status`.

Each service, its fields, and examples appear in **Developer Tools → Actions**, and are documented in `custom_components/xbloom/services.yaml`.

## Blueprints

Three automation blueprints live in `blueprints/automation/xbloom/`:

- `brew_announce.yaml` — announces brew progress and completion.
- `live_control_announce.yaml` — speaks live-session feedback while you adjust the machine.
- `machine_fault_announce.yaml` — announces machine faults.

They target any TTS or notify service, so they work with Alexa, Google, or a local speaker. Import them from **Settings → Automations & Scenes → Blueprints → Import Blueprint** using the raw file URL, or copy them into your `config/blueprints/automation/` directory.

## Disclaimer

This is an independent, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. It communicates with the machine over its local BLE protocol, which may change with firmware updates. Firmware flashing in particular can brick the machine if it's interrupted. Use at your own risk.

## License

Released under the [MIT License](LICENSE).
