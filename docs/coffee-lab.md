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
counting it at any time. An unopened bag given its size is counted from
that size at its first brew, since a sealed bag holds what it was sold as.

A bag is **unopened**, then **open** from its first brew, then **finished**
once a brew leaves 5 g or less, or when you mark it with
`xbloom.finish_bag`. Finishing is refused for an unopened bag, and for a
tracked bag still showing 20 g or more — weigh it and start tracking again
first. A finished bag keeps its brews.

Bags are named by their name, or by their id when two bags share one; a shared
name is refused rather than guessed.

A bag's **country**, **process**, **variety** and **roast** are kept in the
[community hub](recipes.md#community-recipes)'s English names — "ethiopia",
the country's name in Arabic or Chinese, "Anaerobic", "gesha" or "light" become
"Ethiopia", "Anaerobic Fermentation", "Geisha/Gesha" and "Light Roast" — so
bags of the same coffee match each other and the hub. Several varieties are
separated by commas, and each is checked. A name the hub does not list is kept
as typed, and the action's response names it under `not_on_hub`. The
**roaster notes** stay as written; the hub's flavor names found in them are
what community suggestions match. A bag can also say where and when its
coffee was made: its **producer** (the farmer, farm, cooperative or washing
station), the **altitude** it was grown at, in metres, one height or a range,
and the **roast date**. Where it has one, a bag can keep its **shop page**, a
web link, which the Bags tab links to.

## Coffee, xPod boxes and tea

An item is a **bag of coffee**, a **box of xPods** or a **tea** — its kind,
set when it is added or edited. A brew draws from the kind its recipe's cup
takes: a coffee brew takes its dose from **Coffee bag**, an xPod brew takes
**one pod** from **xPod box**, and a tea brew takes its grams from **Tea**.
An xPod or tea brew is never charged to a bag of coffee, and with nothing of
its kind in use it is recorded against nothing. Only a coffee recipe needs a
bag chosen before it is prepared.

On the Brew tab, what you brew from comes first: the bag, and the xPod box or
tea when there are any. The recipe is offered once one is chosen, or at once
when there is nothing to choose, or when a recipe was already picked from a
suggestion, an assistant or an automation. Once a recipe is picked, only the
picker for what it draws from stays.

A box is counted in **pods** — give how many it holds when adding it — and is
finished when the last is used. When the machine reads a pod's recipe card
while Connect holds the link, the box in use keeps it if the card is its own,
and learns the card if it has none yet; otherwise a box that knows the card is
put in use, an open one before an unopened one.

Changing an item between a box and a bag or tea clears its amount, since pods
and grams do not convert; give the new amount to count it again. An xPod brew
stopped after grinding is recorded for review against its box, as a coffee
brew is against its bag; a stopped tea brew is not recorded, since tea is not
ground.

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
| From an open, untracked bag | Recorded against the bag; nothing subtracted |
| With no bag chosen | Recorded for review (`no_bag`) |
| Larger than what the bag shows | Recorded for review (`more_than_left`); the bag is left as it is |
| From a finished bag | Recorded for review (`bag_closed`) |
| From a tracked bag with no amount | Recorded for review (`tracked_without_amount`) |
| Stopped after the grinder ran | Recorded for review (`stopped_after_grinding`), since its coffee was used |

A brew recorded for review shows on **Last brew counted** as *Needs review*,
with the reason in its attributes. A brew started from the machine's own
controls runs no Home Assistant brew and is not counted.

Coffee made another way — a V60, say — is recorded with **Manual brewer**,
**Manual brew dose** and **Record manual brew**, or `xbloom.consume`; it takes
its coffee from the bag in use, so the Brew tab offers it once a bag is
chosen. The brewers offered are yours to set in **Configure → Coffee Lab**.

**A brew is never lost when the record cannot be reached** — Notion down, or
the network away. It waits in Home Assistant with the time it was brewed, is
tried again every five minutes, and is saved once. **Waiting brews** counts
them; after an hour a repair says so.

## How was it

A while after a brew, Coffee Lab asks how it was: **Brew to rate** names the
recipe and the bag a quarter of an hour after the last cup, when the coffee can
have been tasted, and **Verdict** answers it — **Keep it like this**,
**Close, needs a tweak** or **Doesn't suit this coffee**. Unanswered, the question goes after a day.

A question is asked once for a recipe with a bag at one grind and ratio —
the dose is how much is made, so it makes no question of its own —
and not again once it has a verdict. Cups of the same one brewed close
together share a question, and its answer is kept on each of them; a
different recipe, bag or setting gets a question of its own. Up to three are
open at once, asked oldest first.

Beside the verdict, how it tasted can be kept — body, acidity, sweetness and
clarity, how it was hot, warm and cool, overall, the finish — and a **Next
change**, such as "grind 52", with the `xbloom.rate_brew` action or by telling
an AI assistant. Only what is given is kept.

After a verdict of **Close, needs a tweak**, **What was wrong** is asked
next, for as long as the question would have stayed open. Its answer sets the
Next change for you, counted from the grind and ratio the cup was brewed at:

| Answer | Next change |
|---|---|
| Sour | grind 3 steps finer |
| Bitter | grind 3 steps coarser |
| Too weak | ratio one step stronger, such as 1:16 to 1:15 |
| Too strong | ratio one step lighter |
| Nothing | no change |

Answers build on each other, since each counts from the version brewed, but
never move the grind more than 6 steps from the saved recipe's; past that, or
for a recipe that does not grind, nothing is set and a change can still be
given in words. The action and the AI tools take it as `issue`: `sour`,
`bitter`, `weak`, `strong` or `none`.

The question can also be asked
for you: by an AI assistant that started the brew, through its
[callback](events.md#callbacks), or by the **Ask how the coffee was**
[blueprint](automations.md#ready-made-blueprints), on a phone or aloud.

### Trying a change

The next time the recipe is picked with that bag, **Next Change** offers the
change asked for, and **Use Next Change** sets the Brew tab's one-off
adjustments to it; the saved recipe stays as it is. The versions tried and
their verdicts are side by side on the Brew tab. A changed version rated
**Keep it like this** is offered to keep, as **Version to Keep**: **Make Version the
Recipe** changes the saved recipe, **Save Version as New Recipe** keeps both,
and **Leave Recipe Unchanged** keeps neither and closes the offer.

### A recipe for this bag

Choosing a bag looks for a recipe for it at once, and **Suggest Recipe** looks
again: your own first,
ranked by how close the bags they were brewed with are — this bag, then the
same origin and process, then the same origin — and by their verdicts, with
a recipe last rated **Doesn't suit this coffee** with this bag left out — and, after them,
[community recipes](recipes.md#community-recipes) for coffee like it, the
closest to the bag's process, variety, roast and roaster notes first. **Suggested Recipe** offers them all, your own first and
each community one marked as such, with the best already chosen; its
attributes say why the chosen one was suggested. **Use Suggested Recipe**
picks it for brewing, adding a community recipe to your library first.

**Drink** — Any, Hot or Iced — keeps the suggestions to that drink, your own
and the community's, and asks again for the bag in use when it changes. A
recipe is iced when it pours 12 parts of water to its coffee or fewer: iced
recipes brew about 1:8 to 1:10 straight onto ice, hot ones about 1:14 to 1:18.

**Taste** — Balanced, Less sour or Less bitter — moves this brew's grind from
the picked recipe's: three steps finer for less sour, three coarser for less
bitter, never past the grinder's range. **Brew Grind Size** shows the result,
and the saved recipe is not changed; the brew's version records the grind it
was made at. Nothing moves while Use Grinder is off, or for a recipe that does
not grind. Taste goes back to Balanced once a brew has used its coffee, and
when another bag is chosen.

### Buy it again?

When a bag is finished, **Finished bag** names it for a week, and **Buy
again** keeps whether you would buy it again — yes, maybe or no.

## Running low

Coffee Lab keeps a **stock** figure for each kind the home has had — coffee,
xPod boxes, tea — counted over every item on hand: a counted item by what is
left, an unopened one not yet counted by its size. Choose what it is counted
in with **Stock measure** — days, grams, cups or bags (for tea, packs: its
tins or pouches); for xPods days, pods or boxes — and below which it is running low with **Stock level** (0 turns it
off). Days and cups come from the last 30 days of brews of that kind, each brew
counting half as much a week older, so the figure follows a change of habit
within days; they need at least five brews.

An item whose amount is not known — opened before it was counted — is left
out, and the figure becomes "at least" what is counted: it never turns low on
that alone, since the item left out is usually not empty. Weigh it with
`start_tracking` and the figure is whole again. Bags are always counted.

When a kind falls below its level, `xbloom_stock_low` fires and, when they are
set under **Configure → Coffee Lab**, the kind goes on the **Shopping list**
(unless an open item of that name is already there) and the **Phone** is told
once. When it rises back — a new bag — `xbloom_stock_restored` fires and the
item Coffee Lab added is ticked off; an item someone wrote is never changed.
A finished bag answered **buy again: yes**, with no other bag of that coffee on
hand, goes on the list by name and fires `xbloom_buy_again`. The first look
after this is installed only records where things stand.

The Bags tab shows what is left of each kind at any time. The Brew tab says
so only while what the picked recipe draws from is running low. The AI tools
see it too, mentioning a low stock once while already talking about coffee.

## Opening bags

Coffee fades once its bag is open, so Coffee Lab keeps few coffee bags open
and says when to open the next. Three settings, on the dashboard's Bags tab:

| Setting | Default | What it does |
|---|---|---|
| **Open bags at once** | 2 | Above this, no sealed bag is named to open |
| **Rest after roasting** | 7 days | A sealed bag roasted more recently waits for an older one |
| **Open bag fades after** | 28 days | An open bag open longer is past its best |

A sealed bag is named to open next — **Coffee bags**' `open_next` — when fewer
bags are open than the limit and what is left in them is two usual doses or
less, or when no open bag holds a dose. It is the oldest roast that has
rested; with none rested, the oldest roast. An open bag past its best is
listed in `fading`. The usual dose is the hot dose brewed most over the last
30 days, else their average, else 15 g.

## Today's cup

**Today's cup** is the cup to brew next: an open bag, a recipe for it and the
dose, with the reasons it was chosen. It is worked out again when Coffee Lab
changes, when the Drink setting changes, at midnight and when a brew ends —
not while one runs.

- **The bag**, among the open bags holding a dose: a liked coffee first —
  liked when any recipe was rated *Keep it like this* with it or the same
  coffee before, not liked when every recipe tried was rated *Doesn't suit
  this coffee*, and a **Buy again** answer settles it; between coffees liked
  alike, not the one brewed last; and a bag that would pass its best before
  it is finished at that pace is brewed more. A bag past its best only when
  nothing else qualifies; with no open bag holding a dose, the sealed bag to
  open next.
- **The recipe**: those rated *Keep it like this* with the bag, taking turns;
  then its other recipes, from the brews with it or with coffee like it; else
  a [community recipe](recipes.md#community-recipes) for it; else none.
- **The dose**: the usual dose for the drink, within what the recipe's cup
  takes; for iced with no usual iced dose, the recipe's own.

It is offered once a day: on the Brew tab until the day's first coffee is
brewed, then not again until the next day. When the first cup of the day has
a habit — at least ten of the last 30 days, the middle 60 % of them within
four hours of each other — it appears an hour before the early end of that
range rather than at midnight. A brew given a date but no time says nothing
about the hour and is left out of it.
Asked for, an AI assistant offers it at any time, for a second cup.

**Use today's cup** picks the bag, the recipe — adding a community one to the
library first — and the dose on the Brew tab, which prepares the machine; the
brew is started as any other. **Another cup** offers the next one.

**Today's cup** carries `bag`, `bag_id`, `recipe`, `source` (`own` or
`community`), `hub_id`, `drink`, `dose_g`, `due` (offered now), `shows_from`
(the usual time, when there is one) and `reasons`: for the bag `liked`,
`not_yesterday`, `use_soon`, `past_best` or `open_next`; for the recipe
`rated_again`, `brewed_with_bag`, `like_this_coffee` or `community`.

## How you brew

For the period chosen in **Stats period**, **Brews** also says how its cups
were made, under `habits`:

| Habit | What it is |
|---|---|
| `days_brewed`, `days_in_period` | Days with a brew, out of the days in the period so far |
| `longest_streak_days` | The most days in a row with a brew |
| `cups_per_brewing_day` | Cups on a day with a brew |
| `usual` | For `hot` and `iced`: the dose and ratio brewed most, from three brews of that drink or more |
| `top_coffee`, `top_recipe` | The coffee and the recipe brewed most, with how many times; bags of a coffee bought again count as one coffee |
| `verdicts` | How many cups got each verdict |
| `time_of_day` | `morning`, `afternoon`, `evening` or `night`, only when at least five cups were brewed and most of them at that time |
| `bags_opened` | Bags of coffee opened in the period |

A cup is hot or iced by its ratio, as for suggestions. Tea and brews without
a ratio, such as most manual brews, set no usual dose, and a brew stopped
after grinding is not a cup. The AI tools' stats return the same.

`habits` also lists each coffee of the period with its cups and the grams
they took (`by_coffee`), and each recipe with its cups and the verdicts it was
given (`by_recipe`), most brewed first. A brew stopped after grinding is not a
cup, so these grams can be fewer than the coffee used.

**Recent brews** is the time of the newest brew in the **Stats period**, with
that period's brews as its `brews` attribute, newest first and up to 50 —
recipe, bag, dose, how it was brewed, the verdict, tasting and next change, as
`brew_history` gives them — for a dashboard to show each one.

**Brew history** counts the brews in the record that made coffee, with brews,
coffee and water for each of the last twelve months since the first brew
(`by_month`) and each of the last eight weeks, Monday to Sunday (`by_week`),
this one first: the numbers the charts draw, to be read. It is worked out
again after each change and at midnight.

## Entities and actions

**Coffee bag** (the bag in use), **Coffee left**, **Coffee bags** (with every
bag as an attribute), **Brews** and **Stats period**, **Recent brews**, **Brew history**, **Last brew counted**,
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
kept, as are Kind, Pods Left, Pod ID, Variety, Roast, Producer, Altitude m, Altitude Max m and
Roast Date in Coffee Beans.
A select option the database lacks — a new brewer,
say — is added before it is used. A bag added or changed in Notion itself
appears within ten minutes, or at once with **Refresh Coffee Bags**.
