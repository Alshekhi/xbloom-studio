"""A brew's stories written by a story agent: the request and the reply.

Pure. The built-in writer has already planned the brew — which slots carry a
story, their headings, the big-story part due — so the request asks the agent
for the texts of those slots and the next teaser, grounded in what is known.
The reply's texts go under the built-in headings; a slot the agent left empty
shows nothing.
"""
from __future__ import annotations

import json
from typing import Any

from .compose import BrewTexts
from .memory import StoryMemory
from .plan import Slot

TASK_NAME = "xbloom brew story"

_LANGUAGE_NAMES = {"en": "English", "ar": "Modern Standard Arabic"}

_KINDS = {
    "bag": "about this bag of coffee, from its own fields only",
    "big_story": "the next part of a story following coffee's history; retell the source text given",
    "science": "one fact about coffee that bears on this brew or this bag",
    "you": "a short closing line to the person drinking it, about this cup",
}

_RULES = """\
You write the short texts shown on a phone while a coffee machine brews one cup.
Each text fills one slot of the brew and is read in the seconds that slot lasts.
Write in {language}. Plain sentences, at most about 60 words per text, no lists,
no headings, no emoji.

Never invent. A specific claim about this coffee (its farm, producer, altitude,
variety, process, taste, roast) comes only from the bag's fields below. General
knowledge is allowed only at the level of a region, a variety, a process or
coffee's history. When unsure, say less rather than guess."""


def slot_key(slot: Slot) -> str:
    return "draining" if slot.at == "draining" else f"{slot.at}_{slot.pour}"


def _when(slot: Slot) -> str:
    if slot.at == "draining":
        return "while the coffee drains at the end"
    if slot.at == "wait":
        return f"in the wait after pour {slot.pour}"
    return f"while pour {slot.pour} runs"


def build_request(
    texts: BrewTexts, plan: list[dict] | None, bag: dict | None, history: list[dict],
    memory: StoryMemory, language: str,
) -> tuple[str, dict[str, Any]]:
    """The instructions and the structure of one brew's request."""
    parts = [_RULES.format(language=_LANGUAGE_NAMES.get(language, "English"))]
    pours = [{k: p.get(k) for k in ("volume_ml", "temperature_c", "pattern", "wait_s")}
             for p in plan or []]
    parts.append("The brew, pour by pour: " + (json.dumps(pours) if pours else "not known"))
    if bag:
        fields = {k: v for k, v in bag.items() if k not in ("id",) and v not in (None, "")}
        parts.append("The bag: " + json.dumps(fields, ensure_ascii=False))
        last = history[0] if history else {}
        said = [f"This is cup {len(history) + 1} from this bag."]
        if last.get("rating"):
            said.append(f"The last cup was rated {last['rating']} of 5.")
        if last.get("next_change"):
            said.append(f"After it, the plan was to change: {last['next_change']}.")
        parts.append(" ".join(said))
        told = memory.agent_told(bag.get("id"))
        if told:
            parts.append("Already told about this bag; do not repeat any of it:\n"
                         + "\n".join(f"- {t}" for t in told))
    else:
        parts.append("There is no bag for this brew: write nothing about a particular coffee.")
    teaser = memory.teaser
    if teaser and teaser.get("text"):
        parts.append(f"The last brew ended by promising: \"{teaser['text']}\" "
                     "The first story text keeps that promise.")
    structure: dict[str, Any] = {}
    for slot, (heading, text) in texts.stories.items():
        description = f"{_KINDS.get(slot.kind, slot.kind)}; shown {_when(slot)}."
        if slot.kind == "big_story":
            parts.append(f"Source text for the story part titled \"{heading}\": {text}")
            description += f" Retell the source text for \"{heading}\"."
        structure[slot_key(slot)] = {
            "description": description, "required": True, "selector": {"text": {}}}
    structure["teaser"] = {
        "description": "One sentence promising the next cup's topic, one not told in this brew.",
        "required": True, "selector": {"text": {}}}
    return "\n\n".join(parts), structure


def parse_reply(
    texts: BrewTexts, data: dict[str, Any],
) -> tuple[dict[Slot, tuple[str, str]], dict[str, Any] | None]:
    """The agent's texts under the built-in headings, and its teaser."""
    stories: dict[Slot, tuple[str, str]] = {}
    for slot, (heading, _text) in texts.stories.items():
        value = data.get(slot_key(slot))
        if isinstance(value, str) and value.strip():
            stories[slot] = (heading, value.strip())
    teaser = data.get("teaser")
    if isinstance(teaser, str) and teaser.strip():
        return stories, {"kind": "agent", "key": None, "text": teaser.strip()}
    return stories, None
