"""The `xbloom` AI tool.

Home Assistant's MCP server tells a client each argument's type and values but
never which ones an action requires, so the tool's own description and its
refusal carry that. These tests hold both to the same table, and hold the
tool to returning facts: no sentence of its own, a translated error when it
refuses.
"""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom import llm_api, tool_xbloom
from custom_components.xbloom.tool_xbloom import ACTIONS, ARGUMENTS, check_arguments, describe

COMPONENT = Path(__file__).parents[3] / "custom_components" / "xbloom"


def _action_line(action: str) -> str:
    [line] = [l for l in describe().splitlines() if l.startswith(f"- {action}:")]
    return line


# ── Discipline: an action's needs reach the client ──────────────────────────


@pytest.mark.parametrize("action", list(ACTIONS))
def test_description_names_what_each_action_needs(action):
    line = _action_line(action)
    for name in ACTIONS[action].requires + ACTIONS[action].one_of:
        assert name in line, f"{action}'s description does not name {name}"


@pytest.mark.parametrize(
    "action", [a for a, s in ACTIONS.items() if s.requires or s.one_of]
)
def test_refusal_names_what_is_missing(action):
    with pytest.raises(HomeAssistantError) as caught:
        check_arguments(action, {})
    assert caught.value.translation_key == "missing_arguments"
    said = caught.value.translation_placeholders["arguments"]
    for name in ACTIONS[action].requires + ACTIONS[action].one_of:
        assert name in said


@pytest.mark.parametrize("action", list(ACTIONS))
def test_a_complete_call_is_not_refused(action):
    spec_ = ACTIONS[action]
    args = {name: "x" for name in spec_.requires}
    if spec_.one_of:
        args[spec_.one_of[0]] = "x"
    check_arguments(action, args)


def test_every_named_requirement_is_an_argument():
    for action, spec_ in ACTIONS.items():
        for name in spec_.requires + spec_.one_of:
            assert name in ARGUMENTS, f"{action} needs {name}, which is not an argument"


def test_an_empty_string_counts_as_missing():
    with pytest.raises(HomeAssistantError):
        check_arguments("get_recipe", {"name": ""})


# ── Every refusal has a message, in every language ──────────────────────────


def _exceptions(path: Path) -> dict:
    return json.loads(path.read_text())["exceptions"]


def _refusal_keys() -> set[str]:
    source = "".join(p.read_text() for p in COMPONENT.rglob("*.py"))
    keys = set(re.findall(r'(?:refuse|fail)\(\s*"([a-z_]+)"', source))
    # finish_bag raises the code finish_refusal returns.
    keys |= set(re.findall(r'return "(bag_[a-z_]+)"', source))
    from xbloom import spec

    keys |= {f"refused_{reason}" for reason in spec.REPLY_REFUSALS.values()}
    return keys


@pytest.mark.parametrize(
    "path", ["strings.json", "translations/en.json", "translations/ar.json"]
)
def test_every_refusal_is_translated(path):
    table = _exceptions(COMPONENT / path)
    missing = _refusal_keys() - table.keys()
    assert not missing, f"{path} lacks {sorted(missing)}"


def test_arabic_keeps_every_placeholder():
    en = _exceptions(COMPONENT / "translations/en.json")
    ar = _exceptions(COMPONENT / "translations/ar.json")
    for key in _refusal_keys():
        placeholders = lambda text: set(re.findall(r"\{(\w+)\}", text))  # noqa: E731
        assert placeholders(en[key]["message"]) == placeholders(ar[key]["message"]), key


# ── A machine to talk to ─────────────────────────────────────────────────────


