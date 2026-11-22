"""The shipped story content: the same in both languages, sourced, and short."""
from __future__ import annotations

import json
import re
from pathlib import Path

FOLDER = Path(__file__).parents[3] / "custom_components" / "xbloom" / "stories" / "content"
EN = json.loads((FOLDER / "en.json").read_text(encoding="utf-8"))
AR = json.loads((FOLDER / "ar.json").read_text(encoding="utf-8"))
KNOWN = {"pour", "volume", "temperature", "name", "country", "region", "producer", "process",
         "varietal", "roast", "altitude", "days_since_roast", "days_since_open", "brew_count",
         "last_rating", "next_change", "title", "topic", "chapter", "n"}
TOPICS = ("bloom", "extraction", "origin", "process", "roast", "water")


def _shape(node):
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in node.items() if k not in ("source",)}
    if isinstance(node, list):
        return [_shape(v) for v in node]
    return type(node).__name__


def _texts(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in ("source", "topic", "key", "countries", "level"):
                yield from _texts(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _texts(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def test_both_languages_have_the_same_shape():
    shape_en, shape_ar = _shape(EN), _shape(AR)
    # Count forms differ by language; everything else matches.
    shape_en.pop("counts"), shape_ar.pop("counts")
    assert shape_en == shape_ar


def test_every_placeholder_is_known_and_in_both_languages():
    en, ar = dict(_texts(EN)), dict(_texts(AR))
    for path, text in en.items():
        if path.startswith(".counts"):
            continue
        names = set(re.findall(r"{(\w+)}", text))
        assert names <= KNOWN, (path, names - KNOWN)
        assert names == set(re.findall(r"{(\w+)}", ar[path])), path


def test_every_fact_and_chapter_has_a_source():
    for language in (EN, AR):
        assert all(f.get("source") for f in language["facts"].values())
        assert all(c.get("source") for c in language["big_story"]["chapters"])


def test_every_topic_has_facts_at_every_level():
    for topic in TOPICS:
        facts = [f for f in EN["facts"].values() if f["topic"] == topic]
        assert len(facts) >= 6, topic
        assert {f["level"] for f in facts} == {1, 2, 3}, topic


def test_there_are_twelve_chapters_of_three_parts():
    chapters = EN["big_story"]["chapters"]
    assert len(chapters) == 12 and all(len(c["parts"]) == 3 for c in chapters)


def test_no_text_is_longer_than_three_sentences():
    for language in (EN, AR):
        for path, text in _texts(language):
            sentences = [s for s in re.split(r"[.!?؟]+\s*", text) if s.strip()]
            assert len(sentences) <= 3, (path, text)
