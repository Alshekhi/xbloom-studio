"""Versions of a recipe with a bag: what was changed, how each was, what next.

A version is a recipe brewed with a bag at a grind, ratio and dose
(`coffee_lab.lab.brew_version`). The brew record holds every version tried
and the verdicts given, so from it come:

  * the rated versions side by side, so the better one is not a memory;
  * the change asked for last time (Next Change), offered for the next brew
    of that recipe with that bag as one press that sets the Brew tab's
    one-off adjustments — the saved recipe is not touched;
  * after a changed version is rated Again, keeping it: as the recipe itself,
    or as a new recipe beside it.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .coffee_lab.lab import CoffeeLab, brew_version, normalize_ratio
from .coffee_lab.inventory import kind_of_cup
from .coffee_lab.models import VERDICT_OF, Brew
from .const import DOMAIN, SIGNAL_COFFEE_LAB_UPDATED
from .tool_common import fail

_LOGGER = logging.getLogger(__name__)

# How far back versions are looked for: as far as the question looks.
LOOKBACK = timedelta(days=365)
RECIPE_SELECT = "xbloom_recipe_select"
BAG_SELECT = "xbloom_coffee_lab_active_bag"
# The xPod box and tea in use: an xPod or tea recipe's versions are its own.
ITEM_SELECTS = (BAG_SELECT, "xbloom_coffee_lab_active_xpod_box", "xbloom_coffee_lab_active_tea")

# The Brew tab's one-off adjustments, by unique id, and the grinder switch a
# grind change needs on.
SLIDERS = {"grind": "xbloom_brew_grind", "ratio": "xbloom_brew_ratio", "dose_g": "xbloom_brew_dose"}
USE_GRINDER = "xbloom_use_grinder"

# A decimal point, a comma or the Arabic decimal separator (U+066B).
_NUMBER = r"\d+(?:[.,\u066b]\d+)?"
# What a "next time" note can name: a setting's word, in English or Arabic,
# followed by its value — "grind 52", "ratio 1:15", "dose 18 g", and the same
# with the Arabic word. A note saying where from and where to ("grind from 55
# to 56", or with the Arabic word for "to") means the second.
WORDS = {
    "grind": ("grind", "طحن"),
    "ratio": ("ratio", "نسبة"),
    "dose_g": ("dose", "جرعة"),
}
# "To", in English, in Arabic with and without the hamza, and as an arrow.
TO_WORDS = ("to", "إلى", "الى", "→", "->")
# An English word only at the start of a word ("duration" names no ratio); the
# Arabic words also arrive joined to a prefix, so they are matched anywhere.
_KEYWORDS = {
    key: "|".join(rf"\b{w}" if w.isascii() else w for w in words) for key, words in WORDS.items()
}
_ANY_KEYWORD = re.compile("|".join(_KEYWORDS.values()), re.IGNORECASE)
_TO = re.compile(
    "(?:" + "|".join(r"\bto\b" if w == "to" else re.escape(w) for w in TO_WORDS) + ")"
    + rf"\s*(?:1\s*:\s*)?({_NUMBER})",
    re.IGNORECASE,
)
_FIRST = re.compile(rf"(?:1\s*:\s*)?({_NUMBER})")


def parse_next_change(text: str) -> dict[str, float]:
    """The settings a "next time" note names, as numbers; the rest is ignored."""
    text = text or ""
    found = {}
    for key, keyword in _KEYWORDS.items():
        # Each mention in turn, until one is followed by a value: "grind finer,
        # grind 52" names 52.
        for match in re.finditer(keyword, text, re.IGNORECASE):
            # What follows this setting's name, up to the next one named.
            rest = text[match.end():]
            if (other := _ANY_KEYWORD.search(rest)) is not None:
                rest = rest[:other.start()]
            number = _TO.search(rest) or _FIRST.search(rest)
            if number is not None:
                found[key] = float(number.group(1).replace(",", ".").replace("\u066b", "."))
                break
    return found


def _same_pair(brew: Brew, recipe: str, bean_id: str) -> bool:
    return brew.bean_id == bean_id and (brew.recipe or "").casefold() == recipe.casefold()


def versions_of(brews: list[Brew], recipe: str, bean_id: str) -> list[dict[str, Any]]:
    """Each rated version of a recipe with a bag, with its latest verdict.

    Newest first. A version brewed often keeps the verdict it was last given.
    """
    seen: dict[tuple, dict[str, Any]] = {}
    for brew in brews:  # newest first, as every store returns them
        if brew.rating is None or not _same_pair(brew, recipe, bean_id):
            continue
        version = brew_version(brew.dose_g, brew.settings)
        key = tuple(version.values())
        if key in seen:
            seen[key]["brews"] += 1
            continue
        seen[key] = {**version, "verdict": VERDICT_OF.get(brew.rating), "brews": 1}
    return list(seen.values())


def pending_change(brews: list[Brew], recipe: str, bean_id: str) -> dict[str, Any] | None:
    """What the last brew of a recipe with a bag asked to change, if anything.

    Only the latest brew counts: once a brew has followed the change, there is
    nothing left to offer until someone asks for another.
    """
    for brew in brews:
        if not _same_pair(brew, recipe, bean_id):
            continue
        if not brew.next_change:
            return None
        return {
            "text": brew.next_change,
            "settings": parse_next_change(brew.next_change),
            "brewed_at": brew.brewed_at,
        }
    return None


class VersionDesk:
    """The Next Change and the version to keep, for the Brew tab's entities."""

    def __init__(self, hass: HomeAssistant, entry_id: str, lab: CoffeeLab, coordinator: Any) -> None:
        self._hass = hass
        self._lab = lab
        self._coordinator = coordinator
        self.signal = f"{DOMAIN}_versions_{entry_id}"
        self.next_change: dict[str, Any] | None = None
        self.recipe: str | None = None

    def _entity_id(self, platform: str, unique_id: str) -> str:
        entity_id = er.async_get(self._hass).async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id is None:
            raise fail("entity_missing", entity=f"{platform}.{unique_id}")
        return entity_id

    def _picked_recipe(self) -> str | None:
        state = self._hass.states.get(self._entity_id("select", RECIPE_SELECT))
        if state is None or state.state in ("unknown", "unavailable", ""):
            return None
        return state.attributes.get("name") or state.state

    async def async_refresh(self) -> None:
        """Read the Next Change for the picked recipe with the bag in use."""
        recipe = self._picked_recipe()
        # The item this recipe draws from: the bag, or the xPod box or tea.
        state = self._hass.states.get(self._entity_id("select", RECIPE_SELECT))
        kind = kind_of_cup(state.attributes.get("cup_type")) if state is not None else "coffee"
        bean_id = self._lab.active_id(kind)
        found = None
        if recipe and bean_id:
            since = dt_util.utcnow() - LOOKBACK
            found = pending_change(await self._lab.store.async_list_brews(since=since), recipe, bean_id)
        self.recipe, self.next_change = recipe, found
        async_dispatcher_send(self._hass, self.signal)

    async def async_use_next_change(self) -> None:
        """Set the one-off adjustments to what was asked for; the recipe stays."""
        settings = (self.next_change or {}).get("settings") or {}
        if not settings:
            raise fail("next_change_none")
        if "grind" in settings:
            await self._hass.services.async_call(
                "switch", "turn_on", {"entity_id": self._entity_id("switch", USE_GRINDER)}, blocking=True,
            )
        for key, value in settings.items():
            await self._hass.services.async_call(
                "number", "set_value",
                {"entity_id": self._entity_id("number", SLIDERS[key]), "value": value}, blocking=True,
            )

    async def async_keep_version(self, *, as_new: bool) -> str:
        """Keep the version rated Again: as the recipe itself, or as a new one."""
        from xbloom.brew_scale import scale_recipe

        keep = self._lab.version_to_keep
        if keep is None:
            raise fail("version_none")
        saved = next(
            (r for r in self._coordinator.data or [] if r.get("name") == keep["recipe"]), None,
        )
        if saved is None:
            raise fail("recipe_not_found", name=keep["recipe"], available="")
        version = keep["version"]
        scaled = scale_recipe(
            saved,
            dose_g=float(version["dose_g"] or saved["dose_g"]),
            ratio=float(version["ratio"] or normalize_ratio(saved)),
            grind_size=int(version["grind"] or saved.get("grinder_size") or 0),
        )
        if as_new:
            scaled.pop("id", None)
            scaled["name"] = f"{keep['recipe']} ({keep['label']})"
            await self._coordinator.async_add_recipe(scaled)
        else:
            await self._coordinator.async_replace_recipe(scaled)
        await self._lab.async_clear_version_to_keep()
        return scaled["name"]


