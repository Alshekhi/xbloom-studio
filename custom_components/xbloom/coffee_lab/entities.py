"""Coffee Lab's entities, added only while it is switched on.

Each reads the lab and re-reads whenever the lab says something changed, so a
bag added by the AI tool, a brew counted on completion and a choice made on the
dashboard all show at once. Names and states are translation keys.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfMass
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from ..tool_common import refuse
from ..const import DOMAIN, SIGNAL_COFFEE_LAB_STOCK, SIGNAL_COFFEE_LAB_UPDATED
from . import actions
from .lab import CoffeeLab, focus_text
from .inventory import kind_of_cup
from .models import BUY_AGAIN, ISSUES, KINDS, VERDICTS, Bean
from .stats import PERIODS, UNKNOWN_BREWER as OTHER_BREWER
from .opening import USUAL_DAYS, fading, open_next, usual_dose
from .todays_cup_runtime import SIGNAL_TODAYS_CUP
from .stock import MEASURES, figure, floor

_LOGGER = logging.getLogger(__name__)

# The recipe picker, whose pick decides which kind of item a brew draws from.
RECIPE_SELECT = "select.xbloom_studio_recipe"
# The results a count can have, as the last-count sensor's states.
COUNT_RESULTS = ["counted", "recorded", "skipped", "flagged", "queued"]
# How often the question's sensor looks at the clock.
QUESTION_TICK = timedelta(minutes=1)
# How many of the latest brews Recent brews holds.
RECENT_BREWS = 10


def bag_labels(beans: list[Bean]) -> dict[str, str]:
    """A label per bag, unique.

    A name shared by several bags — a coffee bought again — carries each
    bag's roast date, which is what tells them apart; when the dates do not,
    the bags are numbered. Held by id underneath, so a label is only ever
    what a person picks from.
    """
    by_name: dict[str, list[Bean]] = {}
    for bean in beans:
        by_name.setdefault(bean.name, []).append(bean)
    labels: dict[str, str] = {}
    for name, bags in by_name.items():
        dates = [b.roast_date for b in bags]
        dated = len(bags) > 1 and all(dates) and len(set(dates)) == len(dates)
        for n, bean in enumerate(bags, start=1):
            if dated:
                labels[bean.id] = f"{name} ({bean.roast_date})"
            else:
                labels[bean.id] = name if n == 1 else f"{name} {n}"
    # Read in the order the bags came, as the picker shows them.
    return {bean.id: labels[bean.id] for bean in beans}


class CoffeeLabEntity(Entity):
    """Shared by every Coffee Lab entity: the device, and re-reading on change."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, lab: CoffeeLab, key: str) -> None:
        self.lab = lab
        self._attr_translation_key = f"coffee_lab_{key}"
        self._attr_unique_id = f"xbloom_coffee_lab_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "xbloom_studio")})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_COFFEE_LAB_UPDATED, self._changed)
        )
        await self.async_read()

    @callback
    def _changed(self) -> None:
        self.hass.async_create_task(self._async_read_and_write())

    async def _async_read_and_write(self) -> None:
        # A store that cannot be reached (Notion answering too slowly, say)
        # leaves the last values showing until the next read succeeds.
        try:
            await self.async_read()
        except HomeAssistantError as err:
            _LOGGER.warning("Coffee Lab: could not re-read %s: %s", self.entity_id, err)
            return
        self.async_write_ha_state()

    async def async_read(self) -> None:
        """Read what this entity shows from the lab."""


# ── Selects ──────────────────────────────────────────────────────────────────


