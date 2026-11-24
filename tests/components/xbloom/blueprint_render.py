"""Render a blueprint's variables the way Home Assistant does, for tests.

Home Assistant renders each entry of `variables:` in order, every template
seeing the ones before it and `trigger`, and parses each result back into a
native value (a number, a bool, a list) when it reads as one. This does the
same with plain Jinja2. Home Assistant's own functions are stood in for:
`states()` and `state_attr()` read the `states` given to `render`, so a test
says exactly what the entities hold. What only a live install knows —
whether the speaker is reached, how Alexa reads it — still needs the machine.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import jinja2
import yaml

BLUEPRINTS = Path(__file__).parents[3] / "custom_components" / "xbloom" / "blueprints"


class Input(str):
    """An `!input` reference, by its input's name."""


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: Input(loader.construct_scalar(node)))


def load(name: str) -> dict:
    return yaml.load((BLUEPRINTS / name).read_text(encoding="utf-8"), Loader=_Loader)


def _defaults(inputs: dict) -> dict[str, Any]:
    """Every input's default, sections included."""
    out: dict[str, Any] = {}
    for key, spec in (inputs or {}).items():
        if isinstance(spec, dict) and "input" in spec:
            out.update(_defaults(spec["input"]))
        elif isinstance(spec, dict):
            out[key] = spec.get("default")
    return out


def _native(text: str) -> Any:
    """Home Assistant's reading of a rendered result: a literal if it is one."""
    stripped = text.strip()
    try:
        value = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        return text
    return value if isinstance(value, (int, float, bool, list, dict, tuple)) or value is None else text


def render(
    name: str,
    trigger: dict,
    *,
    inputs: dict[str, Any] | None = None,
    states: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every variable of blueprint `name` for `trigger`, rendered in order."""
    blueprint = load(name)
    given = {**_defaults(blueprint["blueprint"].get("input")), **(inputs or {})}
    states = states or {}

    def _state(entity_id: str) -> str:
        value = states.get(entity_id)
        return str(value[0] if isinstance(value, tuple) else value) if value is not None else "unknown"

    def _attr(entity_id: str, attribute: str) -> Any:
        value = states.get(entity_id)
        return value[1].get(attribute) if isinstance(value, tuple) else None

    env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"])
    env.globals.update(states=_state, state_attr=_attr)
    # Home Assistant's own filter, as it defines it.
    env.filters["regex_replace"] = lambda value, find="", replace="", ignorecase=False: re.sub(
        find, replace, str(value), flags=re.IGNORECASE if ignorecase else 0)
    context: dict[str, Any] = {"trigger": trigger}
    for key, value in blueprint["variables"].items():
        if isinstance(value, Input):
            context[key] = given.get(str(value))
        elif isinstance(value, str) and ("{{" in value or "{%" in value):
            context[key] = _native(env.from_string(value).render(context))
        else:
            context[key] = value
    return context


def event(event_type: str, **data: Any) -> dict:
    """A trigger from the brew event entity changing to `event_type`."""
    return {"id": "done_recipe", "platform": "state",
            "to_state": {"state": "2026-01-01T00:00:00+00:00",
                         "attributes": {"event_type": event_type, **data}}}


def bus_event(trigger_id: str, **data: Any) -> dict:
    """A trigger from a bus event, such as `xbloom_brew_failed`."""
    return {"id": trigger_id, "platform": "event", "event": {"data": data}}
