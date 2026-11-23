"""A brew's texts, written from the built-in content.

Pure: the slots, the pour plan, the bag's Coffee Lab facts, this bag's past
brews and the memory go in; the pour lines, the story parts and what to
remember come out. A text is written only from what is known: the bag's own
fields, its brews, and general knowledge in the content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .content import Content
from .memory import StoryMemory
from .plan import Slot

# Science topics, in the order a brew's science slots reach for them.
SCIENCE_TOPICS = ("origin", "process", "roast", "water", "extraction", "bloom")
# A bag with less than about two doses left is in its last cups.
LAST_CUPS_G = 40
# Brews with stories before deeper facts unlock.
LEVELS = ((15, 1), (40, 2))
# Figures a brew states once: a second text naming one says it again.
FIGURES = frozenset({"days_since_roast", "days_since_open", "altitude"})


def _figures(template: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", template)) & FIGURES


@dataclass
class BrewTexts:
    pour_lines: dict[int, str] = field(default_factory=dict)
    stories: dict[Slot, tuple[str, str]] = field(default_factory=dict)
    told: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    big_story_part_told: bool = False
    teaser: dict[str, Any] | None = None


def _number(value: Any) -> str | None:
    return None if value is None else f"{float(value):g}"


def _days(content: Content, since: str | None, today: date) -> str | None:
    try:
        days = (today - date.fromisoformat(since)).days if since else None
    except ValueError:
        return None
    # The day itself is not "0 days ago": nothing is said.
    return content.count(days, "day") if days is not None and days > 0 else None


def _values(bag: dict | None, history: list[dict], content: Content, today: date) -> dict[str, Any]:
    bag = bag or {}
    low, high = bag.get("altitude_m"), bag.get("altitude_max_m")
    last = history[0] if history else {}
    return {
        **{k: bag.get(k) for k in ("name", "region", "producer", "varietal", "roast")},
        # Countries and processes in the brew's language; a name the content
        # does not know stays as written, and one it maps to nothing is untold.
        "country": _named(content, "country", bag.get("country")),
        "process": _named(content, "process", bag.get("process")),
        "altitude": _altitude(content, low, high),
        "days_since_roast": _days(content, bag.get("roast_date"), today),
        "days_since_open": _days(content, bag.get("opened_on"), today),
        # Cups are counted for a bag; a brew from no bag has none.
        "brew_count": str(len(history) + 1) if bag else None,
        "last_rating": _number(last.get("rating")),
        "next_change": last.get("next_change") or None,
    }


def _named(content: Content, kind: str, value: str | None) -> str | None:
    if not value:
        return None
    names = {k.casefold(): v for k, v in content.entry(f"names.{kind}").items()}
    return names[value.casefold()] if value.casefold() in names else value


def _altitude(content: Content, low: Any, high: Any) -> str | None:
    """The height with its counted word; a range takes the form of its top."""
    if low is None:
        return None
    if high is None:
        return content.count(int(float(low)), "metre", _number(low))
    return content.count(int(float(high)), "metre", f"{_number(low)}–{_number(high)}")


def _level(brews: int) -> int:
    for limit, level in LEVELS:
        if brews < limit:
            return level
    return 3


def _phase(bag: dict, history: list[dict]) -> str:
    if len(history) < 3:
        return "intro"
    if bag.get("tracked") and bag.get("remaining_g") is not None and bag["remaining_g"] < LAST_CUPS_G:
        return "farewell"
    return "middle"


class _Writer:
    def __init__(self, plan, bag, history, memory: StoryMemory, content: Content, today) -> None:
        self.plan, self.bag, self.history = plan, bag, history
        self.memory, self.content = memory, content
        self.values = _values(bag, history, content, today)
        self.level = _level(memory.brews)
        self.out = BrewTexts()
        teaser = memory.teaser
        self.promised = teaser["key"] if teaser and teaser.get("kind") == "fact" else None
        self.said: set[str] = set()

    @property
    def _seen(self) -> set[str]:
        return self.memory.facts_seen | set(self.out.facts)

    def _heading(self, key: str, **values: Any) -> str:
        return self.content.fill(self.content.entry(f"headings.{key}"), values) or ""

    def _fact(self, topics: tuple[str, ...]) -> tuple[str, str] | None:
        """An unseen fact from any of `topics` before a seen one from the first."""
        found = []
        for topic in topics:
            picked = self.content.pick_fact(
                topic, self.values, self._seen, self.level, frozenset(self.said))
            if picked and picked[0] not in self.out.facts:
                if picked[0] not in self._seen:
                    return self._said(picked)
                found.append(picked)
        return self._said(found[0]) if found else None

    def _said(self, picked: tuple[str, str]) -> tuple[str, str]:
        self.said |= _figures(self.content.entry("facts")[picked[0]]["text"])
        return picked

    def _keep_promise(self) -> str | None:
        if not self.promised or self.promised in self.out.facts:
            return None
        fact = self.content.entry("facts").get(self.promised)
        if not fact or _figures(fact["text"]) & self.said:
            return None
        text = self.content.fill(fact["text"], self.values)
        if text:
            self.out.facts.append(self.promised)
            self.said |= _figures(fact["text"])
        return text

    def pour_line(self, pour: int) -> str | None:
        step = self.plan[pour - 1]
        template = self.content.entry("pour_lines").get(step.get("pattern") or "")
        if not template:
            return None
        return self.content.fill(template, {
            "pour": pour, "volume": _number(step.get("volume_ml")),
            "temperature": _number(step.get("temperature_c")),
        })

    def bag_story(self) -> tuple[str, str] | None:
        bean_id = self.bag["id"]
        told = set(self.memory.bag(bean_id)["told"])
        phase = _phase(self.bag, self.history)
        heading = self._heading("bag", name=self.bag.get("name"),
                                chapter=self.memory.bag(bean_id)["chapter"] + 1)
        for index, template in enumerate(self.content.entry(f"bag.{phase}")):
            key = f"bag.{phase}.{index}"
            if key in told or _figures(template) & self.said:
                continue
            text = self.content.fill(template, self.values)
            if text:
                self.out.told.append(key)
                self.said |= _figures(template)
                return heading, text
        picked = self._fact(("origin", "process"))
        if picked:
            self.out.facts.append(picked[0])
            return heading, picked[1]
        return None

    def big_story(self) -> tuple[str, str] | None:
        chapters = self.content.entry("big_story.chapters")
        bean_id = self.bag["id"] if self.bag else None
        chapter_index, part = self.memory.big_story_position(bean_id)
        chapter = chapters[chapter_index % len(chapters)]
        if part >= len(chapter["parts"]):
            return self.science()
        tasted = {c.casefold() for c in self.memory.big_story()["tasted"]}
        if self.values.get("country"):
            tasted.add(self.values["country"].casefold())
        # A chapter about no one country (processing, the cup itself) is
        # never "still ahead".
        ahead = bool(chapter["countries"]) and not any(
            c.casefold() in tasted for c in chapter["countries"])
        self.out.big_story_part_told = True
        heading = self._heading("big_story_ahead" if ahead else "big_story", title=chapter["title"])
        return heading, chapter["parts"][part]

    def science(self) -> tuple[str, str] | None:
        text = self._keep_promise()
        if text is None:
            picked = self._fact(SCIENCE_TOPICS)
            if picked is None:
                return None
            self.out.facts.append(picked[0])
            text = picked[1]
        return self._heading("science"), text

    def you(self) -> tuple[str, str] | None:
        lines = self.content.entry("you.lines")
        start = self.memory.brews % len(lines)
        line = next((t for t in (self.content.fill(lines[(start + i) % len(lines)], self.values)
                                 for i in range(len(lines))) if t), None)
        teaser = self._teaser()
        self.out.teaser = teaser
        text = " ".join(t for t in (line, teaser["text"] if teaser else None) if t)
        return (self._heading("you"), text) if text else None

    def _teaser(self) -> dict[str, Any] | None:
        # A topic this cup told already would read as a repeat when promised.
        facts = self.content.entry("facts")
        told_now = {facts[key]["topic"] for key in self.out.facts}
        for topic in SCIENCE_TOPICS:
            if topic in told_now:
                continue
            picked = self.content.pick_fact(topic, self.values, self._seen, self.level)
            if picked and picked[0] not in self._seen:
                text = self.content.fill(self.content.entry("you.teaser.fact"),
                                         {"topic": self.content.entry(f"topics.{topic}")})
                return {"kind": "fact", "key": picked[0], "text": text}
        chapters = self.content.entry("big_story.chapters")
        bean_id = self.bag["id"] if self.bag else None
        chapter = chapters[self.memory.big_story_position(bean_id)[0] % len(chapters)]
        text = self.content.fill(self.content.entry("you.teaser.big_story"), {"title": chapter["title"]})
        return {"kind": "big_story", "key": chapter["key"], "text": text} if text else None


def compose(
    slots: list[Slot], plan: list[dict] | None, bag: dict | None, history: list[dict],
    memory: StoryMemory, content: Content, today: date,
) -> BrewTexts:
    writer = _Writer(plan or [], bag, history, memory, content, today)
    for slot in slots:
        if slot.kind == "you":
            continue
        if slot.kind == "pour_line":
            if (text := writer.pour_line(slot.pour)) is not None:
                writer.out.pour_lines[slot.pour] = text
            continue
        story = {
            "bag": writer.bag_story if bag else writer.big_story,
            "big_story": writer.big_story,
            "science": writer.science,
            "you": writer.you,
        }[slot.kind]()
        if story is not None:
            writer.out.stories[slot] = story
    # A promise the brew had no science slot for is kept on its first pour,
    # before the closing line chooses the next promise.
    if writer.promised and 1 in writer.out.pour_lines and (kept := writer._keep_promise()):
        writer.out.pour_lines[1] = f"{writer.out.pour_lines[1]} {kept}"
    for slot in slots:
        if slot.kind == "you" and (story := writer.you()) is not None:
            writer.out.stories[slot] = story
    return writer.out
