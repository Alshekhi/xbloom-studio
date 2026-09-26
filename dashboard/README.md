# xBloom Studio dashboard

An example dashboard for the whole integration — brewing, the machine's modules,
settings, and Coffee Lab — built from stock Home Assistant cards: **sections**
views of **tile** cards with visibility conditions. Nothing custom to install.
Paste it, then adapt it to your own home.

| File | What it is |
|---|---|
| `dashboard-xbloom-studio.yaml` | The dashboard, English. |
| `dashboard-xbloom-studio.ar.yaml` | The same dashboard, Arabic. |
| `dashboard-dependencies.yaml` | Three toggle helpers the dashboard uses. Create these first. |
| `build.py` | Builds both files from one layout. |

Entity names and states come from the integration, so they follow Home
Assistant's language on their own. The two files differ only in the
dashboard's own text: section headings, confirmations, and the few lines built
from data such as the bag list.

## Install

1. Set up the integration.
2. Create the three helpers in `dashboard-dependencies.yaml`.
3. New dashboard → **Edit dashboard** → three-dot menu → **Raw configuration
   editor** → paste the file for your language → **Save**.

Optional: import the blueprints in `../blueprints/automation/xbloom/` to get the
**Voice announcements** toggles. That section stays hidden until at least one
of those automations exists.

## Coffee Lab

The Coffee Lab cards — the bag in use, what is left, bags on hand, manual
brews, stats — appear only while Coffee Lab is switched on (**Configure →
Coffee Lab**). With it off, the dashboard is the machine alone. **Refresh
Coffee Bags** appears only when Coffee Lab is kept in Notion.

## The views

- **Brew** — what is happening now, the bag in use, brewing a recipe, one-off
  adjustments, saving a new recipe, and manual brews.
- **Stats** — brews and coffee over a chosen period, brews per brewer, and
  charts of the brew history: brews per day and per month, coffee used and
  water brewed per week. The charts read statistics the integration keeps
  from the brew record, so they cover every brew in it.
- **Bags** — every open or unopened bag, choosing the one in use, and a link
  to where bags are added and edited.
- **xBloom** — connection and status, the grinder, brewer and scale modules,
  the recipe library with its actions (archive, delete) and the archived
  recipes, settings, tools, announcements, updates, and a 24-hour log of
  machine events.

Every view uses `max_columns: 2`: two-up on a wide screen, one column on a
phone.

## What controls visibility

Two sensors drive the Brew and xBloom views:

- `sensor.xbloom_studio_current_module` — `home` / `grinder` / `brewer` / `scale`
- `sensor.xbloom_studio_brew_status` — `grinding` and `brewing` during a recipe

| Machine is on | Dashboard shows |
|---|---|
| Home (idle) | Status, brewing, and the adjustments if shown |
| Grinder, Brewer or Scale | Only that module, with Back to home |
| Brewing or grinding | Only the brew in progress |

Module sections match positively (`state: grinder`); idle sections stack
negative matches (`state_not: grinder`, …), so the idle screen goes the instant
the machine is on a module. The live modules also need
`switch.xbloom_studio_connect` on, since the knobs only respond while the
Bluetooth session is held.

A card for an entity that may not exist, or may have nothing to show — Coffee
Lab's, the scale weight, firmware, the announcement automations, the HACS
update — carries a `state_not: unavailable` guard; a missing entity reads as
unavailable, so the card is hidden rather than shown broken.

## Conventions to keep if you edit it

- **Section titles are `markdown` cards with `text_only: true` and `## …`**,
  not `heading` cards: only the markdown form renders a real heading, so the
  page can be moved through by heading.
- **Every tile sets `icon_tap_action: {action: none}`**, so the icon is not a
  second control beside the tile's own action. Action tiles also set
  `hide_state: true`.
- **Names come from the entities.** Tiles do not override them, so they are
  translated.
- **Destructive actions ask first** — Stop brew, Run recipe action,
  Record manual brew.

## Editing it

Change `build.py`, not the built files, then run `python3 dashboard/build.py`
(it needs PyYAML). The layout is written once and every language is built from
it, so the files cannot drift apart. A new language is one more entry in
`TEXT`.
