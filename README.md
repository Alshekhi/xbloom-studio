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

## Coffee Lab

Coffee Lab keeps track of your bags of coffee and counts each brew against the
bag it came from. It is off until you switch it on in **Settings → Devices &
services → xBloom Studio → Configure → Coffee Lab**, where you also choose
where it keeps its records: in Home Assistant, which needs no setup and is part
of Home Assistant's backups, or in [Notion](#coffee-lab-in-notion). With it
off, nothing of it appears.

### Bags

Add and edit bags in **Configure → Add a bag / Edit a bag**, with the
`xbloom.add_bean` and `xbloom.update_bean` actions, or by asking an AI
assistant. A bag given the grams in it is **tracked**: counted down with each
brew. A bag without an amount is **untracked**: its brews are recorded, and
nothing is subtracted. Weigh a bag and use `xbloom.start_tracking` to start
counting it at any time.

A bag is **unopened**, then **open** from its first brew, then **finished**
once a brew leaves 5 g or less, or when you mark it with
`xbloom.finish_bag`. Finishing is refused for an unopened bag, and for a
tracked bag still showing 20 g or more — weigh it and start tracking again
first. A finished bag keeps its brews.

Bags are named by their name, or by their id when two bags share one; a shared
name is refused rather than guessed.

### How a brew is counted

The bag is fixed when the brew starts: the one named in `start_brew`
(`bean_id`), otherwise the one chosen in **Coffee bag**. Choosing another bag
while a brew runs does not move it. A brew from no bag, such as an xPod, is
started with `unattributed`.

When the brew completes — `confirmed` or `presumed` — its dose is taken from
that bag, once, however many times the completion arrives. Some brews are
recorded without touching a bag:

| Brew | What happens |
|---|---|
| From an xPod, or `unattributed` | Recorded against no bag |
| From an untracked bag | Recorded against the bag; nothing subtracted |
| With no bag chosen | Recorded for review (`no_bag`) |
| Larger than what the bag shows | Recorded for review (`more_than_left`); the bag is left as it is |
| From a finished bag | Recorded for review (`bag_closed`) |
| From a tracked bag with no amount | Recorded for review (`tracked_without_amount`) |
| Stopped after the grinder ran | Recorded for review (`stopped_after_grinding`), since its coffee was used |

A brew recorded for review shows on **Last brew counted** as *Needs review*,
with the reason in its attributes. A brew started from the machine's own
controls runs no Home Assistant brew and is not counted.

Coffee made another way — a V60, say — is recorded with **Manual brewer**,
**Manual brew dose** and **Record manual brew**, or `xbloom.consume`. The
brewers offered are yours to set in **Configure → Coffee Lab**.

### Entities and actions

**Coffee bag** (the bag in use), **Coffee left**, **Coffee bags** (with every
bag as an attribute), **Brews** and **Stats period**, **Last brew counted**,
and the manual-brew controls. The actions are `xbloom.add_bean`,
`xbloom.update_bean`, `xbloom.set_active_bean`, `xbloom.consume`,
`xbloom.start_tracking` and `xbloom.finish_bag`; each can return what it did as
a response.

**Brews** counts brews that made coffee; a brew stopped after grinding counts
toward the coffee used but not as a brew.

### Coffee Lab in Notion

