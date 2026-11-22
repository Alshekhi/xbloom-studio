"""The texts Brew Stories tells, one file per language under `content/`.

A template is filled only when every value it names is known: a text with a
blank in it, or "None", never reaches the screen. Counted words take their
language's forms (Arabic has six) rather than a fixed plural after a number.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).parent / "content"
FALLBACK = "en"


class _Missing(Exception):
    pass


class _Known(dict):
    """Template values that refuse anything unknown."""

    def __missing__(self, key: str) -> str:
        raise _Missing(key)

    def __getitem__(self, key: str) -> Any:
        value = super().__getitem__(key)
        if value is None or value == "":
            raise _Missing(key)
        return value


def _arabic_form(n: int) -> str:
    if n == 0:
        return "zero"
    if n == 1:
        return "one"
    if n == 2:
        return "two"
    rest = n % 100
    if 3 <= rest <= 10:
        return "few"
    if 11 <= rest <= 99:
        return "many"
    return "other"


class Content:
    def __init__(self, lang: str, data: dict[str, Any]) -> None:
        self.lang = lang
        self._data = data

    @classmethod
    def load(cls, lang: str, folder: Path | None = None) -> Content:
        folder = folder or FOLDER
        path = folder / f"{lang}.json"
        if not path.exists():
            lang, path = FALLBACK, folder / f"{FALLBACK}.json"
        return cls(lang, json.loads(path.read_text(encoding="utf-8")))

    def entry(self, path: str) -> Any:
        node: Any = self._data
        for part in path.split("."):
            node = node[part]
        return node

    def fill(self, template: str, values: dict[str, Any]) -> str | None:
        try:
            return template.format_map(_Known(values))
        except _Missing:
            return None

    def count(self, n: int, key: str) -> str:
        forms = self._data["counts"][key]
        form = _arabic_form(n) if self.lang == "ar" else ("one" if n == 1 else "other")
        return (forms.get(form) or forms["other"]).replace("{n}", str(n))

    def pick_fact(
        self, topic: str, values: dict[str, Any], seen: set[str], level: int
    ) -> tuple[str, str] | None:
        """An unseen fact on `topic` that can be told; a seen one once all are."""
        told: list[tuple[str, str]] = []
        for key in sorted(self._data.get("facts", {})):
            fact = self._data["facts"][key]
            if fact["topic"] != topic or fact["level"] > level:
                continue
            text = self.fill(fact["text"], values)
            if text is None:
                continue
            if key not in seen:
                return key, text
            told.append((key, text))
        return told[0] if told else None