class ActiveBagSelect(CoffeeLabEntity, SelectEntity):
    """The item of one kind the xBloom draws from when a brew names none.

    One each for a bag of coffee, an xPod box and a tea: a brew draws from the
    one its cup type takes.
    """

    _attr_icon = "mdi:sack"
    _kind = "coffee"
    _key = "active_bag"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, self._key)
        self._ids_by_label: dict[str, str] = {}
        # Home Assistant reads the options while registering the entity,
        # before it is added and has read the bags.
        self._attr_options = []

    async def async_read(self) -> None:
        beans = [b for b in await self.lab.store.async_list_beans() if b.kind == self._kind]
        labels = bag_labels(beans)
        self._ids_by_label = {label: bean_id for bean_id, label in labels.items()}
        self._attr_options = list(labels.values())
        active = await self.lab.async_active_bean(self._kind)
        self._attr_current_option = labels.get(active.id) if active else None
        self._attr_extra_state_attributes = actions.bean_facts(active) if active else {}

    @property
    def available(self) -> bool:
        # With nothing of its kind to choose, there is no picker: the Brew tab
        # then offers the recipe without asking for one.
        return bool(self._attr_options)

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_select(self._ids_by_label[option])


class ActiveXpodBoxSelect(ActiveBagSelect):
    """The xPod box an xPod brew draws one pod from."""

    _attr_icon = "mdi:package-variant"
    _kind = "xpod"
    _key = "active_xpod_box"


class ActiveTeaSelect(ActiveBagSelect):
    """The tea a tea brew draws its grams from."""

    _attr_icon = "mdi:tea"
    _kind = "tea"
    _key = "active_tea"


class RecipeKindSensor(CoffeeLabEntity, SensorEntity):
    """What the picked recipe draws from: coffee, xpod or tea; unknown with none picked.

    The dashboard shows the matching picker by it, since a card's visibility
    cannot read the recipe's attributes.
    """

    _attr_icon = "mdi:shape-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(KINDS)

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "recipe_kind")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_state_change_event(
            self.hass, [RECIPE_SELECT], self._recipe_changed,
        ))

    @callback
    def _recipe_changed(self, _event) -> None:
        self._changed()

    async def async_read(self) -> None:
        recipe = self.hass.states.get(RECIPE_SELECT) if self.hass else None
        cup = (recipe.attributes.get("cup_type") if recipe else None)
        self._attr_native_value = kind_of_cup(cup) if cup is not None else None


class StatsPeriodSelect(CoffeeLabEntity, SelectEntity):
    """Which period the stats sensor totals."""

    _attr_options = list(PERIODS)
    _attr_icon = "mdi:calendar-range"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "stats_period")

    async def async_read(self) -> None:
        self._attr_current_option = self.lab.stats_period

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_set_stats_period(option)


# ── Sensors ──────────────────────────────────────────────────────────────────


class RemainingSensor(CoffeeLabEntity, SensorEntity):
    """What is left in the active bag; unknown when it is not counted."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    # Whole grams: "142 g", not "142.0 g" read out in full.
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:scale"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "remaining")

    async def async_read(self) -> None:
        active = await self.lab.async_active_bean()
        self._attr_native_value = (
            active.remaining_g if active is not None and active.tracked else None
        )


class BagsSensor(CoffeeLabEntity, SensorEntity):
    """How many bags can be brewed from, with each of them as an attribute."""

    _attr_icon = "mdi:sack"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "bags")

    async def async_read(self) -> None:
        beans = await self.lab.store.async_list_beans()
        self._attr_native_value = len(beans)
        now = dt_util.now()
        brews = await self.lab.store.async_list_brews(since=now - timedelta(days=USUAL_DAYS))
        rules = self.lab.opening
        nxt = open_next(beans, usual_dose(brews, now), now, rules)
        self._attr_extra_state_attributes = {
            "bags": [actions.bean_facts(b) for b in beans],
            # The sealed bag to open now, when it is time; the open ones past their best.
            "open_next": nxt.id if nxt else None,
            "fading": [b.id for b in beans if fading(b, now, rules)],
        }


class StatsSensor(CoffeeLabEntity, SensorEntity):
    """Brews in the chosen period; the rest of the totals as attributes."""

    _attr_icon = "mdi:chart-bar"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "stats")

    async def async_read(self) -> None:
        facts = await actions.stats(self.lab, {"period": self.lab.stats_period})
        self._attr_native_value = facts.pop("brews")
        self._attr_extra_state_attributes = facts


class RecentBrewsSensor(CoffeeLabEntity, SensorEntity):
    """When the newest brew was made; the latest brews, in full, as attributes.

    Each brew as brew_history gives it — recipe, bag, dose, how it was brewed,
    the verdict and tasting — so a dashboard can open one without an agent.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"
    # The list is re-read from the record whenever it is needed; keeping every
    # copy of it in the recorder's history would only fill the database.
    _unrecorded_attributes = frozenset({"brews"})

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "recent_brews")

    async def async_read(self) -> None:
        brews = (await actions.brew_history(self.lab, {"limit": RECENT_BREWS}))["brews"]
        # A brew typed in without a time has none to show; the newest with one.
        newest = next((b["brewed_at"] for b in brews if b.get("brewed_at")), None)
        self._attr_native_value = dt_util.parse_datetime(newest) if newest else None
        self._attr_extra_state_attributes = {"brews": brews}


