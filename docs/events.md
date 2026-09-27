# Events the integration fires

Automations can trigger on these. They are the integration's contract with
anything that wants to know how a brew went — the blueprints use them, and so
can your own automations or a service outside Home Assistant.

| Event | When | Payload |
|---|---|---|
| `xbloom_brew_started` | the machine has accepted the brew — every step, including execute | `recipe_name`, `total_pours` |
| `xbloom_brew_completed` | **The brew finished.** Key on this one. | `recipe_id`, `recipe_name`, `dose_g`, `cup_type`, `outcome`, `started_at`, `first_pour_at`, `ended_at`, `duration_s` (first pour to the machine's end signal; empty when either went unheard), and what it was made with: `grind`, `water_ml`, `ratio`, `temperature_c`, `flow_rate` (a value the pours disagree on is omitted rather than guessed) |
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

## Callbacks

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

## Event reference

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
