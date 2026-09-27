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

## Entities and actions

**Coffee bag** (the bag in use), **Coffee left**, **Coffee bags** (with every
bag as an attribute), **Brews** and **Stats period**, **Last brew counted**,
and the manual-brew controls. The actions are `xbloom.add_bean`,
`xbloom.update_bean`, `xbloom.set_active_bean`, `xbloom.consume`,
`xbloom.start_tracking` and `xbloom.finish_bag`; each can return what it did as
a response.

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
is saved until it is fixed. A select option the database lacks — a new brewer,
say — is added before it is used. A bag added or changed in Notion itself
appears within ten minutes, or at once with **Refresh Coffee Bags**.
