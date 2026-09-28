"""The `xbloom` AI tool: the machine, reachable from any agent.

One tool with an `action` argument, the same shape agents already call. Each
action is a call to one of this integration's services or a read of one of its
entities, so the tool adds no behaviour of its own to the machine.

**Facts, not sentences.** Every action returns structured fields and the agent
phrases them in whatever language it is speaking; a refusal raises a
translated error. Nothing here is prose a person reads.

**No rules about the machine.** Ranges, names and codes come from `xbloom.spec`;
adjusting a recipe to the machine is `xbloom.build_recipe`'s job. A hand-written
copy of either drifted before: room-temperature pours refused, the grinder's
default speed wrong, spiral and circular swapped.

**What a client is told an action needs lives in the description.** Home
Assistant's MCP server sends only each argument's type, values and description
— never which ones are required, and never a per-action rule — so each action's
line names its arguments, and the same table refuses a call without them.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.components.recorder import get_instance, history
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from xbloom import spec
from xbloom.recipe_validate import normalize_recipe

from .coffee_lab.actions import resolve_bean
from .coffee_lab.lab import CoffeeLab
from .const import DOMAIN
from .tool_common import Spec, check_arguments as _check, describe as _describe, fail, refuse

DEFAULT_HISTORY_DAYS = 7

# How long start_brew waits for the machine to take the brew. The service hands
# the brew to a background task and returns at once; `xbloom_brew_started` fires
# only when every step is accepted and `xbloom_brew_failed` when one is refused,
# so the answer waits for whichever comes first.
BREW_CONFIRM_TIMEOUT_S = 45.0

# Codes the machine uses for "on" and "off" in agitation and bypass fields.
_ON, _OFF = 1, 2


# ── Talking to the integration ───────────────────────────────────────────────


@dataclass
class Machine:
    """This integration's services and entities, as the tool reaches them.

    Entities are found by unique id through the entity registry, so a person
    renaming one does not break the tool.
    """

    hass: HomeAssistant
    context: Context | None
    # Coffee Lab, when it is switched on.
    lab: CoffeeLab | None = None

    async def call(self, service: str, data: dict[str, Any] | None = None) -> None:
        await self.hass.services.async_call(
            DOMAIN, service, data or {}, blocking=True, context=self.context
        )

    async def ask(self, service: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.hass.services.async_call(
            DOMAIN, service, data or {}, blocking=True, context=self.context,
            return_response=True,
        )
        return dict(response or {})

    def entity_id(self, platform: str, unique_id: str) -> str:
        entity_id = er.async_get(self.hass).async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id is None:
            raise fail("entity_missing", entity=f"{platform}.{unique_id}")
        return entity_id

    def state(self, platform: str, unique_id: str) -> str | None:
        """An entity's state, or None when it has none worth reading."""
        current = self.hass.states.get(self.entity_id(platform, unique_id))
        if current is None or current.state in ("unknown", "unavailable", ""):
            return None
        return current.state

    def attributes(self, platform: str, unique_id: str) -> dict[str, Any]:
        current = self.hass.states.get(self.entity_id(platform, unique_id))
        return dict(current.attributes) if current is not None else {}

    async def entity_service(
        self, platform: str, service: str, unique_id: str, **data: Any
    ) -> None:
        await self.hass.services.async_call(
            platform, service,
            {"entity_id": self.entity_id(platform, unique_id), **data},
            blocking=True, context=self.context,
        )


_refuse = refuse


# ── Recipes as facts ─────────────────────────────────────────────────────────


