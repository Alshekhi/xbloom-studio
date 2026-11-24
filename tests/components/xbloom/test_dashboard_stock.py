"""The dashboard's stock: on the Brew tab for the picked recipe, and its level on the bags tab."""
from .test_water_wording import _build, _cards

KINDS = ("coffee", "tea", "xpod")


def _stock_lines(build, lang):
    return [c for c in _cards(build.dashboard(lang))
            if c.get("type") == "markdown" and "_stock'" in str(c.get("content"))]


def test_the_brew_tab_shows_the_stock_of_the_picked_recipe_s_kind_only_while_low():
    build = _build()
    for lang in ("en", "ar"):
        brew = build.brew_view(build.TEXT[lang])
        lines = [c for c in _cards(brew) if c.get("type") == "markdown" and "_stock'" in str(c.get("content"))]
        assert len(lines) == 3, lang
        for kind, card in zip(KINDS, lines):
            assert f"sensor.xbloom_studio_{kind}_stock" in card["content"]
            assert {"condition": "state", "entity": f"binary_sensor.xbloom_studio_{kind}_stock_low",
                    "state": "on"} in card["visibility"]


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


import re
from datetime import date, datetime

import jinja2


def _render(template, states, attrs):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_replace"] = lambda s, find, repl: re.sub(find, repl, s)
    env.globals["states"] = lambda e: states.get(e, "unknown")
    env.globals["state_attr"] = lambda e, n: attrs.get(e, {}).get(n)
    env.globals["is_state"] = lambda e, v: states.get(e) == v
    env.globals["now"] = lambda: datetime(2026, 9, 26, 10, 0)
    env.globals["as_datetime"] = lambda text, default=None: datetime.fromisoformat(text)
    return env.from_string(template).render().replace("\u2068", "").replace("\u2069", "")


COFFEE = "sensor.xbloom_studio_coffee_stock"


def _coffee(measure, value, least=None, low="off"):
    states = {COFFEE: value, "binary_sensor.xbloom_studio_coffee_stock_low": low}
    return states, {COFFEE: {"measure": measure, "at_least": least, "unknown": 0}}


def test_the_bags_tab_says_what_is_left_and_calls_an_estimate_about():
    build = _build()
    t = build.TEXT["en"]
    say = lambda *a, **k: _render(build.stock_line(t, "coffee"), *_coffee(*a, **k))  # noqa: E731
    assert say("days", "67.4") == "Coffee left: about 67 days"
    assert say("days", "1") == "Coffee left: about 1 day"
    assert say("cups", "37") == "Coffee left: about 37 cups"
    assert say("grams", "640.0") == "Coffee left: 640 g"
    assert say("bags", "3") == "Coffee left: 3 bags"
    assert say("days", "unknown", least=12) == "Coffee left: at least 12 days"
    assert say("days", "5", low="on") == "Coffee left: about 5 days Running low."


def test_the_brew_tab_line_says_it_is_running_low():
    build = _build()
    line = _render(build.stock_low_line(build.TEXT["en"], "coffee"), *_coffee("days", "5", low="on"))
    assert line == "Running low on coffee: about 5 days left."


def test_arabic_counts_each_number_its_own_way():
    build = _build()
    t = build.TEXT["ar"]
    say = lambda v: _render(build.stock_line(t, "coffee"), *_coffee("days", v))  # noqa: E731
    assert say("1") == "المتبقي من القهوة: يوم واحد تقريبًا"
    assert say("2") == "المتبقي من القهوة: يومان تقريبًا"
    assert say("5") == "المتبقي من القهوة: 5 أيام تقريبًا"
    assert say("67") == "المتبقي من القهوة: 67 يومًا تقريبًا"


def test_tea_by_the_pack_and_xpods_by_the_pod():
    build = _build()
    t = build.TEXT["en"]
    tea = "sensor.xbloom_studio_tea_stock"
    out = _render(build.stock_line(t, "tea"), {tea: "2"}, {tea: {"measure": "bags", "at_least": None}})
    assert out == "Tea left: 2 packs"
    pod = "sensor.xbloom_studio_xpod_stock"
    out = _render(build.stock_line(t, "xpod"), {pod: "12"}, {pod: {"measure": "pods", "at_least": None}})
    assert out == "xPods left: 12 pods"


