# xBloom Studio dashboard

Two views built entirely from stock Home Assistant cards — a **sections** view of **tile**
cards with visibility conditions. Nothing custom to install.

| File | What it is |
|---|---|
| `dashboard-xbloom-studio.yaml` | The dashboard. Paste into the raw configuration editor. |
| `dashboard-xbloom-studio.json` | The same config as JSON, for tools that prefer it. |
| `dashboard-dependencies.yaml` | Two toggle helpers and one script the dashboard references. Create these first. |

## Install

1. Create the helpers and script from `dashboard-dependencies.yaml`. The cards that use
   them error if they're missing.
2. New dashboard → **Edit dashboard** → three-dot menu → **Raw configuration editor** →
   paste `dashboard-xbloom-studio.yaml` → **Save**.

The `xbloom_studio_*` entities come from the integration, so set that up first. Importing
the blueprints in `../blueprints/automation/xbloom/` is optional — it adds the **Voice
announcements** toggles, and that section stays hidden until at least one of those
automations exists.

## The views

**Studio** is the daily driver: connection and status, modules, recipe, an optional brew
editor, the live module panels, and brew-in-progress.

**Machine** is settings and tools: mode and units, connection tools, announcement toggles,
update tiles, and a 24-hour logbook of machine events.

Both use `max_columns: 2`, so they're two-up on a wide screen and single-column on a phone.

## What controls visibility

Every section carries a `visibility:` block, and two sensors drive all of them:

- `sensor.xbloom_studio_current_module` — `home` / `grinder` / `brewer` / `scale`
- `sensor.xbloom_studio_brew_status` — includes `grinding` and `brewing` during a recipe

Together they make the Studio view behave as a state machine:

| Machine is on | Dashboard shows |
|---|---|
| Home (idle) | Connection & status, Modules, Recipe, and the brew editor if enabled |
| Grinder | Only the Grinder section, plus Back to home |
| Brewer | Only the Brewer section, plus Back to home |
| Scale | Only the Scale section, plus Back to home |
| Brewing or grinding | Only Brew-in-progress |

Module sections match positively (`state: grinder`). Idle sections carry a stack of negative
matches (`state_not: grinder`, `state_not: brewer`, and so on). That negative stack is what
makes the idle screen disappear the instant you step onto a module, with no flicker and no
two panels competing.

Most live sections also require `switch.xbloom_studio_connect: on`, because the knobs only
stream and respond while the Bluetooth session is held.

Two toggles keep the idle screen short: `input_boolean.xbloom_show_advanced` reveals the
brew editor, save-as-new-recipe, and the recipe library; `input_boolean.xbloom_show_per_pour`
reveals the per-pour table inside the editor.

## Conventions to keep if you edit it

These are deliberate, and changing them degrades the dashboard for screen-reader users:

- **Section titles are `markdown` cards with `text_only: true` and `## …`**, not `heading`
  cards. Only the markdown form emits a real `<h2>`, so heading navigation works.
- **Every tile sets `icon_tap_action: {action: none}`**, so the icon isn't a second,
  redundant tab stop beside the tile's own action. Action tiles also set `hide_state: true`.
- **Names are overridden everywhere** in plain language — "Grind size (lower is finer)",
  "Ratio (1:N water)", "You are here (machine screen)" — rather than raw entity names.
- **Destructive actions carry a `confirmation:` dialog** (Stop brew, Delete recipe).
- **Anything that could read as "unknown" or "unavailable" is hidden** behind a `state_not`
  guard rather than shown empty. That covers scale weight, firmware, dose on an xPod, the
  announcement automations, and the HACS update tile, which doesn't exist on a manual
  install.
- **Each section opens with a `text_only` sentence** saying what it does, since there are no
  visual affordances to lean on.

## The calculated cards

Two `markdown` cards in the brew editor do the arithmetic so the numbers stay honest and
unit-aware:

- **This brew** recomputes coffee, water, and ratio from the live sliders, formatting in
  grams and millilitres or in ounces per `select.xbloom_studio_weight_unit`.
- **Per-pour table** scales each stored pour by `dose × ratio ÷ sum of original pour
  volumes`, and prints temperature per `select.xbloom_studio_temperature_unit`
  (39 = room temperature, 96 = boiling point).
