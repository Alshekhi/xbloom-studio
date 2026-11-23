"""The parts of a brew a story agent writes: the request and the reply.

Pure. The agent writes only what no file can — texts about this cup, reasoned
from the brew history the integration keeps: what this recipe does for this
coffee and what to taste for (the bloom), and what changed since last time,
what to check because of it and a pattern in the history (the closing line).
Facts and the big story stay built-in and are never sent. The closing line
ends on the built-in teaser.
"""
from __future__ import annotations

import json
from typing import Any

from ..coffee_lab.actions import DESCRIPTIVE, ORIGIN
from .compose import BrewTexts
from .memory import StoryMemory
from .plan import Slot

TASK_NAME = "xbloom brew story"
# The slot kinds the agent writes; every other slot keeps its built-in text.
AGENT_KINDS = ("bag", "you")
# What of a bag is sent: what it is and where it comes from, nothing of stock.
BAG_FIELDS = ("name", *DESCRIPTIVE, *ORIGIN)

_LANGUAGE_NAMES = {"en": "English", "ar": "Modern Standard Arabic"}

_KINDS = {
    "bag": ("This cup: what this recipe does for this coffee (its temperatures, pours "
            "and ratio against the coffee's origin, process and the roaster's notes) "
            "and what to smell or taste for now and as it cools."),
    "you": ("The coach: what changed since the last brew of this recipe with this bag "
            "and what to check in the cup because of it, given that brew's verdict, "
            "tasting and planned change; then one pattern from the rated history, "
            "only if a real one exists."),
}

_RULES = """\
You write short texts shown on a phone while a coffee machine brews one cup,
for the person who will drink it. Each text fills one moment of the brew and is
read in the seconds it lasts. Write in {language}. Plain sentences, at most
about 60 words per text, no lists, no headings, no emoji.

Reason only from the data below. Do not state facts about coffee's history or
science, and no figure that is not in the data. When the data does not support
something, leave it out."""


def slot_key(slot: Slot) -> str:
    return "draining" if slot.at == "draining" else f"{slot.at}_{slot.pour}"


def changes_since(before: dict[str, Any], now: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """The settings known on both sides whose values differ."""
    return {
        key: (before[key], now[key]) for key in now
        if before.get(key) is not None and now.get(key) is not None and before[key] != now[key]
    }


def _brews(brews: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    rows = [{k: b.get(k) for k in keys if b.get(k) not in (None, "", {})} for b in brews]
    return json.dumps(rows, ensure_ascii=False)


def build_request(
    texts: BrewTexts, plan: list[dict] | None, recipe: str | None, settings: dict[str, Any],
    bag: dict | None, bag_brews: list[dict], rated: list[dict], memory: StoryMemory,
    language: str,
) -> tuple[str, dict[str, Any]]:
    """The instructions and the structure of one brew's request."""
    parts = [_RULES.format(language=_LANGUAGE_NAMES.get(language, "English"))]
    pours = [{k: p.get(k) for k in ("volume_ml", "temperature_c", "pattern", "wait_s")}
             for p in plan or []]
    parts.append(f"This brew: recipe {json.dumps(recipe, ensure_ascii=False)}, settings "
                 f"{json.dumps(settings)}, pours {json.dumps(pours) if pours else 'not known'}.")
    if bag:
        fields = {k: bag[k] for k in BAG_FIELDS if bag.get(k) not in (None, "")}
        parts.append("The coffee: " + json.dumps(fields, ensure_ascii=False))
        parts.append(f"This bag's earlier brews, newest first ({len(bag_brews)}): "
                     + _brews(bag_brews, ("recipe", "settings", "verdict", "tasting", "next_change")))
        last = next((b for b in bag_brews if b.get("recipe") == recipe), None)
        if last is None:
            parts.append("This is the first brew of this recipe with this bag.")
        else:
            changed = changes_since(last.get("settings") or {}, settings)
            parts.append("Changed since the last brew of this recipe with this bag "
                         "(setting: before, now): "
                         + (json.dumps(changed) if changed else "nothing"))
        told = memory.agent_told(bag.get("id"))
        if told:
            parts.append("Already told about this bag; do not repeat any of it:\n"
                         + "\n".join(f"- {t}" for t in told))
    else:
        parts.append("There is no bag for this brew: say nothing about a particular coffee.")
    if rated:
        parts.append("Rated history, newest first, for patterns (a verdict is again, fine "
                     "or not again): " + _brews(rated, ("bag", "country", "process", "recipe",
                                                        "settings", "verdict")))
    else:
        parts.append("There is no rated history: say nothing about patterns.")
    structure: dict[str, Any] = {}
    for slot in texts.stories:
        if slot.kind in AGENT_KINDS:
            structure[slot_key(slot)] = {
                "description": _KINDS[slot.kind], "required": True, "selector": {"text": {}}}
    return "\n\n".join(parts), structure


def parse_reply(texts: BrewTexts, data: dict[str, Any]) -> dict[Slot, tuple[str, str]]:
    """The agent's text per slot it writes, under the built-in heading.

    The closing line ends on the built-in teaser, as in built-in mode.
    """
    teaser = (texts.teaser or {}).get("text") or ""
    stories: dict[Slot, tuple[str, str]] = {}
    for slot, (heading, _text) in texts.stories.items():
        if slot.kind not in AGENT_KINDS:
            continue
        value = data.get(slot_key(slot))
        text = value.strip() if isinstance(value, str) else ""
        if slot.at == "draining" and teaser:
            text = f"{text} {teaser}".strip()
        if text:
            stories[slot] = (heading, text)
    return stories
