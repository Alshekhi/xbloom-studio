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

Optional: create automations from the announcement blueprints the integration
installs to get the **Voice announcements** toggles. That section stays hidden until at least one
of those automations exists.

## Coffee Lab

The Coffee Lab cards — the bag in use, what is left, bags on hand, manual
brews, stats — appear only while Coffee Lab is switched on (**Configure →
Coffee Lab**). With it off, the dashboard is the machine alone. **Refresh
Coffee Bags** appears only when Coffee Lab is kept in Notion.


A brew that cannot be saved — Coffee Lab kept in Notion, and Notion cannot be
reached — is kept in Home Assistant and saved by itself once it can be.
**Waiting brews** appears on the Brew tab only while one is waiting, and a
repair appears if one has waited more than an hour.

## The views

- **Brew** — what is happening now, the bag in use, a recipe for that bag,
  brewing a recipe, one-off adjustments, saving a new recipe, and manual brews.
  Choosing a bag, or **Suggest a recipe**, fills a picker with your own recipes brewed with this
  bag or coffee like it, then community recipes to try, each marked as from
  the community, with the best chosen; a line says why it was suggested, and
  **Use this recipe** picks it for brewing, adding a community one to your
  recipes first. Asking for a suggestion sends nothing to the machine.
  **How was it?** appears a quarter of an hour after a brew of a recipe, bag
  and grind, ratio and dose that has no verdict, and asks for one: Again, Fine
  or Not again. Cups of the same one brewed close together are asked about
  once; several different ones are asked about in turn. A version rated Again that changed the recipe is
  offered to keep, as the recipe or as a new one; a change asked for last time
  is offered as **Use that change** under the recipe picker; a finished bag
  asks whether it would be bought again.
- **Stats** — brews and coffee over a chosen period, brews per brewer, and
  charts of the brew history: brews per day and per month, coffee used and
  water brewed per week. The charts read statistics the integration keeps
  from the brew record, so they cover every brew in it.
- **Bags** — every open or unopened bag, choosing the one in use, and a link
  to where bags are added and edited.
- **Community** — signed in to the xBloom account, first For You (with
  Another), Trending recipes and Tea recipes, as the xBloom app offers them to
  the account, each with Add, and Show xPod recipes. Then, signed in or not,
  Studio recipes other people shared on the xBloom
  community hub. **Suggest a recipe** offers the most downloaded ones for the
  bag in use (its origin and process), leaving out recipes you already have,
  and picks one; or search by words, origin and order. Read one with its
  pours, and add it to your recipes. It is then brewed from the Brew tab like any
  other recipe. Text a recipe's author wrote is shown exactly as written,
  never as a link, image or formatting.
- **xBloom** — connection and status, the grinder, brewer and scale modules,
  the recipe library with its actions (archive, delete), settings, tools, announcements, updates, and a 24-hour log of
  machine events.
- **Archived recipes** — a subview with no tab of its own, opened from the
  recipe library's link, which shows only while something is archived.
  Restoring a recipe is done here.

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
- **Names come from the entities**, so they are translated — except where a
  section heading already gives the context (the Community tab, and the rating,
  version and suggestion sections of the Brew tab), whose tiles take short
  names from `TEXT` in each language.
- **Destructive actions ask first** — Stop brew, Run recipe action,
  Record manual brew, Make it the recipe, Add to my recipes.

## Editing it

Change `build.py`, not the built files, then run `python3 dashboard/build.py`
(it needs PyYAML). The layout is written once and every language is built from
it, so the files cannot drift apart. A new language is one more entry in
`TEXT`.