class FakeHass:
    """Services, states and the event bus — what the tool touches."""

    def __init__(self, states=None, responses=None, on_call=None):
        self.loop = asyncio.get_running_loop()
        self.calls: list[tuple] = []
        self._states = states or {}
        self._responses = responses or {}
        self._on_call = on_call
        self.listeners: dict[str, list] = {}
        self.services = SimpleNamespace(async_call=self._call)
        self.states = SimpleNamespace(get=self._get)
        self.bus = SimpleNamespace(async_listen=self._listen)
        self.config = SimpleNamespace(components={"recorder"})

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, data))
        if self._on_call:
            self._on_call(self, service)
        if kw.get("return_response"):
            return self._responses.get(service, {})
        return None

    def _get(self, entity_id):
        value = self._states.get(entity_id)
        if value is None:
            return None
        if isinstance(value, tuple):
            return SimpleNamespace(state=value[0], attributes=value[1])
        return SimpleNamespace(state=value, attributes={})

    def _listen(self, event_type, cb):
        self.listeners.setdefault(event_type, []).append(cb)

        def unsub():
            self.listeners[event_type].remove(cb)

        return unsub

    def fire(self, event_type, data):
        for cb in list(self.listeners.get(event_type, [])):
            cb(SimpleNamespace(event_type=event_type, data=data))


@pytest.fixture(autouse=True)
def registry():
    """Entity ids are `<platform>.<unique id>` here."""
    reg = MagicMock()
    reg.async_get_entity_id = lambda platform, domain, uid: f"{platform}.{uid}"
    with patch.object(tool_xbloom.er, "async_get", return_value=reg):
        yield reg


def _machine(hass):
    return tool_xbloom.Machine(hass, None)


# ── start_brew waits for the machine's answer ────────────────────────────────


async def test_start_brew_reports_started_when_the_machine_takes_it():
    hass = FakeHass(
        responses={"list_recipes": {"recipes": [{"name": "Kenya"}]},
                   "start_brew": {"run_id": "r1"}},
        on_call=lambda h, svc: svc == "start_brew" and h.fire(
            "xbloom_brew_started", {"recipe_name": "Kenya", "total_pours": 3, "run_id": "r1"}
        ),
    )
    facts = await ACTIONS["start_brew"].run(_machine(hass), {"name": "kenya", "dose": 18.0})
    assert facts == {
        "run_id": "r1",
        "outcome": "started",
        "recipe": "Kenya",
        "overrides_this_brew_only": {"dose": 18.0},
    }
    assert ("xbloom", "start_brew", {"recipe_name": "Kenya", "dose": 18.0}) in hass.calls
    assert not any(hass.listeners.values()), "listeners left behind"


async def test_start_brew_refused_by_the_machine_raises_its_reason():
    hass = FakeHass(
        responses={"start_brew": {"run_id": "r1"}},
        on_call=lambda h, svc: svc == "start_brew" and h.fire(
            "xbloom_brew_failed", {"reason": "no_water", "recipe_name": None, "run_id": "r1"}
        ),
    )
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["start_brew"].run(_machine(hass), {})
    assert caught.value.translation_key == "refused_no_water"


async def test_start_brew_ignores_another_brew_s_events():
    hass = FakeHass(
        responses={"start_brew": {"run_id": "mine"}},
        on_call=lambda h, svc: svc == "start_brew" and h.fire(
            "xbloom_brew_failed", {"reason": "no_water", "run_id": "someone-else"}
        ),
    )
    with patch.object(tool_xbloom, "BREW_CONFIRM_TIMEOUT_S", 0.01):
        facts = await ACTIONS["start_brew"].run(_machine(hass), {})
    assert facts["outcome"] == "pending" and facts["run_id"] == "mine"


async def test_start_brew_without_an_answer_is_pending_not_started():
    hass = FakeHass(responses={"start_brew": {"run_id": "r1"}})
    with patch.object(tool_xbloom, "BREW_CONFIRM_TIMEOUT_S", 0.01):
        facts = await ACTIONS["start_brew"].run(_machine(hass), {})
    assert facts["outcome"] == "pending"


@pytest.mark.parametrize("reason, key", [
    ("machine_not_found", "machine_unreachable"),
    ("bluetooth_error", "connection_failed"),
    ("not_configured", "not_configured"),
    ("something_new", "brew_not_started"),
])
def test_every_failure_reason_has_a_message(reason, key):
    assert tool_xbloom._brew_failure({"reason": reason}).translation_key == key


# ── Status never passes off a stale reading ──────────────────────────────────


async def test_machine_status_out_of_range_gives_no_status():
    hass = FakeHass(states={
        "binary_sensor.xbloom_in_range": "off",
        "sensor.xbloom_machine_status": "ok",
    })
    assert await ACTIONS["machine_status"].run(_machine(hass), {}) == {"in_range": False}