# ── Entities ─────────────────────────────────────────────────────────────────


def entities_for(entry, platform: str) -> list:
    desk: VersionDesk | None = getattr(entry.runtime_data, "versions", None)
    if desk is None:
        return []
    return {
        "sensor": [NextChangeSensor(desk), VersionToKeepSensor(desk)],
        "button": [UseNextChangeButton(desk), KeepVersionButton(desk, as_new=False),
                   KeepVersionButton(desk, as_new=True)],
    }.get(platform, [])


class _VersionEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, desk: VersionDesk) -> None:
        self._desk = desk

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, "xbloom_studio")})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()  # type: ignore[misc]
        self.async_on_remove(  # type: ignore[attr-defined]
            async_dispatcher_connect(self.hass, self._desk.signal, self._redraw)  # type: ignore[attr-defined]
        )

    @callback
    def _redraw(self) -> None:
        self.async_write_ha_state()  # type: ignore[attr-defined]


class NextChangeSensor(_VersionEntity, SensorEntity):
    """The change asked for last time this recipe was brewed with this bag.

    Re-read whenever the recipe or the bag is picked, and whenever Coffee
    Lab's record changes.
    """

    _attr_translation_key = "next_change"
    _attr_unique_id = "xbloom_next_change"
    _attr_icon = "mdi:tune-variant"

    @property
    def native_value(self) -> str | None:
        return (self._desk.next_change or {}).get("text")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        found = self._desk.next_change or {}
        return {"recipe": self._desk.recipe, "settings": found.get("settings") or {}}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        watched = [
            eid for uid in (RECIPE_SELECT, *ITEM_SELECTS)
            if (eid := registry.async_get_entity_id("select", DOMAIN, uid))
        ]
        self.async_on_remove(async_track_state_change_event(self.hass, watched, self._changed))
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_COFFEE_LAB_UPDATED, self._changed))
        self.hass.async_create_task(self._async_refresh())

    @callback
    def _changed(self, _event: Event | None = None) -> None:
        self.hass.async_create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        try:
            await self._desk.async_refresh()
        except Exception as err:  # noqa: BLE001 — a store that cannot be read leaves the last value
            _LOGGER.warning("xbloom: could not read the next change: %s", err)