class RatingQuestionSensor(CoffeeLabEntity, SensorEntity):
    """The brew waiting for its verdict, once it is due: its recipe as state.

    Unknown while there is none, or before it is due, so a dashboard shows the
    question only when it should be asked. Re-read each minute, since being
    due is a matter of time, not of anything changing.
    """

    _attr_entity_registry_visible_default = False  # see workflow_entities.py

    _attr_icon = "mdi:star-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "rating_question")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, QUESTION_TICK))

    @callback
    def _tick(self, _now) -> None:
        # A callback, so Home Assistant runs it in its event loop: a plain
        # function given to the timer runs in a worker thread, where
        # scheduling the re-read is unsafe.
        self._changed()

    async def async_read(self) -> None:
        question = self.lab.rating_question_due()
        self._attr_native_value = question["recipe"] if question else None
        self._attr_extra_state_attributes = (
            {"bag": question["bag"], "brew_id": question["brew_id"],
             "changes": question.get("changes") or [],
             # What was to be noticed in it, said when it was ready.
             "focus": focus_text(question)}
            if question else {}
        )


class RateBrewSelect(CoffeeLabEntity, SelectEntity):
    """The verdict on the brew in question; picking one answers it."""

    _attr_entity_registry_visible_default = False  # see workflow_entities.py

    _attr_icon = "mdi:star"
    _attr_options = list(VERDICTS)
    _attr_current_option = None

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "rate_brew")

    async def async_select_option(self, option: str) -> None:
        # Only the question the card shows: one not yet due is not shown, and
        # with none open nothing is rated.
        question = self.lab.rating_question_due()
        if question is None:
            raise refuse("rating_none")
        await self.lab.async_rate(verdict=option, brew_id=question["brew_id"])


class CupIssueSelect(CoffeeLabEntity, SelectEntity):
    """What was wrong with a brew just rated Fine.

    Available only while one waits to be asked; picking an answer sets its
    Next Change (Nothing sets none) and the question goes.
    """

    _attr_entity_registry_visible_default = False  # see workflow_entities.py

    _attr_icon = "mdi:help-circle-outline"
    _attr_options = list(ISSUES)
    _attr_current_option = None

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "cup_issue")

    @property
    def available(self) -> bool:
        return self.lab.issue_question is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        asked = self.lab.issue_question or {}
        return {"recipe": asked.get("recipe"), "bag": asked.get("bag")}

    async def async_select_option(self, option: str) -> None:
        asked = self.lab.issue_question
        if asked is None:
            raise refuse("rating_none")
        await self.lab.async_rate(issue=option, brew_id=asked["brew_id"])


