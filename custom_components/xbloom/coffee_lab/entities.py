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

from ..tool_common import refuse
from ..const import DOMAIN, SIGNAL_COFFEE_LAB_UPDATED
from . import actions
from .lab import CoffeeLab
from .inventory import kind_of_cup
from .models import BUY_AGAIN, ISSUES, KINDS, VERDICTS, Bean
from .stats import PERIODS, UNKNOWN_BREWER as OTHER_BREWER

_LOGGER = logging.getLogger(__name__)

# The recipe picker, whose pick decides which kind of item a brew draws from.
RECIPE_SELECT = "select.xbloom_studio_recipe"
# The results a count can have, as the last-count sensor's states.
COUNT_RESULTS = ["counted", "recorded", "skipped", "flagged", "queued"]
# How often the question's sensor looks at the clock.
QUESTION_TICK = timedelta(minutes=1)


def bag_labels(beans: list[Bean]) -> dict[str, str]:
    """A label per bag, unique: a name shared by two bags is numbered.

    Held by id underneath, so a label is only ever what a person picks from.
    """
    labels: dict[str, str] = {}
    seen: dict[str, int] = {}
    for bean in beans:
        seen[bean.name] = seen.get(bean.name, 0) + 1
        labels[bean.id] = bean.name if seen[bean.name] == 1 else f"{bean.name} {seen[bean.name]}"
    return labels


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
        self._attr_extra_state_attributes = {"bags": [actions.bean_facts(b) for b in beans]}


class StatsSensor(CoffeeLabEntity, SensorEntity):
    """Brews in the chosen period; the rest of the totals as attributes."""

    _attr_icon = "mdi:chart-bar"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "stats")

    async def async_read(self) -> None:
        facts = await actions.stats(self.lab, {"period": self.lab.stats_period})
        self._attr_native_value = facts.pop("brews")
        self._attr_extra_state_attributes = facts


class RatingQuestionSensor(CoffeeLabEntity, SensorEntity):
    """The brew waiting for its verdict, once it is due: its recipe as state.

    Unknown while there is none, or before it is due, so a dashboard shows the
    question only when it should be asked. Re-read each minute, since being
    due is a matter of time, not of anything changing.
    """

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
             "changes": question.get("changes") or []}
            if question else {}
        )


class RateBrewSelect(CoffeeLabEntity, SelectEntity):
    """The verdict on the brew in question; picking one answers it."""

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
    """What was wrong with a brew just rated Fine or Not again.

    Available only while one waits to be asked; picking an answer sets its
    Next Change (Nothing sets none) and the question goes.
    """

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

    _attr_icon = "mdi:sack-outline"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "bag_question")

    async def async_read(self) -> None:
        question = self.lab.bag_question
        self._attr_native_value = question["name"] if question else None


class BuyAgainSelect(CoffeeLabEntity, SelectEntity):
    """Would the finished bag's coffee be bought again; picking one answers it."""

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
            RemainingSensor, BagsSensor, StatsSensor, LastCountSensor, WaitingBrewsSensor,
            RatingQuestionSensor, BagQuestionSensor, RecipeKindSensor,
        ],
        "number": [ManualDoseNumber],
        "button": [RecordManualBrewButton],
    }
    # Only a store edited elsewhere — Notion — can be out of date here.
    if lab.store.remote:
        makers["button"].append(RefreshBagsButton)
    return [make(lab) for make in makers.get(platform, [])]
