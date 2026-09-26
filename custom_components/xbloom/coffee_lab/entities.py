"""Coffee Lab's entities, added only while it is switched on.

Each reads the lab and re-reads whenever the lab says something changed, so a
bag added by the AI tool, a brew counted on completion and a choice made on the
dashboard all show at once. Names and states are translation keys.
"""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfMass
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from ..const import DOMAIN, SIGNAL_COFFEE_LAB_UPDATED
from . import actions
from .lab import CoffeeLab
from .models import Bean
from .stats import PERIODS, UNKNOWN_BREWER as OTHER_BREWER

# The results a count can have, as the last-count sensor's states.
COUNT_RESULTS = ["counted", "recorded", "skipped", "flagged"]


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
        await self.async_read()
        self.async_write_ha_state()

    async def async_read(self) -> None:
        """Read what this entity shows from the lab."""


# ── Selects ──────────────────────────────────────────────────────────────────


class ActiveBagSelect(CoffeeLabEntity, SelectEntity):
    """The bag the xBloom draws from when a brew names none."""

    _attr_icon = "mdi:sack"

    def __init__(self, lab: CoffeeLab) -> None:
        super().__init__(lab, "active_bag")
        self._ids_by_label: dict[str, str] = {}
        # Home Assistant reads the options while registering the entity,
        # before it is added and has read the bags.
        self._attr_options = []

    async def async_read(self) -> None:
        beans = await self.lab.store.async_list_beans()
        labels = bag_labels(beans)
        self._ids_by_label = {label: bean_id for bean_id, label in labels.items()}
        self._attr_options = list(labels.values())
        active = await self.lab.async_active_bean()
        self._attr_current_option = labels.get(active.id) if active else None
        self._attr_extra_state_attributes = actions.bean_facts(active) if active else {}

    async def async_select_option(self, option: str) -> None:
        await self.lab.async_select(self._ids_by_label[option])


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


def entities_for(lab: CoffeeLab | None, platform: str) -> list[Entity]:
    """The Coffee Lab entities of one platform, or none when it is off."""
    if lab is None:
        return []
    makers: dict[str, list[Callable[[CoffeeLab], Entity]]] = {
        "select": [ActiveBagSelect, StatsPeriodSelect, ManualBrewerSelect],
        "sensor": [RemainingSensor, BagsSensor, StatsSensor, LastCountSensor],
        "number": [ManualDoseNumber],
        "button": [RecordManualBrewButton],
    }
    return [make(lab) for make in makers.get(platform, [])]