BAGS = [
    {"id": "o1", "name": "Hill Farm", "status": "open", "kind": "coffee", "country": "Kenya",
     "process": "Washed", "remaining_g": 36, "bag_size_g": 250, "opened_on": "2026-09-20"},
    {"id": "u1", "name": "Valley Lot", "status": "unopened", "kind": "coffee", "country": "Peru",
     "process": "Natural", "remaining_g": None, "bag_size_g": 250, "roast_date": "2026-09-15"},
    {"id": "u2", "name": "Ridge Top", "status": "unopened", "kind": "coffee", "country": "",
     "process": "", "remaining_g": None, "bag_size_g": 250, "roast_date": "2026-09-01"},
]


def _bag_cards(build, lang="en"):
    view = build.bags_view(build.TEXT[lang])
    cards = [c for c in _cards(view) if c.get("type") == "markdown" and "sensor.xbloom_studio_coffee_bags" in str(c.get("content"))]
    attrs = {"sensor.xbloom_studio_coffee_bags": {"bags": BAGS},
             "select.xbloom_studio_coffee_bag": {"id": "o1"}}
    return [_render(c["content"], {}, attrs) for c in cards]


def test_open_and_unopened_bags_are_listed_apart():
    build = _build()
    open_list, unopened, empty = _bag_cards(build)
    assert open_list.startswith("## Open bags")
    assert "- **Hill Farm** (in use) · Kenya · Washed · 36 of 250 g left · opened 6 days ago" in open_list
    assert "Valley Lot" not in open_list
    assert unopened.splitlines()[0] == "## Unopened bags"
    # Oldest roast first, each with what it holds.
    assert unopened.splitlines()[2:] == ["- **Ridge Top** · 250 g", "- **Valley Lot** · Peru · Natural · 250 g"]
    assert empty == ""


def test_no_heading_for_a_list_with_nothing_in_it():
    build = _build()
    view = build.bags_view(build.TEXT["en"])
    cards = [c for c in _cards(view) if c.get("type") == "markdown" and "sensor.xbloom_studio_coffee_bags" in str(c.get("content"))]
    only_open = {"sensor.xbloom_studio_coffee_bags": {"bags": BAGS[:1]}, "select.xbloom_studio_coffee_bag": {"id": "x"}}
    assert _render(cards[1]["content"], {}, only_open) == ""
    assert all(c.get("show_empty") is False for c in cards)


def test_a_bag_missing_optional_details_still_lists_under_strict_templates():
    build = _build()
    view = build.bags_view(build.TEXT["en"])
    cards = [c for c in _cards(view) if c.get("type") == "markdown" and "sensor.xbloom_studio_coffee_bags" in str(c.get("content"))]
    bare = [{"id": "a", "name": "Bare", "status": "unopened"}, {"id": "b", "name": "Open Bare", "status": "open"}]
    attrs = {"sensor.xbloom_studio_coffee_bags": {"bags": bare}, "select.xbloom_studio_coffee_bag": {"id": None}}
    out = [_render(c["content"], {}, attrs) for c in cards]
    assert "- **Open Bare** · not tracked" in out[0]
    assert "- **Bare** · not tracked" in out[1]


def test_nothing_left_is_said_as_such():
    build = _build()
    for lang, text in (("en", "No coffee left."), ("ar", "نفد مخزون القهوة.")):
        t = build.TEXT[lang]
        assert _render(build.stock_line(t, "coffee"), *_coffee("days", "0")) == text
        assert _render(build.stock_low_line(t, "coffee"), *_coffee("days", "0", low="on")) == text


def test_the_low_line_reads_for_every_kind():
    build = _build()
    t = build.TEXT["en"]
    pod = "sensor.xbloom_studio_xpod_stock"
    out = _render(build.stock_low_line(t, "xpod"), {pod: "3"}, {pod: {"measure": "pods", "at_least": None}})
    assert out == "Running low on xPods: 3 pods left."
    ar = _render(build.stock_low_line(build.TEXT["ar"], "xpod"), {pod: "1"}, {pod: {"measure": "pods", "at_least": None}})
    assert ar == "مخزون كبسولات xPod منخفض، والمتبقي كبسولة واحدة."


def test_a_picked_unopened_bag_says_it_is_in_use():
    build = _build()
    view = build.bags_view(build.TEXT["en"])
    cards = [c for c in _cards(view) if c.get("type") == "markdown" and "sensor.xbloom_studio_coffee_bags" in str(c.get("content"))]
    attrs = {"sensor.xbloom_studio_coffee_bags": {"bags": BAGS}, "select.xbloom_studio_coffee_bag": {"id": "u1"}}
    assert "- **Valley Lot** (in use) · Peru · Natural · 250 g" in _render(cards[1]["content"], {}, attrs)