class VersionToKeepSensor(_VersionEntity, SensorEntity):
    """A changed version rated Again, waiting to be kept or let go: its recipe."""

    _attr_translation_key = "version_to_keep"
    _attr_unique_id = "xbloom_version_to_keep"
    _attr_icon = "mdi:trophy-outline"

    @property
    def native_value(self) -> str | None:
        keep = self._desk._lab.version_to_keep
        return keep["recipe"] if keep else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        keep = self._desk._lab.version_to_keep or {}
        return {"changes": keep.get("changes") or [], "label": keep.get("label")}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_COFFEE_LAB_UPDATED, self._redraw))


class UseNextChangeButton(_VersionEntity, ButtonEntity):
    _attr_translation_key = "use_next_change"
    _attr_unique_id = "xbloom_use_next_change"
    _attr_icon = "mdi:tune-variant"

    async def async_press(self) -> None:
        await self._desk.async_use_next_change()


class KeepVersionButton(_VersionEntity, ButtonEntity):
    def __init__(self, desk: VersionDesk, *, as_new: bool) -> None:
        super().__init__(desk)
        self._as_new = as_new
        self._attr_translation_key = "save_version_as_new" if as_new else "make_version_the_recipe"
        self._attr_unique_id = f"xbloom_{self._attr_translation_key}"
        self._attr_icon = "mdi:content-save-plus" if as_new else "mdi:content-save"

    async def async_press(self) -> None:
        await self._desk.async_keep_version(as_new=self._as_new)