class BagQuestionSensor(CoffeeLabEntity, SensorEntity):
    """A finished bag waiting to be asked about: its name, for a week."""

    _attr_entity_registry_visible_default = False  # see workflow_entities.py

    _attr_icon = "mdi:sack-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "bag_question")

    async def async_read(self) -> None:
        question = self.lab.bag_question
        self._attr_native_value = question["name"] if question else None


class BuyAgainSelect(CoffeeLabEntity, SelectEntity):
    """Would the finished bag's coffee be bought again; picking one answers it."""

    _attr_entity_registry_visible_default = False  # see workflow_entities.py

    _attr_icon = "mdi:cart-outline"
    _attr_options = list(BUY_AGAIN)
    _attr_current_option = None

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "buy_again")

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_rate_bag(option)


class WaitingBrewsSensor(CoffeeLabEntity, SensorEntity):
    """How many brews wait for the store; the oldest's error as an attribute."""

    _attr_icon = "mdi:cloud-upload-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "waiting_brews")

    async def async_read(self) -> None:
        self._attr_native_value = len(self.lab.pending)
        oldest = self.lab.pending.oldest
        self._attr_extra_state_attributes = (
            {"oldest_queued_at": oldest["queued_at"], "error": oldest.get("last_error")}
            if oldest else {}
        )


class LastCountSensor(CoffeeLabEntity, SensorEntity):
    """What the last brew did to the inventory; `flagged` needs a look."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = COUNT_RESULTS
    _attr_icon = "mdi:clipboard-check-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "last_count")

    async def async_read(self) -> None:
        last = dict(self.lab.last_count or {})
        self._attr_native_value = last.pop("result", None)
        self._attr_extra_state_attributes = {k: v for k, v in last.items() if v not in (None, {}, False)}


# ── Manual brews ─────────────────────────────────────────────────────────────


class ManualDoseNumber(CoffeeLabEntity, NumberEntity):
    """The dose of a brew made without the xBloom, before it is recorded."""

    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_icon = "mdi:coffee"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "manual_dose")

    async def async_read(self) -> None:
        self._attr_native_value = self.lab.manual_dose_g

    async def async_set_native_value(self, value: float) -> None:
        await self.lab.async_set_manual_dose(value)


class ManualBrewerSelect(CoffeeLabEntity, SelectEntity):
    """What made a brew recorded without the xBloom: the person's own brewers,
    as set in Configure, and `other`."""

    _attr_icon = "mdi:coffee-maker-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "manual_brewer")
        self._attr_options = [*lab.brewers, OTHER_BREWER]

    async def async_read(self) -> None:
        brewer = self.lab.manual_brewer
        self._attr_current_option = brewer if brewer in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_set_manual_brewer(option)


class RecordManualBrewButton(CoffeeLabEntity, ButtonEntity):
    """Record the manual dose and brewer against the active bag."""

    _attr_icon = "mdi:coffee-to-go"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "record_manual_brew")

    async def async_press(self) -> None:
        # What it did shows on the last-count sensor; a refusal is raised.
        await actions.record_manual_brew(self.lab, {})


class RefreshBagsButton(CoffeeLabEntity, ButtonEntity):
    """Re-read the bags now, from a store that can change outside Home Assistant."""

    _attr_icon = "mdi:refresh"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "refresh_bags")

    async def async_press(self) -> None:
        self.lab.on_change()


# ── Stock ────────────────────────────────────────────────────────────────────

# The level number's range and step for each measure, and its unit.
_LEVEL_RANGE: dict[str, tuple[float, float, str | None]] = {
    "days": (60, 1, "d"), "grams": (2000, 10, UnitOfMass.GRAMS), "cups": (100, 1, None),
    "bags": (10, 1, None), "pods": (100, 1, None), "boxes": (10, 1, None),
}


def _whole(value: float | None) -> int | None:
    return None if value is None else round(value)


class StockEntity(CoffeeLabEntity):
    """One kind's stock: re-read when it is worked out again, and when its
    level or measure changes. Unavailable while the home has never had the kind."""

    def __init__(self, lab: CoffeeLab, kind: str, key: str) -> None:
        super().__init__(lab, f"{kind}_{key}")
        self.kind = kind

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_COFFEE_LAB_STOCK, self._changed))

    def _stock(self):
        stock = self.lab.stock.get(self.kind)
        self._attr_available = bool(stock is not None and stock.kept)
        return stock if self._attr_available else None


class StockSensor(StockEntity, SensorEntity):
    """What is left of a kind, in the measure chosen for it; every figure as attributes."""

    _attr_icon = "mdi:archive-outline"

    def __init__(self, lab: CoffeeLab, kind: str) -> None:
        super().__init__(lab, kind, "stock")

    async def async_read(self) -> None:
        stock = self._stock()
        measure = self.lab.stock_measure(self.kind)
        self._attr_native_unit_of_measurement = _LEVEL_RANGE[measure][2]
        if stock is None:
            self._attr_native_value, self._attr_extra_state_attributes = None, {}
            return
        value = figure(stock, measure)
        self._attr_native_value = _whole(value)
        amount = "pods" if self.kind == "xpod" else "grams"
        self._attr_extra_state_attributes = {
            "measure": measure, "level": _whole(self.lab.stock_level(self.kind)),
            "low": bool(self.lab.stock_low_state(self.kind)) and value is not None
                   and self.lab.stock_level(self.kind) > 0,
            # Shown when the figure is only a floor, with items not counted.
            "at_least": _whole(floor(stock, measure)) if value is None else None,
            "unknown": len(stock.unknown),
            amount: _whole(stock.amount), "bags": stock.bags,
            "cups": _whole(stock.cups), "days": _whole(stock.days),
        }


class StockLowBinarySensor(StockEntity, BinarySensorEntity):
    """On while a kind is below its level; off while its figure is not known."""

    _attr_icon = "mdi:basket-unfill"

    def __init__(self, lab: CoffeeLab, kind: str) -> None:
        super().__init__(lab, kind, "stock_low")

    async def async_read(self) -> None:
        stock = self._stock()
        known = stock is not None and figure(stock, self.lab.stock_measure(self.kind)) is not None
        self._attr_is_on = bool(
            known and self.lab.stock_level(self.kind) > 0 and self.lab.stock_low_state(self.kind))


class StockMeasureSelect(StockEntity, SelectEntity):
    """What a kind's stock is counted in."""

    _attr_icon = "mdi:ruler"

    def __init__(self, lab: CoffeeLab, kind: str) -> None:
        super().__init__(lab, kind, "stock_measure")
        self._attr_options = list(MEASURES[kind])

    async def async_read(self) -> None:
        self._stock()
        self._attr_current_option = self.lab.stock_measure(self.kind)

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_set_stock_measure(self.kind, option)


