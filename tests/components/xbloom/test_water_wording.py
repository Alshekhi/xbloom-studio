"""Water is named as water, not as the tank, wherever it is spoken or shown.

Everyone at the machine knows what to refill; saying "the tank" in every
line only makes each one longer. The low-water switch trips with water
still in the tank, so its status says the water is low, not gone.
"""
import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
COMPONENT = ROOT / "custom_components" / "xbloom"


class _Loader(yaml.SafeLoader):
    """Reads `!input name` as a plain string."""


_Loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


def _variables(name):
    text = (COMPONENT / "blueprints" / name).read_text(encoding="utf-8")
    return yaml.load(text, Loader=_Loader)["variables"]


def test_no_spoken_line_names_the_tank():
    for name in ("machine_fault_announce.yaml", "brew_announce.yaml", "live_control_announce.yaml"):
        for key, value in _variables(name).items():
            if isinstance(value, str):
                spoken = re.sub(r"\{#.*?#\}", "", value, flags=re.S)   # comments are not said
                assert "الخزان" not in spoken, (name, key)
                assert "the tank" not in spoken, (name, key)


def test_low_water_is_shown_as_low_not_gone():
    for path, expected in (("strings.json", "Low water"), ("translations/en.json", "Low water"),
                           ("translations/ar.json", "الماء قليل")):
        data = json.loads((COMPONENT / path).read_text(encoding="utf-8"))
        assert data["entity"]["sensor"]["machine_status"]["state"]["no_water"] == expected


def test_a_refused_command_does_not_name_the_tank():
    for path in ("strings.json", "translations/en.json", "translations/ar.json"):
        message = json.loads((COMPONENT / path).read_text(encoding="utf-8"))[
            "exceptions"]["refused_no_water"]["message"]
        assert "الخزان" not in message and "tank" not in message


def _build():
    spec = importlib.util.spec_from_file_location("dashboard_build", ROOT / "dashboard" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cards(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _cards(value)
    elif isinstance(node, list):
        for value in node:
            yield from _cards(value)


def test_the_dashboard_shows_the_water_during_a_brew():
    build = _build()
    for lang in ("en", "ar"):
        water = [c for c in _cards(build.dashboard(lang))
                 if c.get("type") == "markdown" and "water_left_ml" in str(c.get("content"))]
        assert len(water) == 1, lang
        card = water[0]
        assert card["show_empty"] is False
        assert {"condition": "state", "entity": "sensor.xbloom_studio_machine_status",
                "state": "no_water"} in card["visibility"]


def test_the_dashboard_does_not_name_the_tank():
    build = _build()
    for lang in ("en", "ar"):
        assert "خزان" not in build.TEXT[lang]["need_water"]
        assert "tank" not in build.TEXT[lang]["need_water"]


def test_the_dashboard_shows_the_water_poured_during_a_brew():
    build = _build()
    for lang, label in (("en", "Water poured"), ("ar", "الماء المصبوب")):
        poured = [c for c in _cards(build.dashboard(lang))
                  if c.get("type") == "markdown" and "xbloom_studio_water_poured" in str(c.get("content"))]
        assert len(poured) == 1, lang
        assert label in poured[0]["content"]
        assert poured[0]["visibility"] == build.present("sensor.xbloom_studio_water_poured")