async def test_machine_status_in_range_reports_a_fault():
    hass = FakeHass(states={
        "binary_sensor.xbloom_in_range": "on",
        "sensor.xbloom_machine_status": "no_water",
    })
    facts = await ACTIONS["machine_status"].run(_machine(hass), {})
    assert facts == {"in_range": True, "machine_status": "no_water", "fault": True}


async def test_refresh_status_does_not_ask_a_machine_out_of_range():
    hass = FakeHass(states={"binary_sensor.xbloom_in_range": "off"})
    facts = await ACTIONS["refresh_status"].run(_machine(hass), {})
    assert facts == {"in_range": False, "refreshed": False}
    assert hass.calls == []


async def test_scale_weight_says_whether_it_is_live():
    hass = FakeHass(states={
        "sensor.xbloom_scale_weight": "12.5",
        "switch.xbloom_connect_switch": "off",
    })
    assert await ACTIONS["scale_weight"].run(_machine(hass), {}) == {
        "grams": 12.5, "live": False,
    }


# ── Recipes as facts ─────────────────────────────────────────────────────────


def test_recipe_facts_speak_the_tool_s_own_vocabulary():
    facts = tool_xbloom.recipe_facts({
        "id": "r1", "name": "Kenya", "dose_g": 15, "ratio": "1:16",
        "grinder_size": 55, "rpm": 100, "cup_type": 2,
        "pours": [
            {"volume_ml": 45, "temperature_c": 20, "pattern": 2, "flow_rate": 3.0,
             "pause_s": 30, "agitate_before": 1, "agitate_after": 2},
        ],
        "bypass_water_enabled": 2,
    })
    assert facts["ratio"] == 16 and facts["water_ml"] == 240
    assert facts["cup_type"] == "Omni dripper"
    [pour] = facts["pours"]
    assert pour["pattern"] == "spiral"
    assert pour["temperature_means"] == "room_temperature"
    assert pour["agitate_before"] is True and pour["agitate_after"] is False
    assert facts["bypass_water"] is False and "bypass_volume_ml" not in facts


def test_pours_go_to_the_machine_as_codes():
    out = tool_xbloom._pour_for_machine(
        {"pattern": "circular", "agitate_after": True, "pause_s": 45.0, "flow_rate": None}
    )
    assert out == {"pattern": 3, "agitate_after": 1, "pause_s": 45}


async def test_an_unknown_recipe_is_refused_with_the_library():
    hass = FakeHass(responses={"list_recipes": {"recipes": [{"name": "Kenya"}]}})
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["recipe_link"].run(_machine(hass), {"name": "Ethiopia"})
    assert caught.value.translation_key == "recipe_not_found"
    assert caught.value.translation_placeholders["available"] == "Kenya"


async def test_an_empty_library_is_said_as_such():
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["get_recipe"].run(_machine(FakeHass()), {"name": "Kenya"})
    assert caught.value.translation_key == "no_recipes"


async def test_a_brew_with_no_recipe_selected_says_so():
    hass = FakeHass(
        responses={"start_brew": {"run_id": "r1"}},
        on_call=lambda h, svc: svc == "start_brew" and h.fire(
            "xbloom_brew_failed", {"reason": "recipe_not_found", "recipe_name": None, "run_id": "r1"}
        ),
    )
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["start_brew"].run(_machine(hass), {})
    assert caught.value.translation_key == "no_recipe_selected"


async def test_a_recipe_the_machine_cannot_run_comes_back_as_errors():
    hass = FakeHass(responses={
        "build_recipe": {"ok": False, "errors": {"ratio": "ratio_invalid"}},
    })
    facts = await ACTIONS["create_recipe"].run(_machine(hass), {"name": "X", "ratio": 99.0})
    assert facts == {"saved": False, "errors": {"ratio": "ratio_invalid"}}


async def test_temperature_on_a_recipe_is_refused_not_dropped():
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["preview_recipe"].run(_machine(FakeHass()), {"name": "X", "temperature": 94.0})
    assert caught.value.translation_key == "per_pour_only"


