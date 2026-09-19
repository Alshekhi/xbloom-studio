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
- **Firmware update** *(cloud + Bluetooth)* — when signed in, a Firmware entity compares the machine's installed firmware (read over Bluetooth) against the latest version xBloom publishes, with release notes. Pressing **Install** downloads the firmware from xBloom, verifies its MD5, and flashes it over Bluetooth, acknowledged block by block and verified byte-for-byte against a real captured update. It's off until you enable it in the Configure menu. **⚠️ See [Firmware updates](#firmware-updates) before turning it on.**
- **One-tap brewing** — start, pause, resume, or cancel a brew; brew with pre-ground coffee; write a recipe to one of the machine's on-device slots.
- **Standalone control** — run the grinder or brewer on their own, tare the scale, switch water source, and change the machine's on-screen units.
- **Ready-made dashboard** — a context-aware dashboard built from stock Home Assistant cards, every control clearly labelled. It follows the machine from screen to screen and hides controls that can't work right now.
- **Announcement blueprints** — ready-made, one-click blueprints that speak brew progress, live machine feedback, and faults. Bilingual (English / Arabic), and they work with Alexa, any TTS engine and speaker, or any notify service.

## Getting started

### Requirements

- Home Assistant **2025.1** or newer.
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

#### Optional: xBloom cloud sign-in

The same **Configure** menu has **Sign in to xBloom cloud**. Sign in with your xBloom account to sync recipes: once signed in, the cloud becomes the home for your recipes and every create, edit, and delete is written back to your account. If you already have local recipes, you'll be asked whether to upload them or discard them.

Tick **Remember my credentials** to store your password locally (in `.storage`, next to the session token) so the session refreshes itself when the token expires. It's only ever sent to xBloom's sign-in endpoint. Leave it unticked for more privacy: only the token is kept, and you'll be prompted to sign in again when it expires. Use **Sign out of xBloom cloud** to clear everything and return to the local library (your synced recipes stay cached locally). The cloud is entirely optional; leaving it out keeps the integration BLE-only.

Recipe sync is event-driven, not polled: changes you make in Home Assistant apply immediately, and the Configure recipe lists pull fresh from the cloud each time you open them. A recipe you added or edited on your phone shows up in the dashboard dropdowns after you press the **Refresh Recipes** button.

## Entities and services

### Entities

- **Sensors** — Brew Status, Machine Status, Scale Weight, and live readings: Current Recipe, Current Pour, Current Module, Grind Size, Grind Speed, Pour Pattern, Brew Temperature, Brew Ratio, Last Recipe Card, Status Updated.
- **Binary sensor** — In Range: on while Home Assistant's Bluetooth can see the machine, off once it drops it. The status sensors keep the last thing the machine reported, so this is the one that says a machine switched off is gone.
- **Event** — Brew Event, fired on brew lifecycle changes (useful as an automation trigger).
- **Selects** — Recipe, Mode (auto / pro), Water Source (tank / tap), Temperature Unit (°C / °F), Weight Unit (g / oz / ml), Brew Pattern.
- **Numbers** — Grind Size, Grind Speed, Brew Volume, Brew Temperature, Brew Flow Rate, and the brew-customizer overrides: Brew Dose, Brew Ratio, Brew Grind Size.
- **Text** — New Recipe Name (used by the brew customizer's Save as New Recipe).
- **Buttons** — Start Brew, Cancel Brew, Pause Brew, Resume Brew, Tare Scale, Back to Home, Grind, Brew (standalone), Refresh Recipes, Save as New Recipe, plus BLE Connect / BLE Disconnect diagnostics.
- **Switches** — Use Grinder, Connect (opens a live session that holds the BLE link and streams machine events for sensors, the dashboard, and optional spoken announcements).
- **Update** — Firmware (installed vs latest, with an Install button; available when signed in to the xBloom cloud).

### Services

The integration registers its services under the `xbloom.` domain:

- **Brewing** — `start_brew`, `stop_brew`, `brew_pause`, `brew_resume`, `brew_standalone`, `write_slot`.
- **Machine control** — `grind`, `tare`, `back_to_home`, `set_mode`, `set_water_source`, `set_temp_unit`, `set_weight_unit`.
- **Recipe library** — `list_recipes`, `get_recipe`, `add_recipe`, `update_recipe`, `delete_recipe`, `save_scaled_recipe`.
- **Diagnostics** — `ble_connect`, `ble_disconnect`, `refresh_status`.

Each service, its fields, and examples appear in **Developer Tools → Actions**, and are documented in `custom_components/xbloom/services.yaml`.

## Dashboard

A ready-made dashboard lives in [`dashboard/`](dashboard/), built from stock Home Assistant
cards — nothing custom to install. It follows the machine from screen to screen, showing the
grinder's controls when you're at the grinder and the brew panel while a recipe runs, and
it's laid out so every control is clearly labelled and reachable in order.

1. Create the helpers and script from
   [`dashboard/dashboard-dependencies.yaml`](dashboard/dashboard-dependencies.yaml).
2. New dashboard → **Edit dashboard** → three-dot menu → **Raw configuration editor** →
   paste [`dashboard/dashboard-xbloom-studio.yaml`](dashboard/dashboard-xbloom-studio.yaml).

[`dashboard/README.md`](dashboard/README.md) documents the two views and what to change if
you adapt it.

## Automations

There are two ways to get spoken brew announcements: import a ready-made
blueprint, or write your own automation. Most people want the blueprints.

### Ready-made blueprints

Three blueprints ship with the integration. Each one is configured entirely
through form fields — pick a speaker, pick a language, done — with no YAML to
edit.

| Blueprint | What it does | Import |
|---|---|---|
| **Brew announcements** | Announces the brew starting, pouring, and the coffee being ready. Optionally names the recipe. | [Import][bp-brew] |
| **Live-session announcements** | Speaks live feedback while you turn the machine's knobs — weight, grind size, temperature, which module you're on. Needs the **Connect** switch on. | [Import][bp-live] |
| **Machine fault announcements** | Speaks up when the machine runs out of water or beans, or reports a dose or gear problem. | [Import][bp-fault] |

[bp-brew]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Fbrew_announce.yaml
[bp-live]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Flive_control_announce.yaml
[bp-fault]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FAlshekhi%2Fxbloom-studio%2Fmain%2Fblueprints%2Fautomation%2Fxbloom%2Fmachine_fault_announce.yaml

Each **Import** link opens the blueprint straight in your own Home Assistant. If
a link doesn't work, the files are in
[`blueprints/automation/xbloom/`](blueprints/automation/xbloom/) — copy them into
`config/blueprints/automation/`, or paste the raw URL into **Settings →
Automations & Scenes → Blueprints → Import Blueprint**.

**Every blueprint speaks through whatever you have.** The **How to announce**
field offers three choices:

- **Alexa** — via the [Alexa Media Player](https://github.com/alandtse/alexa_media_player) custom integration.
- **Speaker (TTS)** — any TTS engine (Piper, Google Translate, Cloud) on any media player.
- **Notify service** — any `notify.*` service, so the text arrives as a phone notification instead of speech.

All three are **bilingual, English or Arabic**, chosen per automation. You can
import a blueprint more than once — for example, English on the kitchen speaker
and Arabic on another.

### Events the integration fires

Automations can trigger on these. They are the integration's contract with
anything that wants to know how a brew went — the blueprints use them, and so
can your own automations or a service outside Home Assistant.

| Event | When | Payload |
|---|---|---|
| `xbloom_brew_started` | Home Assistant has begun a brew | `recipe_name`, `total_pours` |
| `xbloom_brew_completed` | **The brew finished.** Key on this one. | `run_id`, `recipe_id`, `recipe_name`, `dose_g`, `cup_type`, `outcome`, `started_at`, `ended_at` |
| `xbloom_brew_failed` | The brew could not start, or the machine gave up on it | `reason`, `recipe_name`, sometimes `run_id` / `error` |
| `xbloom_brew_timeout` | Ten minutes passed with no ending heard from the machine | `recipe_name` |

**`outcome` is the part worth understanding.** The machine's own "your coffee
is ready" (`RD_ENJOY`) is what a completion rests on, but it can fail to be
heard: until xbloom-py 0.2.1 it was dropped whenever the machine packed it into
one Bluetooth notification behind other frames. So:

- **`confirmed`** — `RD_ENJOY` arrived. The machine said so itself.
- **`presumed`** — it did not, but the machine's end-of-pouring frame did, and
  nothing followed within two minutes. The coffee was made; the final signal
  was lost.

Both mean the brew finished, and a consumer should treat them the same unless
it has a reason not to. When neither signal arrives, no completion is fired at
all — that case is genuinely unknown, and becomes `xbloom_brew_timeout` rather
than a completion nobody can stand behind.

`reason` on a failure is a code, not a sentence — `machine_not_found`,
`bluetooth_error`, `recipe_not_found`, `not_configured`, `no_beans` — so the
wording belongs to whatever announces it.

**A brew only starts once the machine has accepted every step.** A refused step
is answered with the step's own code, like an accepted one, so the refusal has
to be read out of the reply; when one arrives, or a step gets no reply at all,
the brew stops before the machine is told to execute, and the failure carries
the step as `step`:

- `machine_busy` — the machine is doing something else, or has just been
  powered on: after a power cut it refuses the first command it is sent.
- `not_on_home_screen` — the machine is not on its standby screen.
- `no_water` — the tank is short of water.
- `recipe_rejected` — the machine did not accept the recipe.
- `no_reply` — the machine never answered the step, or its replies could not
  be read.

Executing anyway would grind at whatever size the machine last held.

**Low water is a live reading.** The machine reports the level continuously, but
only while Home Assistant holds the Bluetooth link — which it releases when a
brew ends. So `sensor.xbloom_studio_machine_status` drops a water fault at that
point, and does not restore one across a restart, rather than asserting a level
nobody is still reading; an empty tank
reports itself again on the next connection, and immediately at the next brew.
The other faults are reported once and stay until a brew starts.

**A fault the machine cannot brew through ends the brew.** With no beans in the
hopper it stops the grinder and does nothing further, so waiting for an ending
would leave a brew showing as in progress until it was cancelled by hand: that
fires `xbloom_brew_failed` with the fault as its reason, and `brew_status`
returns to `idle`. A fault it *does* brew through — low water, which the machine
reports mid-pour and carries on — changes nothing.

**A brew started on the machine itself fires none of these.** It runs no Home
Assistant brew task, so there is nothing to report it; `sensor.xbloom_studio_brew_status`
still follows it to `done`, as long as Home Assistant is holding the Bluetooth
link at the time. Key on the sensor when you want every brew, and on the events
when you want the ones Home Assistant started and everything they carry.

### Write your own

The blueprints cover the common jobs. Write your own if you want different
wording, a different service, or a trigger they don't offer. These are the
starting points people ask for most.

Every example speaks through `tts.speak`. Replace that action with any `notify.*`
service to get a phone notification instead — the triggers and templates are the
same either way.

#### Announce the brew from start to finish

The main one. Without it a brew is silent: the machine grinds, pauses, pours, and finishes
with nothing to tell you which stage you're at or when to come back. This narrates the whole
cycle, and names the recipe if Home Assistant started the brew.

```yaml
alias: Narrate the xBloom brew
triggers:
  - trigger: event
    event_type: xbloom_brew_started
    id: started
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: grinding
    id: grinding
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: brewing
    id: pouring
  - trigger: state
    entity_id: sensor.xbloom_studio_brew_status
    to: done
    id: ready
actions:
  - variables:
      message: >-
        {% if trigger.id == 'started' %}
          Starting {{ trigger.event.data.get('recipe_name') or 'your coffee' }}
        {% elif trigger.id == 'grinding' %}Grinding the beans
        {% elif trigger.id == 'pouring' %}Pouring
        {% else %}Your coffee is ready{% endif %}
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.kitchen
      message: "{{ message }}"
```

The three status triggers work whether you started the brew from Home Assistant or by hand
on the machine. The `xbloom_brew_started` trigger is the only one that knows the recipe
name, and it fires only for brews Home Assistant started.

**Want just the ending?** Keep the `ready` trigger and drop the other three.

#### Say something when the machine needs you

A brew that stalls because the tank ran dry looks exactly like a brew that's still working.
This is the difference between waiting two minutes and waiting twenty.

```yaml
alias: xBloom needs attention
triggers:
  - trigger: state
    entity_id: sensor.xbloom_studio_machine_status
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.state not in ['ok', 'unknown', 'unavailable'] }}"
actions:
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.kitchen
      message: >-
        {% set s = trigger.to_state.state %}
        {% if s == 'no_water' %}The xBloom is out of water
        {% elif s == 'no_beans' %}The xBloom is out of beans
        {% elif s == 'gear_position_error' %}Check the xBloom's dripper position
        {% else %}The xBloom reported a dose or water problem{% endif %}
```

#### Start the coffee without walking to the machine

`xbloom.start_brew` with no fields brews whatever `select.xbloom_studio_recipe` is set to,
which is all a dashboard button or a voice assistant needs. The optional fields rescale the
recipe **for that brew only** — your saved recipe is never modified.

```yaml
alias: Morning coffee
triggers:
  - trigger: time
    at: "06:45:00"
conditions:
  - condition: state
    entity_id: sensor.xbloom_studio_brew_status
    state: idle
actions:
  - action: xbloom.start_brew
    data:
      recipe_name: Ethiopia Yirgacheffe
      dose: 18
      ratio: 16
```

`grind_size` overrides the grind for one brew, and `use_preground: true` skips the grinder
entirely. Drop the `data:` block completely to just brew the selected recipe as saved.

> The **Connect** switch holds the Bluetooth link open so the machine can stream live
> feedback. While it's on, the official iOS app can't connect. Turn it off when you're done
> if you want to use the app.

<details>
<summary><strong>Event reference</strong> — every trigger the integration exposes</summary>

Most automations only need `sensor.xbloom_studio_brew_status`
(`idle` → `grinding` → `brewing` → `done`) or
`sensor.xbloom_studio_machine_status` (`ok`, `no_water`, `no_beans`,
`dose_water_error`, `gear_position_error`). The rest is here for anything more detailed.

**`event.xbloom_studio_brew_event`** fires the per-stage brew lifecycle. Its *state* is a
timestamp, not the event name, so `to: "brew_done"` never matches — trigger on any state
change and test `trigger.to_state.attributes.event_type`:

| `event_type` | When | Attributes |
|---|---|---|
| `brew_started` | the first pour begins | `recipe_name` |
| `brew_done` | the cup is ready | `recipe_name` |
| `grinder_started` / `grinder_stopped` | the burrs start and stop | |
| `brewer_started` | the brewer takes over | |
| `pour_started` | each pour begins | `pour_index` (0-based) |
| `bypass_started` | a bypass pour begins | |
| `brew_ended` | the brew sequence finishes | |
| `error_no_water` / `error_no_beans` / `error_dose_water` / `error_gear_position` | a fault is reported | |

**Bus events** come from the live session and fire **only while the Connect switch is on**:

| Event | Fired when | Data |
|---|---|---|
| `xbloom_brew_started` | `xbloom.start_brew` dispatches (also fires with Connect off) | `recipe_name`, `total_pours` |
| `xbloom_connect_ready` / `_connecting` / `_failed` / `_stopped` / `_auto_stopped` | the live session changes state | `reason` on failures and stops |
| `xbloom_scale_weight_stable` | the weight settles while you're on the scale | `weight_g`, `unit` |
| `xbloom_grinder_knob_changed` | a grinder knob is turned | `parameter`, `value` |
| `xbloom_brewer_setting_changed` | a brewer setting is changed | `setting`, `value`, `value_name` |
| `xbloom_module_entered` | you move to another module | `module` |
| `xbloom_mode_changed` | Auto/Pro is switched | `mode` |
| `xbloom_scale_tared` | the scale is tared | |
| `xbloom_recipe_card_scanned` | an xPod card is read | `pod_id` |

</details>

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

**Read this before you enable it.** Firmware flashing is **opt-in and off by default**, and it is the one feature here that can
permanently damage your machine. Enable it only if you accept that.

The update is downloaded from xBloom, its MD5 is verified before anything is sent, and every
block is acknowledged by the machine as it's written. That makes a bad flash unlikely — it
does not make it impossible. **Bluetooth is a wireless link, and a wireless link can drop.**
If it drops in the middle of a firmware write, the machine can be left unbootable, with no
way to recover it from Home Assistant.

If you choose to use it:

- Keep the machine powered and close to the Bluetooth adapter for the whole flash.
- Never start a flash during a brew, or when you're about to leave the house.
- Don't restart Home Assistant while one is running.

**You do this entirely at your own risk.** This is unofficial software talking to an
undocumented protocol that was worked out by inspection, and it is not endorsed by or
connected to xBloom in any way. The authors and contributors accept **no responsibility and
no liability** for any damage to your machine, loss of warranty, or any other loss arising
from using this integration — the firmware updater above all. If that isn't a risk you want
to take, leave the feature switched off; everything else works without it.

## Disclaimer

This is an independent, community project. It is **not affiliated with, authorized, or endorsed by xBloom**. "xBloom" is used only to say which machine this talks to. It communicates with the machine over its local BLE protocol, worked out for interoperability, which may change at any time with a firmware update and break this integration without warning.

The software is provided **as is, without warranty of any kind**, express or implied. You use it at your own risk, and the authors and contributors are not liable for any damage, loss, or injury resulting from its use. See the [Firmware updates](#firmware-updates) section for the risk that matters most.

## License

Released under the [MIT License](LICENSE).