class StockLevelNumber(StockEntity, NumberEntity):
    """Below this, a kind is running low; 0 turns the reminder off."""

    _attr_icon = "mdi:basket-minus-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0

    def __init__(self, lab: CoffeeLab, kind: str) -> None:
        super().__init__(lab, kind, "stock_level")

    async def async_read(self) -> None:
        self._stock()
        top, step, unit = _LEVEL_RANGE[self.lab.stock_measure(self.kind)]
        self._attr_native_max_value, self._attr_native_step = top, step
        self._attr_native_unit_of_measurement = unit
        self._attr_native_value = _whole(self.lab.stock_level(self.kind))

    async def async_set_native_value(self, value: float) -> None:
        await self.lab.async_set_stock_level(self.kind, value)


class TodaysCupSensor(CoffeeLabEntity, SensorEntity):
    """Today's cup: the bag as state; the recipe, dose and reasons as attributes."""

    _attr_icon = "mdi:coffee-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "todays_cup")
        # Named here: "Today's" would otherwise give "today_s".
        self.entity_id = "sensor.xbloom_studio_todays_cup"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_TODAYS_CUP, self._changed))

    async def async_read(self) -> None:
        cup = getattr(self.lab, "todays_cup", None)
        pick = cup.pick if cup is not None else None
        self._attr_native_value = pick.bag if pick else None
        self._attr_extra_state_attributes = {
            "bag_id": pick.bag_id, "bag": pick.bag, "recipe": pick.recipe,
            "source": pick.recipe_source, "hub_id": pick.hub_id, "drink": pick.drink,
            "dose_g": pick.dose_g, "reasons": list(pick.reasons),
        } if pick else {}