async def test_edit_refuses_dose_and_ratio():
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["edit_recipe"].run(_machine(FakeHass()), {"name": "X", "dose": 20.0})
    assert caught.value.translation_key == "rescale_not_edit"


# ── The API ──────────────────────────────────────────────────────────────────


async def test_the_tool_refuses_before_touching_the_machine():
    hass = FakeHass()
    tool = llm_api.XBloomTool()
    tool.parameters = lambda args: dict(args)  # the schema itself runs in Home Assistant
    tool_input = SimpleNamespace(tool_args={"action": "go_to"})
    with pytest.raises(HomeAssistantError) as caught:
        await tool.async_call(hass, tool_input, SimpleNamespace(context=None))
    assert caught.value.translation_key == "missing_arguments"
    assert hass.calls == []


async def test_without_coffee_lab_there_is_only_the_machine():
    entry = SimpleNamespace(runtime_data=SimpleNamespace(coffee_lab=None, callbacks=None))
    api = llm_api.XBloomAPI(MagicMock(), entry)
    instance = await api.async_get_api_instance(MagicMock())
    assert [tool.name for tool in instance.tools] == ["xbloom"]
    assert llm_api.API_ID == "xbloom"
    [tool] = instance.tools
    assert "bean" not in tool.description and "Coffee Lab" not in tool.description


async def test_a_brew_without_a_bag_is_refused_while_coffee_lab_is_on():
    lab = SimpleNamespace(store=None)
    with pytest.raises(HomeAssistantError) as caught:
        await ACTIONS["start_brew"].run(tool_xbloom.Machine(FakeHass(), None, lab), {})
    assert caught.value.translation_key == "bag_required"


def test_a_restart_restoring_done_is_not_a_brew():
    from datetime import datetime, timezone

    def at(hour, state):
        return SimpleNamespace(state=state, last_changed=datetime(2026, 9, 26, hour, tzinfo=timezone.utc))

    start = datetime(2026, 9, 26, 1, tzinfo=timezone.utc)
    states = [
        at(0, "done"),                           # before the window
        at(2, "unavailable"), at(3, "done"),     # a restart restoring done
        at(4, "idle"), at(5, "grinding"), at(6, "brewing"), at(7, "done"),
        at(8, "unavailable"), at(9, "done"),     # another restart
    ]
    finished = tool_xbloom.finished_times(states, start)
    assert len(finished) == 1 and finished[0].startswith("2026-09-26T07")



# ── A prepared recipe, as the AI sees it ─────────────────────────────────────


async def test_brew_status_says_which_recipe_is_ready_to_start_at_once():
    hass = FakeHass(states={
        "sensor.xbloom_brew_status": "idle",
        "binary_sensor.xbloom_recipe_ready": "on",
        "select.xbloom_recipe_select": "Kenya",
    })
    facts = await ACTIONS["brew_status"].run(_machine(hass), {})
    assert facts["recipe_ready"] is True and facts["prepared_recipe"] == "Kenya"


async def test_brew_status_says_why_nothing_is_ready():
    hass = FakeHass(states={
        "sensor.xbloom_brew_status": "idle",
        "binary_sensor.xbloom_recipe_ready": ("off", {"reason": "no_bag"}),
    })
    facts = await ACTIONS["brew_status"].run(_machine(hass), {})
    assert facts["recipe_ready"] is False and facts["not_ready_because"] == "no_bag"
    assert "prepared_recipe" not in facts


async def test_prepare_brew_answers_once_the_machine_has_the_recipe():
    hass = FakeHass(
        states={"select.xbloom_recipe_select": "Kenya"},
        responses={"list_recipes": {"recipes": [{"name": "Kenya"}]}},
    )
    facts = await ACTIONS["prepare_brew"].run(_machine(hass), {"name": "kenya", "dose": 18.0})
    assert facts == {"prepared": True, "recipe": "Kenya"}
    assert ("xbloom", "prepare_brew", {"recipe_name": "Kenya", "dose": 18.0}) in hass.calls


async def test_cancel_preparation_takes_the_recipe_back():
    hass = FakeHass()
    assert await ACTIONS["cancel_preparation"].run(_machine(hass), {}) == {"done": True}
    assert ("xbloom", "cancel_preparation", {}) in hass.calls
