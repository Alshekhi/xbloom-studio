# Coffee Lab

Coffee Lab keeps track of your bags of coffee and counts each brew against the
bag it came from. It is off until you switch it on in **Settings → Devices &
services → xBloom Studio → Configure → Coffee Lab**, where you also choose
where it keeps its records: in Home Assistant, which needs no setup and is part
of Home Assistant's backups, or in [Notion](#coffee-lab-in-notion). With it
off, nothing of it appears.

## Bags

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

A bag's **country**, **process**, **varietal** and **roast** are kept in the
[community hub](recipes.md#community-recipes)'s English names — "ethiopia",
the country's name in Arabic or Chinese, "Anaerobic", "gesha" or "light" become
"Ethiopia", "Anaerobic Fermentation", "Geisha/Gesha" and "Light Roast" — so
bags of the same coffee match each other and the hub. Several varieties are
separated by commas, and each is checked. A name the hub does not list is kept
as typed, and the action's response names it under `not_on_hub`. The
**roaster notes** stay as written; the hub's flavor names found in them are
what community suggestions match.

## Coffee, xPod boxes and tea

An item is a **bag of coffee**, a **box of xPods** or a **tea** — its kind,
set when it is added or edited. A brew draws from the kind its recipe's cup
takes: a coffee brew takes its dose from **Coffee bag**, an xPod brew takes
**one pod** from **xPod box**, and a tea brew takes its grams from **Tea**.
An xPod or tea brew is never charged to a bag of coffee, and with nothing of
its kind in use it is recorded against nothing. Only a coffee recipe needs a
bag chosen before it is prepared; the Brew tab shows the picker the picked
recipe needs.

A box is counted in **pods** — give how many it holds when adding it — and is
finished when the last is used. When the machine reads a pod's recipe card
while Connect holds the link, the box that card belongs to is put in use;
the first card read with a box in use teaches that box its card.

## How a brew is counted

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

**A brew is never lost when the record cannot be reached** — Notion down, or
the network away. It waits in Home Assistant with the time it was brewed, is
tried again every five minutes, and is saved once. **Waiting brews** counts
them; after an hour a repair says so.

## How was it

A while after a brew, Coffee Lab asks how it was: **Brew to rate** names the
recipe and the bag a quarter of an hour after the last cup, when the coffee can
have been tasted, and **Verdict** answers it — **Again**, **Fine** or **Not
again**. Unanswered, the question goes after a day.

A question is asked once for a recipe with a bag at one grind, ratio and dose,
and not again once it has a verdict. Cups of the same one brewed close
together share a question, and its answer is kept on each of them; a
different recipe, bag or setting gets a question of its own. Up to three are
open at once, asked oldest first.

Beside the verdict, how it tasted can be kept — body, acidity, sweetness and
clarity, how it was hot, warm and cool, overall, the finish — and a **Next
change**, such as "grind 52", with the `xbloom.rate_brew` action or by telling
an AI assistant. Only what is given is kept. The question can also be asked
for you: by an AI assistant that started the brew, through its
[callback](events.md#callbacks), or by the **Ask how the coffee was**
[blueprint](automations.md#ready-made-blueprints), on a phone or aloud.

### Trying a change

The next time the recipe is picked with that bag, **Next Change** offers the
change asked for, and **Use Next Change** sets the Brew tab's one-off
adjustments to it; the saved recipe stays as it is. The versions tried and
their verdicts are side by side on the Brew tab. A changed version rated
**Again** is offered to keep, as **Version to Keep**: **Make Version the
Recipe** changes the saved recipe, **Save Version as New Recipe** keeps both.

### A recipe for this bag

Choosing a bag looks for a recipe for it at once, and **Suggest Recipe** looks
again: your own first,
ranked by how close the bags they were brewed with are — this bag, then the
same origin and process, then the same origin — and by their verdicts, with
a recipe last rated **Not again** with this bag left out — and, after them,
[community recipes](recipes.md#community-recipes) for coffee like it, the
closest to the bag's process, varietal, roast and roaster notes first. **Suggested Recipe** offers them all, your own first and
each community one marked as such, with the best already chosen; its
attributes say why the chosen one was suggested. **Use Suggested Recipe**
picks it for brewing, adding a community recipe to your library first.

### Buy it again?

When a bag is finished, **Finished bag** names it for a week, and **Buy
again** keeps whether you would buy it again — yes, maybe or no.

## Entities and actions

**Coffee bag** (the bag in use), **Coffee left**, **Coffee bags** (with every
bag as an attribute), **Brews** and **Stats period**, **Last brew counted**,
**Waiting brews**, the manual-brew controls, and those described above for
rating, versions and suggestions. The actions are `xbloom.add_bean`,
`xbloom.update_bean`, `xbloom.set_active_bean`, `xbloom.consume`,
`xbloom.start_tracking`, `xbloom.finish_bag` and `xbloom.rate_brew`; each can
return what it did as a response.

**Brews** counts brews that made coffee; a brew stopped after grinding counts
toward the coffee used but not as a brew.

For charts, the integration keeps the whole brew record as long-term
statistics — `xbloom:brews_xbloom`, `xbloom:brews_manual`,
`xbloom:coffee_used` and `xbloom:water_brewed` — rebuilt from the record after
each change, so they cover every brew in the record, older ones included.
Any **Statistics graph** card can draw them.

## Coffee Lab in Notion

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
is saved until it is fixed. The fields for ratings — Rating, Body, Acidity,
Sweetness, Clarity, Hot, Warm, Cool and Overall Notes, Finish and Next Change
in Brews, and Buy Again in Coffee Beans — are added the first time one is
kept, as are Kind, Pods Left, Pod ID, Variety and Roast in Coffee Beans.
A select option the database lacks — a new brewer,
say — is added before it is used. A bag added or changed in Notion itself
appears within ten minutes, or at once with **Refresh Coffee Bags**.