class _TodaysCupButton(CoffeeLabEntity, ButtonEntity):
    def _cup(self):
        cup = getattr(self.lab, "todays_cup", None)
        if cup is None:
            raise refuse("suggestion_none")
        return cup


class UseTodaysCupButton(_TodaysCupButton):
    """Pick today's cup on the Brew tab: bag, recipe and dose. Nothing is started."""

    _attr_icon = "mdi:check"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "use_todays_cup")
        # Named here: "Today's" would otherwise give "today_s".
        self.entity_id = "button.xbloom_studio_use_todays_cup"

    async def async_press(self) -> None:
        await self._cup().async_use()


class AnotherCupButton(_TodaysCupButton):
    """The next cup on offer."""

    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "another_cup")
        # Named here: "Today's" would otherwise give "today_s".
        self.entity_id = "button.xbloom_studio_another_cup"

    async def async_press(self) -> None:
        await self._cup().async_another()


class _OpeningNumber(CoffeeLabEntity, NumberEntity):
    """One of the opening rules: a setting kept in Coffee Lab's state."""

    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _setting = ""

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, f"opening_{self._setting}")
        from .lab import OPENING_RANGES
        self._attr_native_min_value, self._attr_native_max_value = OPENING_RANGES[self._setting]

    async def async_read(self) -> None:
        self._attr_native_value = getattr(self.lab.opening, self._setting)

    async def async_set_native_value(self, value: float) -> None:
        await self.lab.async_set_opening(**{self._setting: int(value)})


class OpenLimitNumber(_OpeningNumber):
    _setting = "limit"
    _attr_icon = "mdi:sack-outline"


class RestDaysNumber(_OpeningNumber):
    _setting = "rest_days"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = "d"


class FadeDaysNumber(_OpeningNumber):
    _setting = "fade_days"
    _attr_icon = "mdi:weather-windy"
    _attr_native_unit_of_measurement = "d"


def entities_for(lab: CoffeeLab | None, platform: str) -> list[Entity]:
    """The Coffee Lab entities of one platform, or none when it is off."""
    if lab is None:
        return []
    makers: dict[str, list[Callable[[CoffeeLab], Entity]]] = {
        "select": [
            ActiveBagSelect, ActiveXpodBoxSelect, ActiveTeaSelect, StatsPeriodSelect,
            ManualBrewerSelect, RateBrewSelect, CupIssueSelect, BuyAgainSelect,
        ],
        "sensor": [
            RemainingSensor, BagsSensor, StatsSensor, RecentBrewsSensor, LastCountSensor, WaitingBrewsSensor,
            RatingQuestionSensor, BagQuestionSensor, RecipeKindSensor, TodaysCupSensor,
        ],
        "number": [ManualDoseNumber, OpenLimitNumber, RestDaysNumber, FadeDaysNumber],
        "button": [RecordManualBrewButton, UseTodaysCupButton, AnotherCupButton],
    }
    # Only a store edited elsewhere — Notion — can be out of date here.
    if lab.store.remote:
        makers["button"].append(RefreshBagsButton)
    stock = {"sensor": StockSensor, "binary_sensor": StockLowBinarySensor,
             "select": StockMeasureSelect, "number": StockLevelNumber}
    per_kind = [stock[platform](lab, kind) for kind in KINDS] if platform in stock else []
    return [make(lab) for make in makers.get(platform, [])] + per_kind
