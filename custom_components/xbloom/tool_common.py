"""What the AI tools share: an action table, its description, and refusals.

Home Assistant's MCP server tells a client each argument's type and values but
never which arguments an action requires. So each tool's description names, per
action, what that action cannot run without, and the same table refuses a call
that lacks it — one table, so the two cannot disagree.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


def refuse(key: str, **placeholders: Any) -> HomeAssistantError:
    """A translated refusal, its text under `exceptions` in strings.json."""
    return HomeAssistantError(
        translation_domain=DOMAIN, translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


@dataclass(frozen=True)
class Spec:
    """One action: its handler, what it does, and what it cannot run without."""

    run: Callable[..., Awaitable[dict[str, Any]]]
    help: str
    requires: tuple[str, ...] = ()
    # Arguments of which at least one must be given.
    one_of: tuple[str, ...] = ()


def describe(intro: str, actions: dict[str, Spec]) -> str:
    lines = [intro]
    for action, entry in actions.items():
        needs = [", ".join(entry.requires)] if entry.requires else []
        if entry.one_of:
            needs.append("one of " + "/".join(entry.one_of))
        suffix = f" [needs {'; '.join(needs)}]" if needs else ""
        lines.append(f"- {action}: {entry.help}{suffix}")
    return "\n".join(lines)


def check_arguments(actions: dict[str, Spec], action: str, args: dict[str, Any]) -> None:
    """Refuse a call missing what its action needs, naming what is missing."""
    entry = actions[action]
    missing = [name for name in entry.requires if args.get(name) in (None, "")]
    if entry.one_of and not any(args.get(name) not in (None, "") for name in entry.one_of):
        missing.append(" or ".join(entry.one_of))
    if missing:
        raise refuse("missing_arguments", action=action, arguments=", ".join(missing))
