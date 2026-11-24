"""The dashboard's stock: on the Brew tab for the picked recipe, and its level on the bags tab."""
from .test_water_wording import _build, _cards

KINDS = ("coffee", "tea", "xpod")


def _stock_lines(build, lang):
    return [c for c in _cards(build.dashboard(lang))
            if c.get("type") == "markdown" and "_stock'" in str(c.get("content"))]


def test_the_brew_tab_shows_the_stock_of_the_picked_recipe_s_kind():
    build = _build()
    for lang in ("en", "ar"):
        brew = build.brew_view(build.TEXT[lang])
        lines = [c for c in _cards(brew) if c.get("type") == "markdown" and "_stock'" in str(c.get("content"))]
        assert len(lines) == 3, lang
        for kind, card in zip(KINDS, lines):
            assert f"sensor.xbloom_studio_{kind}_stock" in card["content"]
            # Shown while its sensor exists, even while its figure is only a floor.
            assert {"condition": "state", "entity": f"sensor.xbloom_studio_{kind}_stock",
                    "state_not": "unavailable"} in card["visibility"]
            assert not any(v.get("state_not") == "unknown" for v in card["visibility"])


def test_the_stock_line_says_running_low_while_low():
    build = _build()
    t = build.TEXT["en"]
    line = build.stock_line(t, "coffee")
    assert "is_state('binary_sensor.xbloom_studio_coffee_stock_low', 'on')" in line
    assert t["stock_low"] in line and "at_least" in line


def test_the_bags_tab_has_measure_and_level_per_kind():
    build = _build()
    cards = list(_cards(build.bags_view(build.TEXT["en"])))
    entities = {c.get("entity") for c in cards}
    for kind in KINDS:
        assert {f"select.xbloom_studio_{kind}_stock_measure",
                f"number.xbloom_studio_{kind}_stock_level"} <= entities


def test_a_figure_not_known_yet_says_so_in_words_and_asks_for_a_weighing():
    build = _build()
    for lang in ("en", "ar"):
        t = build.TEXT[lang]
        line = build.stock_line(t, "coffee")
        assert t["stock_not_yet"].replace("{kind}", t["kind_coffee"]) in line and t["stock_weigh"] in line
        assert "states('sensor.xbloom_studio_coffee_stock') in ['unknown', 'unavailable']" in line
