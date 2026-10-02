# xBloom Studio for Home Assistant

A community-built, local-first [Home Assistant](https://www.home-assistant.io/) integration for the **xBloom Studio** coffee machine. It talks to the machine directly over Bluetooth Low Energy (BLE) and turns it into ordinary Home Assistant entities, services, and automation blueprints, so you can brew, monitor, and manage recipes from a dashboard, an automation, or your voice.

Two ideas drove it, equally:

- **Local control.** Brewing and machine control run entirely over BLE, on your own hardware. No cloud account is required, and nothing depends on xBloom's servers to make coffee. Home Assistant contacts the machine only when it needs to and releases it again afterwards, so the official iOS app keeps working alongside it.
- **Spoken feedback.** The machine is driven by three physical knobs and says nothing aloud, so following a brew means standing over it and watching. Exposing it as Home Assistant entities, with spoken announcements for brew progress, live feedback, and faults through any TTS or notify service, means it can be followed and driven from anywhere in the house, by voice or from a phone.

An **optional** xBloom account adds cloud recipe sync and a firmware-update check on top. Everything else works without it.

> ⚠️ **Not affiliated with xBloom.** This is an independent, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. It communicates with the machine over its local BLE protocol, worked out for interoperability, which may change with firmware updates. Use at your own risk.

## Features

- **Live brew monitoring** — brew status, machine status, scale weight, and per-pour progress stream over BLE while a brew runs.
- **Recipe library** — keep recipes locally in Home Assistant, import them from an xBloom share link, and create, edit, or delete them from the integration's Configure menu.
- **Brew customizer** — scale a saved recipe on the fly (dose, ratio, grind size) for a one-off brew, or save the scaled result as a brand-new recipe.
- **Optional cloud sync** — sign in with your xBloom account to make the cloud the home for your recipes. Your account's recipes appear in Home Assistant (both your own and ones you saved from shared links, tagged with a `shared` attribute), and create/edit/delete write straight back to the cloud, so they show up in the iOS app too. On first sign-in, choose to upload your existing local recipes or discard them. Sign out any time to fall back to the local library.
- **Firmware update** *(cloud + Bluetooth)* — when signed in, a Firmware entity compares the machine's installed firmware (read over Bluetooth) against the latest version xBloom publishes, with release notes. Pressing **Install** downloads the firmware from xBloom, verifies its MD5, and flashes it over Bluetooth, acknowledged block by block and verified byte-for-byte against a real captured update. It's off until you enable it in the Configure menu. **⚠️ See [Firmware updates](docs/firmware-updates.md) before turning it on.**
- **One-tap brewing** — start, pause, resume, or cancel a brew; brew with pre-ground coffee; write a recipe to one of the machine's on-device slots.
- **Standalone control** — run the grinder or brewer on their own, tare the scale, switch water source, and change the machine's on-screen units.
- **Ready-made dashboard** — a context-aware dashboard built from stock Home Assistant cards, every control clearly labelled. It follows the machine from screen to screen and hides controls that can't work right now.
- **Coffee Lab** *(optional)* — keep track of your bags of coffee: each brew is counted against the bag it came from, with stats over any period. Kept in Home Assistant, or in Notion.
- **AI tools** — the whole machine, and Coffee Lab, as tools for Home Assistant's conversation agents and for any MCP client.
- **Announcement blueprints** — ready-made, one-click blueprints that speak brew progress, live machine feedback, and faults. Bilingual (English / Arabic), and they work with Alexa, any TTS engine and speaker, or any notify service.

## Getting started

### Requirements

- Home Assistant **2026.8** or newer.
- **Bluetooth on your Home Assistant host.** In most cases this is already there and there's nothing to buy or set up — a Raspberry Pi, an Intel NUC, or a mini PC running Home Assistant has Bluetooth built in, and the machine only has to be within its range.
  - If your host has no Bluetooth, or it's too far from the kitchen to reach the machine, an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) placed near the machine is one way to extend the range. **You don't need one otherwise** — it's an alternative for hosts that can't reach the machine, not a requirement. The integration uses whatever Home Assistant's own Bluetooth gives it and doesn't care which.
- The xBloom Studio powered on and in Bluetooth range during setup and while sending commands.
- **Internet access the first time it starts.** The BLE protocol library ships separately as [`xbloom-py`](https://pypi.org/project/xbloom-py/), and Home Assistant installs it from PyPI when the integration is first set up or updated. After that it runs entirely locally — brewing has never needed the internet and still doesn't.

### Installation

#### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Alshekhi&repository=xbloom-studio&category=integration)

Click the button, press **Download**, then restart Home Assistant. It adds the repository to
HACS for you.

Prefer to do it by hand — or never set up [My Home Assistant](https://my.home-assistant.io/)
links, which the button relies on?

1. In Home Assistant, open **HACS**.
2. Open the menu (three dots, top right) → **Custom repositories**.
3. Add the URL `https://github.com/Alshekhi/xbloom-studio` and choose the category **Integration**.
4. Install **xBloom Studio**, then restart Home Assistant.

#### Manual

Copy `custom_components/xbloom/` into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

### Setup

With the machine powered on and in range, Home Assistant discovers it automatically over Bluetooth (it advertises as `XBLOOM …`). A discovered device appears under **Settings → Devices & Services**; confirm it to finish setup. If it isn't discovered, use **Add Integration → xBloom Studio** and pick it from the list or type its BLE name.

Recipes are managed after setup from the integration's **Configure** menu: add one from an xBloom share link, or create, edit, and delete recipes by hand. The **Recipe** select entity always reflects the current library.

## Documentation

- [Brewing](docs/brewing.md) — how picking a recipe prepares it, starting at the machine, pause and resume.
- [Recipes](docs/recipes.md) — cloud sign-in, how recipes sync, and archiving.
- [Entities and actions](docs/entities-and-actions.md) — everything the integration adds to Home Assistant.
- [Coffee Lab](docs/coffee-lab.md) — bags, how a brew is counted, and keeping it in Notion.
- [AI assistants](docs/ai-assistants.md) — the tools for conversation agents and MCP clients.
- [Automations](docs/automations.md) — the announcement blueprints, and examples to write your own.
- [Events](docs/events.md) — what the integration fires during a brew, and callbacks to services outside Home Assistant.
- [Firmware updates](docs/firmware-updates.md) — read before turning the updater on.

## Dashboard

A ready-made dashboard lives in [`dashboard/`](dashboard/), built from stock Home Assistant
cards — nothing custom to install. It follows the machine from screen to screen, showing the
grinder's controls when you're at the grinder and the brew panel while a recipe runs, and
it's laid out so every control is clearly labelled and reachable in order.

It comes in English and Arabic, and shows Coffee Lab's cards only while Coffee
Lab is switched on.

1. Create the three helpers in
   [`dashboard/dashboard-dependencies.yaml`](dashboard/dashboard-dependencies.yaml).
2. New dashboard → **Edit dashboard** → three-dot menu → **Raw configuration editor** →
   paste [`dashboard/dashboard-xbloom-studio.yaml`](dashboard/dashboard-xbloom-studio.yaml)
   or [`dashboard/dashboard-xbloom-studio.ar.yaml`](dashboard/dashboard-xbloom-studio.ar.yaml).

[`dashboard/README.md`](dashboard/README.md) documents the views and what to change if
you adapt it.

## Troubleshooting

**A brew takes tens of seconds to start.** Open **Settings → Devices & Services →
Bluetooth** and check whether more than one adapter is listed. If one of them is offline or
no longer exists, Home Assistant may try it first and wait out its timeout before falling
back to a working adapter. Removing a stale one took the connect step from 28 seconds to
under a second on a real install.

**The iOS app can't connect.** Turn off the **Connect** switch — it holds the Bluetooth link
open, and the machine only accepts one connection at a time.

**A recipe you added on your phone isn't in the list.** Press the **Refresh Recipes** button.
Cloud sync is event-driven, not polled.

## Firmware updates

Firmware flashing is off by default, and it is the one feature here that can
permanently damage your machine. Read [Firmware updates](docs/firmware-updates.md)
before you turn it on.

## Disclaimer

This is an independent, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. "xBloom" is used only to say which machine this talks to. It communicates with the machine over its local BLE protocol, worked out for interoperability, which may change at any time with a firmware update and break this integration without warning.

The software is provided **as is, without warranty of any kind**, express or implied. You use it at your own risk, and the authors and contributors are not liable for any damage, loss, or injury resulting from its use. See [Firmware updates](docs/firmware-updates.md) for the risk that matters most.

## License

Released under the [MIT License](LICENSE).