Choose **Notion** in **Configure → Coffee Lab**, then give it an [internal
integration](https://www.notion.so/profile/integrations) token and one page
shared with that integration (**••• → Connections**). Inside that page it uses
a **Coffee Beans** and a **Brews** database, or creates both if the page has
neither. Existing databases must have these fields; any other fields are left
alone:

| Database | Fields |
|---|---|
| Coffee Beans | Bean (title), Status (select), Remaining g, Bag Size g (numbers), Inventory Tracking, Process (selects), Roaster, Country, Region, Roaster Notes (text), Opened Date, Finished Date (dates) |
| Brews | Brew (title), Brewed At (date), Dose g, Ratio, Water g, Temperature C, Flow Rate, Total Time sec (numbers), Brewer, Dripper, Outcome, Review Reason (selects), Bean (relation to Coffee Beans), Recipe, Grind, Run ID (text), Needs Review (checkbox) |

A field missing or of the wrong type is named when you set it up, and nothing
is saved until it is fixed. A select option the database lacks — a new brewer,
say — is added before it is used. A bag added or changed in Notion itself
appears within ten minutes, or at once with **Refresh Coffee Bags**.

## AI assistants

The integration offers its controls as tools for AI assistants: **xbloom**, for
the machine — recipes, brewing, the modules, settings — and, while Coffee Lab
is on, **coffee_lab**, for bags, manual brews, history and stats. Each tool's
description names, per action, the arguments that action needs, and lists the
bags on hand. Results are facts for the assistant to put into words in its own
language; a refused call says why, in Home Assistant's language.

`start_brew` waits for the machine to accept or refuse the brew before it
answers. With Coffee Lab on, it needs the bag the coffee comes from, or
`unattributed`. With `notify_target`, the caller is told how the brew ends by
[callback](#callbacks).

**A conversation agent in Home Assistant:** in its settings, under **Control
Home Assistant**, choose **xBloom Studio**.

**Any MCP client** (Home Assistant 2026.8 or newer): add the **Model Context
Protocol Server** integration and select **xBloom Studio**. The tools are then
served at

```
https://<your Home Assistant>/api/mcp/xbloom
```

with a long-lived access token of an **administrator** in the `Authorization:
Bearer` header — Home Assistant serves any API other than Assist to
administrators only.

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
| `xbloom_brew_started` | the machine has accepted the brew — every step, including execute | `recipe_name`, `total_pours` |
| `xbloom_brew_completed` | **The brew finished.** Key on this one. | `recipe_id`, `recipe_name`, `dose_g`, `cup_type`, `outcome`, `started_at`, `ended_at`, `duration_s`, and what it was made with: `grind`, `water_ml`, `ratio`, `temperature_c`, `flow_rate` (a value the pours disagree on is omitted rather than guessed) |
| `xbloom_brew_failed` | The brew could not start, or the machine gave up on it | `reason`, `recipe_name`, sometimes `step` / `error` |
| `xbloom_brew_stopped` | Someone stopped the brew | `by`, `recipe_name`, `ground` (whether the grinder had run), `dose_g` |
| `xbloom_brew_timeout` | Ten minutes passed with no ending heard from the machine | `recipe_name` |

**Every event of one brew also carries its `run_id`**, the same on each, so a
consumer can tell brews apart and handle a repeated event once. `start_brew`
returns it when asked for a response. Give `start_brew` a `context` — any value
— and every event of that brew carries it back unchanged, so an automation can
route the outcome to whoever started the brew. Events are kept in Home
Assistant's history, and so is a `context` sent with one.

`by` on a stop is `machine` (stopped on the machine itself), `home_assistant`
(Cancel Brew, or the `stop_brew` action) or `superseded` (a new brew replaced
one still running). A machine that stops over a fault it cannot brew through —
no beans — reports a failure with that reason instead, not a stop.

**`outcome` is the part worth understanding.** The machine's own "your coffee
is ready" (`RD_ENJOY`) is what a completion rests on, but it can fail to be
heard: until xbloom-py 0.3.0 it was dropped whenever the machine packed it into
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
- `not_ready` — the machine is still recovering from a power interruption and
  refuses every command until it is back on its standby screen. Running
  calibration with the right knob gets it there.
- `restore_incomplete` — the same recovery, one step further on.
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

#### Callbacks

A service outside Home Assistant can be told how a brew it started went,
without watching the event stream. Add a callback target in **Settings →
Devices & services → xBloom Studio → Configure → Add a callback target**: a
name, the URL to post to, and a [Standard Webhooks](https://www.standardwebhooks.com)
secret (`whsec_…`). Then start the brew with `notify_target` set to that name.

The target receives that brew's faults and exactly one ending — `completed`,
`failed`, `stopped` or `timeout` — and, with `notify_progress`, grinding and
each pour. Each is a signed POST, retried if the receiver is briefly away, of
the form `{"type": "xbloom.brew.<event>", "timestamp", "data": {"event",
"final", "run_id", "recipe", …}, "context"}`, where `data` holds the same facts
as the event and `context` is what `start_brew` was given. A caller names a
target; it can never supply a URL.

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
| `xbloom_brew_started` | the machine accepts the brew (also fires with Connect off); a refused brew fires `xbloom_brew_failed` instead | `recipe_name`, `total_pours` |
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