def _ratio_denominator(recipe: dict[str, Any]) -> float | None:
    """The N of 1:N, whichever shape the recipe arrived in.

    `water_ratio` is the denominator in a recipe read from the cloud and the
    total water in ml in one the builder assembled. Reading it directly once
    reported a 20 g, 1:12 recipe as 1:240; `normalize_recipe` is xbloom-py's own
    reconciliation of the two.
    """
    ratio = normalize_recipe(recipe).get("ratio")
    try:
        return float(str(ratio).split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


def _pattern_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    try:
        return spec.PATTERN_API_TO_NAME.get(int(value))
    except (TypeError, ValueError):
        return None


def _temperature(value: Any) -> dict[str, Any]:
    """A temperature, with the machine's two sentinels named.

    20 °C and 98 °C are not literal temperatures: `spec` calls them room
    temperature and boiling point.
    """
    try:
        celsius = float(value)
    except (TypeError, ValueError):
        return {"temperature_c": None}
    if celsius == spec.ROOM_TEMP_C:
        return {"temperature_c": celsius, "temperature_means": "room_temperature"}
    if celsius == spec.BOILING_POINT_C:
        return {"temperature_c": celsius, "temperature_means": "boiling_point"}
    return {"temperature_c": celsius}


def _pour_facts(pour: dict[str, Any]) -> dict[str, Any]:
    # No pour names: the machine names pours by position, and the cloud sorts
    # them by name, so a name invented by a caller can reorder a brew.
    return {
        "volume_ml": pour.get("volume_ml"),
        **_temperature(pour.get("temperature_c")),
        "pattern": _pattern_name(pour.get("pattern")),
        "flow_rate": pour.get("flow_rate"),
        "pause_s": pour.get("pause_s"),
        "agitate_before": pour.get("agitate_before") == _ON,
        "agitate_after": pour.get("agitate_after") == _ON,
    }


def recipe_summary(recipe: dict[str, Any]) -> dict[str, Any]:
    dose = recipe.get("dose_g")
    ratio = _ratio_denominator(recipe)
    pours = recipe.get("pours") or []
    return {
        "id": recipe.get("id"),
        "name": recipe.get("name"),
        "dose_g": dose,
        "ratio": ratio,
        "water_ml": round(float(dose) * ratio) if dose and ratio else None,
        "pour_count": recipe.get("pour_count") or len(pours),
        "from_shared_link": bool(recipe.get("shared")),
    }


def recipe_facts(recipe: dict[str, Any]) -> dict[str, Any]:
    """A recipe in full, in the vocabulary the tool accepts back."""
    try:
        cup = spec.CUP_API_TO_LABEL.get(int(recipe.get("cup_type")))
    except (TypeError, ValueError):
        cup = None
    facts = {
        **recipe_summary(recipe),
        "grind_size": recipe.get("grinder_size", recipe.get("grind_size")),
        "grinder_speed_rpm": recipe.get("rpm", recipe.get("grinder_speed_rpm")),
        "cup_type": cup,
        "pours": [_pour_facts(p) for p in recipe.get("pours") or []],
        "bypass_water": recipe.get("bypass_water_enabled") == _ON,
    }
    if facts["bypass_water"]:
        facts["bypass_volume_ml"] = recipe.get("bypass_volume_ml")
        facts["bypass_temp_c"] = recipe.get("bypass_temp_c")
    return facts


async def _recipes(machine: Machine) -> list[dict[str, Any]]:
    return list((await machine.ask("list_recipes")).get("recipes") or [])


async def _no_such_recipe(machine: Machine, wanted: str | None) -> HomeAssistantError:
    """The refusal for a recipe that is not there, naming what is."""
    if not wanted:
        return _refuse("no_recipe_selected")
    names = [str(r.get("name", "")) for r in await _recipes(machine)]
    if not names:
        return _refuse("no_recipes")
    return _refuse("recipe_not_found", name=wanted, available=", ".join(names))


async def _resolve_recipe_name(machine: Machine, wanted: str) -> str:
    for recipe in await _recipes(machine):
        if str(recipe.get("name", "")).lower() == wanted.lower():
            return str(recipe["name"])
    raise await _no_such_recipe(machine, wanted)


async def _get_recipe(machine: Machine, name: str) -> dict[str, Any]:
    recipe = (await machine.ask("get_recipe", {"name": name})).get("recipe")
    if not recipe:
        raise await _no_such_recipe(machine, name)
    return recipe


# ── Converting a caller's recipe to the machine's shape ─────────────────────


def _pour_for_machine(pour: dict[str, Any]) -> dict[str, Any]:
    """A caller's pour in the shape the machine's validator reads.

    Pattern names become api ids and booleans become agitation codes. The
    builder reads a boolean agitation as off, so `"agitate_after": true` was
    once silently dropped.
    """
    out = {k: v for k, v in pour.items() if v is not None}
    if isinstance(out.get("pattern"), str):
        out["pattern"] = spec.PATTERN_NAME_TO_API[out["pattern"]]
    for key in ("agitate_before", "agitate_after"):
        if isinstance(out.get(key), bool):
            out[key] = _ON if out[key] else _OFF
    if out.get("pause_s") is not None:
        # The validator rejects a float pause outright, even 45.0.
        out["pause_s"] = int(out["pause_s"])
    return out


def _bypass_fields(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if args.get("bypass_water_enabled") is not None:
        out["bypass_water_enabled"] = _ON if args["bypass_water_enabled"] else _OFF
    if args.get("bypass_volume_ml") is not None:
        out["bypass_volume_ml"] = float(args["bypass_volume_ml"])
    if args.get("bypass_temp_c") is not None:
        out["bypass_temp_c"] = float(args["bypass_temp_c"])
    return out


def _cup_api(raw: Any) -> int:
    """A cup type as its api id, given the id or its label."""
    text = str(raw).strip()
    if text.isdigit() and int(text) in spec.CUP_API_TO_LABEL:
        return int(text)
    by_label = {label.lower(): api for label, api in spec.CUP_LABEL_TO_API.items()}
    if text.lower() not in by_label:
        raise _refuse(
            "value_not_accepted", argument="cup_type",
            accepted=", ".join(spec.CUP_LABEL_TO_API),
        )
    return by_label[text.lower()]


def _validation(response: dict[str, Any]) -> dict[str, Any] | None:
    """The builder's refusal as data — its error codes are the information."""
    if response.get("ok", True):
        return None
    return {"saved": False, "errors": response.get("errors") or {"error": response.get("error")}}


# ── Actions ──────────────────────────────────────────────────────────────────

Action = Callable[[Machine, dict[str, Any]], Awaitable[dict[str, Any]]]


async def list_recipes(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return {"recipes": [recipe_summary(r) for r in await _recipes(machine)]}


async def get_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return {"recipe": recipe_facts(await _get_recipe(machine, args["name"]))}


async def recipe_link(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    # The link's token is RSA-encrypted, so it cannot be built from the id; it
    # comes from the cloud, carried through on the recipe.
    name = await _resolve_recipe_name(machine, args["name"])
    recipe = await _get_recipe(machine, name)
    return {"name": name, "share_url": recipe.get("share_url") or None}


async def build_recipe(machine: Machine, args: dict[str, Any], save: bool) -> dict[str, Any]:
    """Snap a described recipe onto the machine's grid, saving it or not."""
    if args.get("temperature") is not None or args.get("pattern") is not None:
        # Refused rather than dropped: dropping them would return a recipe that
        # is neither the temperature nor the pattern asked for.
        raise _refuse("per_pour_only")
    bypass = _bypass_fields(args)
    data: dict[str, Any] = {"name": args["name"], "save": save and not bypass}
    for key in ("dose", "ratio", "grind_size", "pour_count", "apply_brew_defaults"):
        if args.get(key) is not None:
            data[key] = args[key]
    if args.get("cup_type") is not None:
        data["cup_type"] = _cup_api(args["cup_type"])
    if args.get("speed") is not None:
        data["grinder_speed_rpm"] = args["speed"]
    if args.get("pours"):
        data["pours_json"] = json.dumps(
            [_pour_for_machine(p) for p in args["pours"]], ensure_ascii=False
        )
    response = await machine.ask("build_recipe", data)
    if refused := _validation(response):
        return refused
    recipe = response.get("recipe") or {}
    if bypass:
        # The build_recipe service has no bypass fields; add_recipe does, and
        # validates the result the same way.
        recipe = {**recipe, **bypass}
        if save:
            added = await machine.ask(
                "add_recipe", {"recipe_json": json.dumps(recipe, ensure_ascii=False)}
            )
            if refused := _validation(added):
                return refused
    return {
        "saved": save,
        "adjustments": response.get("adjustments") or {},
        "recipe": recipe_facts(recipe),
    }


async def edit_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    """Change a recipe in place.

    Dose and ratio are refused: either rescales every pour, and the recipe
    carries cloud identifiers a rebuild would drop. save_scaled_recipe writes a
    new recipe and leaves the original alone.
    """
    if args.get("dose") is not None or args.get("ratio") is not None:
        raise _refuse("rescale_not_edit")
    recipe = await _get_recipe(machine, args["name"])
    updated = dict(recipe)
    if args.get("grind_size") is not None:
        # The machine blob reads grinder_size; the validator reads grind_size.
        updated["grind_size"] = updated["grinder_size"] = args["grind_size"]
    if args.get("speed") is not None:
        updated["grinder_speed_rpm"] = updated["rpm"] = args["speed"]
    if args.get("pours"):
        # A supplied pour replaces only the fields it names.
        existing = list(updated.get("pours") or [])
        merged = [
            {**(dict(existing[i]) if i < len(existing) else {}), **_pour_for_machine(p), "id": i}
            for i, p in enumerate(args["pours"])
        ]
        updated["pours"] = merged
        updated["pour_count"] = len(merged)
    if args.get("cup_type") is not None:
        updated["cup_type"] = _cup_api(args["cup_type"])
    updated.update(_bypass_fields(args))
    if args.get("new_name"):
        updated["name"] = args["new_name"]
    response = await machine.ask("update_recipe", {"recipe_json": json.dumps(updated)})
    if refused := _validation(response):
        return refused
    return {"saved": True, "recipe": recipe_facts(updated)}


async def delete_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    response = await machine.ask("delete_recipe", {"name": args["name"]})
    if not response.get("ok", True):
        raise await _no_such_recipe(machine, args["name"])
    return {"deleted": args["name"]}


async def archive_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return await machine.ask("archive_recipe", {
        "name": args["name"], "remove_from_cloud": bool(args.get("remove_from_cloud")),
    })


async def restore_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return await machine.ask("restore_recipe", {"name": args["name"]})


async def list_archived_recipes(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return await machine.ask("list_archived_recipes")


async def save_scaled_recipe(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "new_name": args["new_name"],
        "dose": args["dose"],
        "ratio": args["ratio"],
        "grind_size": args["grind_size"],
    }
    if args.get("name"):
        data["recipe_name"] = await _resolve_recipe_name(machine, args["name"])
    response = await machine.ask("save_scaled_recipe", data)
    if refused := _validation(response):
        return refused
    return {"saved": True, **data}


def _recipe_source(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("share_url"):
        return {"share_url": args["share_url"]}
    if args.get("share_id"):
        return {"share_id": args["share_id"]}
    return {}


async def write_to_slot(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {"slot": args["slot"], **_recipe_source(args)}
    if not data.keys() & {"share_url", "share_id"}:
        data["recipe_name"] = await _resolve_recipe_name(machine, args["name"])
    if args.get("scale_on") is not None:
        data["scale_on"] = args["scale_on"]
    await machine.call("write_slot", data)
    return {"written": True, **data}


def _brew_failure(data: dict[str, Any]) -> HomeAssistantError:
    """The translated error for an `xbloom_brew_failed` reason code."""
    reason = str(data.get("reason") or "")
    if reason in set(spec.REPLY_REFUSALS.values()):
        return fail(f"refused_{reason}")
    if reason == "bluetooth_error":
        return fail("connection_failed", error=data.get("error") or "")
    if reason == "not_configured":
        return fail("not_configured")
    if reason == "machine_not_found":
        return fail("machine_unreachable")
    return fail("brew_not_started", reason=reason)


# The brew customizer's sliders, as the dashboard's Start Brew reads them.
_PICKED = (("dose", "xbloom_brew_dose"), ("ratio", "xbloom_brew_ratio"), ("grind_size", "xbloom_brew_grind"))


def _preparation(machine: Machine) -> dict[str, Any]:
    """What the machine is being made ready for, and how far it has got."""
    recipe = machine.state("select", "xbloom_recipe_select")
    if recipe is None:
        return {"state": "none"}
    ready = machine.state("binary_sensor", "xbloom_recipe_ready") == "on"
    attrs = machine.attributes("binary_sensor", "xbloom_recipe_ready")
    facts: dict[str, Any] = {"recipe": recipe}
    for key, unique_id in _PICKED:
        value = machine.state("number", unique_id)
        if value is not None:
            facts[key] = int(float(value)) if key == "grind_size" else float(value)
    facts["use_grinder"] = machine.state("switch", "xbloom_use_grinder") != "off"
    # What this brew changes from the saved recipe, so the assistant can say so.
    saved = machine.attributes("select", "xbloom_recipe_select")
    changed = {
        key: {"saved": saved[attr], "now": facts[key]}
        for key, attr in (("dose", "dose_g"), ("ratio", "water_ratio"), ("grind_size", "grinder_size"))
        if key in facts and saved.get(attr) is not None and float(saved[attr]) != float(facts[key])
    }
    if changed:
        facts["changed_from_recipe"] = changed
    if machine.lab is not None:
        facts["bag"] = machine.state("select", "xbloom_coffee_lab_active_bag")
    if ready:
        return {"state": "ready", **facts}
    if attrs.get("preparing"):
        return {"state": "preparing", **facts}
    return {"state": "not_ready", "because": attrs.get("reason"), **facts}


async def prepare_brew(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    """Choose a recipe and its settings, and make the machine ready.

    Waits for the outcome: an assistant cannot be told later, so answering
    before the machine does only means being asked again.
    """
    data: dict[str, Any] = {}
    if args.get("name"):
        data["recipe_name"] = await _resolve_recipe_name(machine, args["name"])
    for key in ("dose", "ratio", "grind_size", "use_preground"):
        if args.get(key) is not None:
            data[key] = args[key]
    if machine.lab is not None:
        # The same rule as start_brew: the bag is named, never assumed.
        if args.get("unattributed"):
            data["unattributed"] = True
        else:
            if not (args.get("bean") or args.get("bean_id")):
                raise refuse("bag_required")
            data["bean_id"] = (await resolve_bean(machine.lab, args)).id
    await machine.call("prepare_brew", data)
    return _preparation(machine)


async def start_brew(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    # One path, whatever the request: the recipe is prepared — unless the
    # machine already holds exactly it — and then started. Only a share link,
    # which is not in the library and so cannot be picked, is brewed directly.
    data: dict[str, Any] = _recipe_source(args)
    prepared = not data
    changes = {
        k: args[k] for k in ("dose", "ratio", "grind_size", "use_preground") if args.get(k) is not None
    }
    if not data and args.get("name"):
        changes["name"] = args["name"]
    if data:
        if args.get("use_preground") is not None:
            data["use_preground"] = args["use_preground"]
    # notify_context is the name callers already use for the same thing.
    context = args.get("context") if args.get("context") is not None else args.get("notify_context")
    if context is not None:
        data["context"] = context
    if args.get("notify_target"):
        data["notify_target"] = args["notify_target"]
        data["notify_progress"] = bool(args.get("notify_progress"))
    overrides = {k: args[k] for k in ("dose", "ratio", "grind_size") if args.get(k) is not None}
    if not prepared:
        data.update(overrides)
    bag = None
    if machine.lab is not None:
        # Named on the brew itself, so it cannot be forgotten, nor charged to
        # a bag chosen for an earlier brew.
        if args.get("unattributed"):
            data["unattributed"] = True
        else:
            if not (args.get("bean") or args.get("bean_id")):
                raise refuse("bag_required")
            bag = await resolve_bean(machine.lab, args)
            data["bean_id"] = bag.id
            # The bag in use is the one the dashboard should show.
            await machine.lab.async_select(bag.id)
    if prepared:
        # A new recipe or settings are made ready first; otherwise the start
        # takes what is ready, or waits for a preparation still under way.
        if changes:
            await prepare_brew(machine, {**args, **changes})
        # Start exactly what was prepared: the picks, as Start Brew sends them.
        for key, unique_id in _PICKED:
            value = machine.state("number", unique_id)
            if value is not None:
                data[key] = int(float(value)) if key == "grind_size" else float(value)

    hass = machine.hass
    heard: list[Event] = []
    run_id: str | None = None
    answer: asyncio.Future[Event] = hass.loop.create_future()

    @callback
    def _heard(event: Event) -> None:
        heard.append(event)
        if run_id is not None and event.data.get("run_id") == run_id and not answer.done():
            answer.set_result(event)

    # Listening before the call: a brew refused at once fires its failure
    # before the call returns the run id it can be matched by.
    unsubscribe = [
        hass.bus.async_listen("xbloom_brew_started", _heard),
        hass.bus.async_listen("xbloom_brew_failed", _heard),
    ]
    try:
        run_id = (await machine.ask("start_brew", data)).get("run_id")
        event = next((e for e in heard if e.data.get("run_id") == run_id), None)
        if event is None and run_id is not None:
            try:
                event = await asyncio.wait_for(answer, BREW_CONFIRM_TIMEOUT_S)
            except TimeoutError:
                event = None
    finally:
        for unsub in unsubscribe:
            unsub()

    if event is not None and event.event_type == "xbloom_brew_failed":
        if event.data.get("reason") == "recipe_not_found":
            raise await _no_such_recipe(machine, event.data.get("recipe_name"))
        raise _brew_failure(dict(event.data))
    facts: dict[str, Any] = {
        "run_id": run_id,
        # "pending": dispatched, and the machine has not yet said either way.
        "outcome": "started" if event is not None else "pending",
        "recipe": (event.data.get("recipe_name") if event is not None else None)
        or data.get("recipe_name"),
    }
    if overrides:
        facts["overrides_this_brew_only"] = overrides
    if bag is not None:
        facts["bag"] = bag.name
    return facts


async def _plain(service: str, machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    await machine.call(service)
    return {"done": True}


async def grind(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    data = {
        name: args[arg]
        for arg, name in (("grind_size", "size"), ("speed", "speed"), ("seconds", "seconds"))
        if args.get(arg) is not None
    }
    await machine.call("grind", data)
    return {"grinding": True, **data}


async def set_mode(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    await machine.call("set_mode", {"mode": args["mode"]})
    return {"mode": args["mode"]}


async def set_water_source(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    await machine.call("set_water_source", {"source": args["water_source"]})
    return {"water_source": args["water_source"]}


async def set_units(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    if args.get("temperature_unit"):
        await machine.call("set_temp_unit", {"unit": args["temperature_unit"]})
        facts["temperature_unit"] = args["temperature_unit"]
    if args.get("weight_unit"):
        await machine.call("set_weight_unit", {"unit": args["weight_unit"]})
        facts["weight_unit"] = args["weight_unit"]
    return facts


async def connect(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    on = True if args.get("enabled") is None else bool(args["enabled"])
    await machine.entity_service(
        "switch", "turn_on" if on else "turn_off", "xbloom_connect_switch"
    )
    return {"link_held_open": on}


def _in_range(machine: Machine) -> bool | None:
    """Whether Home Assistant's Bluetooth can see the machine, or None if unknown."""
    state = machine.state("binary_sensor", "xbloom_in_range")
    return None if state is None else state == "on"


async def brew_status(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "brew_status": machine.state("sensor", "xbloom_brew_status"),
        "recipe": machine.state("sensor", "xbloom_current_recipe"),
        "in_range": _in_range(machine),
        "preparation": _preparation(machine),
    }


async def machine_status(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    in_range = _in_range(machine)
    if in_range is False:
        # The status sensor keeps the last thing the machine said, and read
        # "ok" for a machine switched off. Out of range, there is no status.
        return {"in_range": False}
    status = machine.state("sensor", "xbloom_machine_status")
    return {
        "in_range": in_range,
        "machine_status": status,
        "fault": status is not None and status != spec.MACHINE_OK,
    }


async def refresh_status(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    if _in_range(machine) is False:
        return {"in_range": False, "refreshed": False}
    await machine.call("refresh_status")
    return {"refreshed": True, **await machine_status(machine, args)}


async def brew_history(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    """When this machine finished brewing — its own status, nothing more.

    Covers a brew started at the machine by hand, which no brew event reports.
    """
    hass = machine.hass
    if "recorder" not in hass.config.components:
        raise fail("history_unavailable")
    days = int(args.get("days") or DEFAULT_HISTORY_DAYS)
    entity_id = machine.entity_id("sensor", "xbloom_brew_status")
    start = dt_util.utcnow() - timedelta(days=days)
    changes = await get_instance(hass).async_add_executor_job(
        partial(
            history.state_changes_during_period,
            hass, start, entity_id=entity_id, no_attributes=True,
            # The state before the window, so a brew finishing first in the
            # window still has what came before it.
            include_start_time_state=True,
        )
    )
    return {"days": days, "finished_at": finished_times(changes.get(entity_id, []), start)}


def finished_times(states: list, start) -> list[str]:
    """When a brew finished: `done` reached from a brew, not restored.

    At every restart the sensor restores its last state, `done` included, and
    that is recorded as a change. Only `done` straight after idle, grinding or
    brewing is a brew finishing.
    """
    return [
        dt_util.as_local(cur.last_changed).isoformat(timespec="minutes")
        for prev, cur in zip(states, states[1:])
        if cur.state == "done" and prev.state in ("idle", "grinding", "brewing")
        and cur.last_changed >= start
    ]


async def standalone_brew(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    """Pour water with no recipe, from the brewer entities' settings."""
    for arg, unique_id in (
        ("volume_ml", "xbloom_brew_volume"),
        ("temperature", "xbloom_brew_temperature"),
        ("flow_rate", "xbloom_brew_flow_rate"),
    ):
        if args.get(arg) is not None:
            await machine.entity_service("number", "set_value", unique_id, value=args[arg])
    if args.get("pattern"):
        await machine.entity_service(
            "select", "select_option", "xbloom_brew_pattern_select", option=args["pattern"]
        )
    await machine.call("brew_standalone")
    return {
        "pouring": True,
        "volume_ml": machine.state("number", "xbloom_brew_volume"),
        "temperature_c": machine.state("number", "xbloom_brew_temperature"),
        "flow_rate": machine.state("number", "xbloom_brew_flow_rate"),
        "pattern": machine.state("select", "xbloom_brew_pattern_select"),
    }


_SCREEN_BUTTONS = {
    "grinder": "xbloom_enter_grinder_button",
    "brewer": "xbloom_enter_brewer_button",
    "scale": "xbloom_enter_scale_button",
}


async def go_to(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    module = args["module"]
    if module == "home":
        await machine.call("back_to_home")
    else:
        await machine.entity_service("button", "press", _SCREEN_BUTTONS[module])
    return {"screen": module}


async def scale_weight(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    """The scale reading, and whether it is live.

    The sensor keeps its last value after the link drops, so the link's state
    travels with the number.
    """
    grams = machine.state("sensor", "xbloom_scale_weight")
    return {
        "grams": float(grams) if grams is not None else None,
        "live": machine.state("switch", "xbloom_connect_switch") == "on",
    }


async def firmware_status(machine: Machine, args: dict[str, Any]) -> dict[str, Any]:
    attrs = machine.attributes("update", "xbloom_firmware")
    return {
        "installed_version": attrs.get("installed_version"),
        "latest_version": attrs.get("latest_version"),
        "update_available": machine.state("update", "xbloom_firmware") == "on",
    }


# ── The action table ─────────────────────────────────────────────────────────


ACTIONS: dict[str, Spec] = {
    # Recipes
    "list_recipes": Spec(list_recipes, "every recipe in the library"),
    "get_recipe": Spec(get_recipe, "one recipe in full", ("name",)),
    "recipe_link": Spec(
        recipe_link,
        "the shareable xBloom link; share_url is null for a recipe not saved in "
        "the xBloom account",
        ("name",),
    ),
    "create_recipe": Spec(
        lambda m, a: build_recipe(m, a, True),
        "build and save a recipe (dose, ratio, grind_size, speed, cup_type, "
        "pour_count, pours, bypass_*). Temperature and pattern go on each pour. "
        "Pour volumes are moved to total dose x ratio; `adjustments` says what "
        "moved. A recipe the machine cannot run comes back as `errors`",
        ("name",),
    ),
    "preview_recipe": Spec(
        lambda m, a: build_recipe(m, a, False),
        "the same as create_recipe without saving",
        ("name",),
    ),
    "edit_recipe": Spec(
        edit_recipe,
        "change grind_size/speed/pours/cup_type/bypass_*/new_name in place. A pour "
        "replaces only the fields it names. Dose and ratio are refused here — use "
        "save_scaled_recipe",
        ("name",),
    ),
    "delete_recipe": Spec(delete_recipe, "remove a recipe", ("name",)),
    "archive_recipe": Spec(
        archive_recipe,
        "take a recipe out of the library and keep it to restore later. It stays "
        "in the xBloom cloud unless remove_from_cloud",
        ("name",),
    ),
    "restore_recipe": Spec(
        restore_recipe,
        "bring an archived recipe back; signed in to the xBloom cloud, it goes back there",
        ("name",),
    ),
    "list_archived_recipes": Spec(list_archived_recipes, "the archived recipes"),
    "save_scaled_recipe": Spec(
        save_scaled_recipe,
        "a rescaled copy under a new name; name picks the source, else the "
        "selected recipe",
        ("new_name", "dose", "ratio", "grind_size"),
    ),
    "write_to_slot": Spec(
        write_to_slot,
        "put a recipe on machine slot A, B or C, to brew from the machine itself "
        "(scale_on)",
        ("slot",),
        ("name", "share_url", "share_id"),
    ),
    # Brewing
    "start_brew": Spec(
        start_brew,
        "start a brew: a recipe by name, or the chosen one if none, or a "
        "share_url/share_id. dose/ratio/grind_size apply to this brew only; "
        "use_preground skips the grinder. The machine is made ready first when "
        "it is not already. Waits for the machine to take the brew: outcome "
        "`started`, or `pending` if it has not answered yet — then read "
        "brew_status",
    ),
    "prepare_brew": Spec(
        prepare_brew,
        "choose a recipe by name, or keep the chosen one, with dose/ratio/"
        "grind_size/use_preground, and make the machine ready without brewing. "
        "Before calling it, confirm the recipe with the person and ask whether to "
        "change the dose, ratio or grind, unless they already said. "
        "Takes several seconds and answers once it is ready, with the recipe, "
        "settings, what differs from the saved recipe, and the bag, or says why "
        "not. To adjust before starting, call it again with just the new "
        "values. start_brew then starts it at once",
    ),
    "cancel_preparation": Spec(
        partial(_plain, "cancel_preparation"),
        "take back a prepared recipe that has not started, and unpick it",
    ),
    "cancel_brew": Spec(partial(_plain, "stop_brew"), "stop the brew"),
    "pause_brew": Spec(partial(_plain, "brew_pause"), "pause the brew"),
    "resume_brew": Spec(partial(_plain, "brew_resume"), "carry on after a pause"),
    # Machine
    "brew_status": Spec(brew_status, "what the machine is doing now"),
    "machine_status": Spec(
        machine_status,
        "whether the machine is in range, and any fault. No status is given out "
        "of range, since the last one may be stale",
    ),
    "refresh_status": Spec(refresh_status, "ask the machine to report again, then read it"),
    "brew_history": Spec(
        brew_history,
        "when this machine finished brewing (days). Times only — the machine does "
        "not know the recipe or the coffee",
    ),
    "grind": Spec(grind, "run the grinder alone (grind_size, speed, seconds)"),
    "standalone_brew": Spec(
        standalone_brew,
        "pour water with no recipe (volume_ml, temperature, flow_rate, pattern)",
    ),
    "scale_weight": Spec(scale_weight, "the scale reading, and whether it is live"),
    "firmware_status": Spec(firmware_status, "installed firmware, and any update"),
    "go_to": Spec(go_to, "send the machine to a screen", ("module",)),
    "tare": Spec(partial(_plain, "tare"), "zero the scale"),
    "back_to_home": Spec(partial(_plain, "back_to_home"), "return to the home screen"),
    # Settings
    "set_mode": Spec(set_mode, "the machine's mode", ("mode",)),
    "set_water_source": Spec(set_water_source, "tank or tap", ("water_source",)),
    "set_units": Spec(
        set_units, "the units the machine shows", (), ("temperature_unit", "weight_unit")
    ),
    "connect": Spec(
        connect,
        "hold the Bluetooth link open (enabled), or release it. The xBloom app "
        "cannot connect while it is held",
    ),
}


INTRO = (
    "The xBloom Studio coffee machine. Pick an action; each line names the "
    "arguments that action cannot run without."
)

# Said of start_brew only while Coffee Lab is on.
BAG_RULE = (
    "Coffee Lab is on: start_brew also needs the bag the coffee comes from — "
    "bean (its name) or bean_id — or unattributed=true for a brew from no bag, "
    "such as an xPod. The bag is counted when the brew completes."
)


def describe(lab_on: bool = False, targets: tuple[str, ...] = ()) -> str:
    """The tool's description: every action, with what it needs."""
    text = _describe(INTRO, ACTIONS)
    if lab_on:
        text = f"{text}\n{BAG_RULE}"
    if targets:
        text = (
            f"{text}\nCallback targets for start_brew's notify_target: {', '.join(targets)}. "
            "With one, do not poll brew_status; the ending will arrive."
        )
    return text


def check_arguments(action: str, args: dict[str, Any]) -> None:
    _check(ACTIONS, action, args)


# ── The argument schema ──────────────────────────────────────────────────────


def _ranged(field: str, what: str) -> tuple[Any, str]:
    """A number bounded by the machine's own range for `field`."""
    rng = spec.field(field)
    unit = f" {rng.unit}" if rng.unit else ""
    return (
        vol.All(vol.Coerce(float), vol.Range(min=rng.min, max=rng.max)),
        f"{what}, {rng.min:g}-{rng.max:g}{unit} in steps of {rng.step:g}.",
    )


POUR_FIELDS: dict[str, tuple[Any, str]] = {
    "volume_ml": _ranged("pour_volume_ml", "Water for this pour"),
    "temperature_c": _ranged("pour_temperature_c", "Water temperature in Celsius"),
    "flow_rate": _ranged("pour_flow_rate", "Flow rate"),
    "pattern": (vol.In(list(spec.PATTERN_NAMES)), "How the water is poured."),
    "pause_s": (
        vol.All(vol.Coerce(int), vol.Range(
            min=int(spec.field("pour_pause_s").min), max=int(spec.field("pour_pause_s").max),
        )),
        "Seconds to wait after this pour, a whole number.",
    ),
    "agitate_before": (bool, "Vibrate the dripper before this pour."),
    "agitate_after": (bool, "Vibrate the dripper after this pour."),
}

ARGUMENTS: dict[str, tuple[Any, str]] = {
    "name": (str, "A recipe's name."),
    "share_url": (str, "An xBloom share link, instead of a library name."),
    "share_id": (str, "An xBloom share id, instead of share_url."),
    "dose": (vol.Coerce(float), "Grams of coffee."),
    "ratio": (vol.Coerce(float), "Brew ratio as its denominator: 16 means 1:16."),
    "grind_size": (vol.Coerce(int), "Grind setting."),
    "speed": (vol.Coerce(int), "Grinder speed in RPM."),
    "temperature": (vol.Coerce(float), "Water temperature, for standalone_brew only."),
    "pattern": (
        vol.In(list(spec.PATTERN_NAMES)),
        "Pour pattern, for standalone_brew only; a recipe sets it per pour.",
    ),
    "cup_type": (
        str, "Cup or dripper: " + ", ".join(spec.CUP_LABEL_TO_API) + ". Sets the dose range.",
    ),
    "mode": (vol.In(list(spec.MODES)), "Machine mode."),
    "water_source": (vol.In(list(spec.WATER_SOURCE_CODES)), "Where the water comes from."),
    "temperature_unit": (vol.In(list(spec.TEMP_UNIT_CODES)), "Temperature unit shown."),
    "weight_unit": (vol.In(list(spec.WEIGHT_UNIT_CODES)), "Weight unit shown."),
    "enabled": (bool, "For connect: hold the link open (true) or release it."),
    "days": (vol.All(vol.Coerce(int), vol.Range(min=1)), "How far back brew_history looks."),
    "new_name": (str, "A new name for the recipe."),
    "slot": (vol.In(list(spec.SLOTS)), "A machine slot."),
    "module": (vol.In(["home", *_SCREEN_BUTTONS]), "The screen go_to shows."),
    "volume_ml": _ranged("brewer_volume_ml", "Millilitres to pour, for standalone_brew"),
    "flow_rate": (vol.Coerce(float), "Flow rate, for standalone_brew."),
    "seconds": (vol.Coerce(float), "How long to run the grinder."),
    "scale_on": (bool, "Whether the slot brews with the scale on."),
    "use_preground": (bool, "For start_brew: skip the grinder, for coffee already ground."),
    "context": (
        vol.Schema({}, extra=vol.ALLOW_EXTRA),
        "For start_brew: any object, returned unchanged in every event of this brew.",
    ),
    "notify_target": (
        str,
        "For start_brew: a callback target's name, told this brew's faults and "
        "exactly one ending. A name, never a URL.",
    ),
    "notify_context": (
        vol.Schema({}, extra=vol.ALLOW_EXTRA),
        "For start_brew, with notify_target: any object, returned unchanged in "
        "every callback so the receiver knows where the news belongs.",
    ),
    "notify_progress": (bool, "For start_brew, with notify_target: also send grinding and each pour."),
    "pour_count": (
        vol.All(vol.Coerce(int), vol.Range(
            min=int(spec.field("pour_count").min), max=int(spec.field("pour_count").max),
        )),
        "How many pours to generate when no pours are given.",
    ),
    "apply_brew_defaults": (
        bool, "Fill unset pauses with the machine's brewing defaults (on unless false).",
    ),
    "remove_from_cloud": (bool, "For archive_recipe: also delete it from the xBloom cloud."),
    "bypass_water_enabled": (bool, "Add water after brewing, bypassing the grounds."),
    "bypass_volume_ml": _ranged("bypass_volume_ml", "Bypass water"),
    "bypass_temp_c": _ranged("bypass_temp_c", "Bypass water temperature in Celsius"),
    "pours": (
        [vol.Schema({
            vol.Optional(key, description=text): validator
            for key, (validator, text) in POUR_FIELDS.items()
        })],
        "The pours, in order. Every field is optional. Pours have no names: the "
        "machine names them by position.",
    ),
}


# Offered only while Coffee Lab is on.
BAG_ARGUMENTS: dict[str, tuple[Any, str]] = {
    "bean": (str, "For start_brew: the name of the bag the coffee comes from."),
    "bean_id": (str, "For start_brew: the bag's id, when two bags share a name."),
    "unattributed": (bool, "For start_brew: the coffee comes from no bag, as with an xPod."),
}


def parameters(lab_on: bool = False) -> vol.Schema:
    arguments = {**ARGUMENTS, **BAG_ARGUMENTS} if lab_on else ARGUMENTS
    return vol.Schema({
        vol.Required("action", description="Which action to run; see the tool description."):
            vol.In(list(ACTIONS)),
        **{
            vol.Optional(key, description=text): validator
            for key, (validator, text) in arguments.items()
        },
    })
