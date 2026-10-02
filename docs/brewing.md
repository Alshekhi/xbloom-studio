# Brewing

## Picking a recipe prepares it

Picking a recipe in the **Recipe** select sends it to the machine straight away,
with the settings on the brew customizer (**Brew Dose**, **Brew Ratio**, **Brew
Grind Size**, **Use Grinder**). With Coffee Lab on, a bag has to be picked too.
Connect is turned on for this if it is off.

Changing a setting sends the recipe again with the new values. A change made
while a send is still under way replaces it, so the machine only ever receives
your latest settings.

**Recipe Ready** is on while the machine holds exactly what **Start Brew**
would send. While it is off, its `reason` attribute says why — a bag not
picked, the machine out of range, a brew running, or what the machine
answered — and `preparing` is true while a send is waiting or under way. The
dashboard shows Start Brew only while the recipe is ready.

**Start Brew** then sends only the start, so grinding begins within a few
seconds. If a send is still under way when you press it, it is finished first,
so a brew never starts with older settings.

## Starting at the machine

With a recipe prepared, the machine shows it on its screen, and its right knob
starts it. That brew is followed exactly like one started from Home Assistant:
it is announced, its pours are counted, its completion is recorded, and
**Pause Brew**, **Resume Brew** and **Cancel Brew** work on it.

A brew started from one of the machine's own recipe slots, which Home
Assistant did not send, is still followed by **Brew Status**, and the brew
announcements say it started, without a recipe name.

## Pause and resume

**Pause Brew** and **Resume Brew** work while grinding or pouring. **Brew
Paused** follows the machine itself, so it is right whether the brew was
paused from Home Assistant or with the machine's knob, and the dashboard shows
Pause or Resume by it.

## Changing your mind

**Cancel Preparation** takes the recipe back from the machine and unpicks it;
the bag stays picked. Turning **Connect** off does the same.

## After a brew

A brew that made coffee unpicks the recipe and the bag, so the next brew
starts from a fresh pick. A brew that made none — no beans in the grinder, or
stopped before the grinder had run for 10 seconds — unpicks the recipe and
keeps the bag, ready to pick again.

Connect is turned off after a brew only if picking the recipe turned it on.
A session you turned on yourself stays on. After a brew that made no coffee,
a Connect that picking turned on stays on for the next pick, and is turned
off after five minutes if nothing is picked.

## Brewing over a Connect session

While **Connect** is on, a brew goes over that session instead of opening a
connection of its own. The session stays on through the brew, so live
readings keep arriving and the brew starts without reconnecting.

## From an automation or a script

`xbloom.prepare_brew` makes the same picks the dashboard does — a recipe, and
optionally `dose`, `ratio`, `grind_size`, `use_preground`, and with Coffee Lab
on `bean_id` or `unattributed` — and sends them. With `wait` on (the default)
it answers once the machine has accepted the recipe, or raises why not.
Pre-ground coffee asked for here applies to this brew only. A later
`xbloom.start_brew` for the same recipe and settings then sends only the
start. `xbloom.cancel_preparation` does what the Cancel Preparation button
does.
