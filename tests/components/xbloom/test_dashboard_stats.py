"""The Stats tab's summary of habits and its list of recent brews, rendered."""
import re
from datetime import datetime

import jinja2

from .test_water_wording import _build, _cards

HABITS = {
    "days_brewed": 18, "days_in_period": 24, "longest_streak_days": 6,
    "cups_per_brewing_day": 1.2,
    "usual": {"hot": {"dose_g": 17.0, "ratio": 15.0, "brews": 20},
              "iced": {"dose_g": 20.0, "ratio": 8.0, "brews": 4}},
    "top_coffee": {"name": "Hill Farm", "brews": 8},
    "top_recipe": {"name": "Daily | Hot", "brews": 12},
    "verdicts": {"again": 5, "not_again": 1},
    "time_of_day": "morning",
    "bags_opened": ["Hill Farm", "Valley Lot"],
}
BREWS = [
    {"brewed_at": "2026-09-24T12:24+00:00", "recipe": "Daily | Hot", "bag": "Hill Farm",
     "dose_g": 17.0, "ratio": 15.0, "water_ml": 255.0, "grind": "50.0", "temperature_c": 89.0,
     "flow_rate": 3.5, "duration_s": 195.6, "brewer": "xBloom Studio", "verdict": "again",
     "tasting": {"body": "full", "finish": "toffee"}, "next_change": "grind 52", "id": "1"},
    {"brewed_at": "2026-09-23T08:00+00:00", "bag": "Valley Lot", "dose_g": 28.0,
     "brewer": "Pour-over", "id": "2"},
]


def _render(template: str, attrs: dict, raw: bool = False) -> str:
    # Strict, as the dashboard's markdown card renders: a missing key is an
    # error there, not an empty value.
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_replace"] = lambda s, find, repl: re.sub(find, repl, s)
    env.globals["state_attr"] = lambda entity, name: attrs.get(entity, {}).get(name)
    def as_datetime(text, default=None):
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return default
    env.globals["as_datetime"] = as_datetime
    out = env.from_string(template).render()
    # The direction marks around names are checked on their own below.
    return out if raw else out.replace("\u2068", "").replace("\u2069", "")


def test_the_summary_reads_each_habit():
    build = _build()
    out = _render(build.summary_card(build.TEXT["en"]),
                  {"sensor.xbloom_studio_brews": {"habits": HABITS}})
    lines = [line for line in out.splitlines() if line]
    assert lines == [
        "## Summary",
        "- **Days brewed:** 18 of 24",
        "- **Most days in a row:** 6",
        "- **Cups on a brewing day:** 1.2",
        "- **Usual hot cup:** 17 g at 1:15",
        "- **Usual iced cup:** 20 g at 1:8",
        "- **Usually brewed:** in the morning",
        "- **Bags opened:** Hill Farm, Valley Lot",
    ]


def test_the_summary_leaves_out_what_the_brews_do_not_show():
    build = _build()
    thin = {"days_brewed": 1, "days_in_period": 7, "longest_streak_days": 1,
            "cups_per_brewing_day": 1.0, "usual": {}, "top_coffee": None, "top_recipe": None,
            "verdicts": {}, "time_of_day": None, "bags_opened": []}
    out = _render(build.summary_card(build.TEXT["en"]), {"sensor.xbloom_studio_brews": {"habits": thin}})
    assert [line for line in out.splitlines() if line] == [
        "## Summary", "- **Days brewed:** 1 of 7", "- **Cups on a brewing day:** 1",
    ]


def test_each_recent_brew_opens_to_how_it_was_made():
    build = _build()
    out = _render(build.recent_card(build.TEXT["en"]),
                  {"sensor.xbloom_studio_recent_brews": {"brews": BREWS}})
    first, second = out.split("</details>")[:2]
    assert "<summary>24/09 12:24 · Daily | Hot · Hill Farm · Keep it like this</summary>" in first
    for line in ("- **Dose:** 17 g · 1:15", "- **Water:** 255 ml",
                 "- **Grind:** 50", "- **Temp:** 89°", "- **Flow:** 3.5 ml/s",
                 "- **Brew time:** 3:15",
                 "- **Body:** full", "- **Finish:** toffee", "- **Next change:** grind 52"):
        assert line in first, line
    assert "<summary>23/09 08:00 · Valley Lot</summary>" in second
    assert "- **Brewer:** Pour-over" in second and "Grind" not in second
    assert "Brewer" not in first


def test_both_languages_render_and_the_view_carries_both_cards():
    build = _build()
    attrs = {"sensor.xbloom_studio_brews": {"habits": HABITS},
             "sensor.xbloom_studio_recent_brews": {"brews": BREWS}}
    ar = build.TEXT["ar"]
    assert "في الصباح" in _render(build.summary_card(ar), attrs)
    assert "أعتمدها كما هي" in _render(build.recent_card(ar), attrs)
    contents = [str(c.get("content")) for c in _cards(build.stats_view(build.TEXT["en"]))]
    assert any("'habits'" in c for c in contents)
    assert any("sensor.xbloom_studio_recent_brews" in c for c in contents)


def test_a_brew_without_a_time_or_a_numeric_grind_still_shows():
    build = _build()
    odd = [{"bag": "Valley Lot", "grind": "medium fine", "dose_g": 15.0, "id": "3"}]
    out = _render(build.recent_card(build.TEXT["en"]), {"sensor.xbloom_studio_recent_brews": {"brews": odd}})
    assert "<summary>Valley Lot</summary>" in out
    assert "- **Grind:** medium fine" in out


def test_an_opened_brew_does_not_repeat_its_summary_line():
    build = _build()
    out = _render(build.recent_card(build.TEXT["en"]), {"sensor.xbloom_studio_recent_brews": {"brews": BREWS}})
    first = out.split("</details>")[0]
    assert first.count("Hill Farm") == 1 and first.count("Keep it like this") == 1


def test_no_summary_while_the_habits_could_not_be_read():
    build = _build()
    out = _render(build.summary_card(build.TEXT["en"]), {"sensor.xbloom_studio_brews": {"habits": {}}})
    assert out.strip() == ""


def test_names_keep_their_own_direction():
    build = _build()
    attrs = {"sensor.xbloom_studio_brews": {"habits": HABITS},
             "sensor.xbloom_studio_recent_brews": {"brews": BREWS}}
    summary = _render(build.summary_card(build.TEXT["en"]), attrs, raw=True)
    assert "\u2068Hill Farm\u2069, \u2068Valley Lot\u2069" in summary
    recent = _render(build.recent_card(build.TEXT["en"]), attrs, raw=True)
    assert "\u2068Daily | Hot\u2069 · \u2068Hill Farm\u2069" in recent


def test_a_brew_without_a_verdict_renders_under_strict_templates():
    build = _build()
    out = _render(build.recent_card(build.TEXT["en"]),
                  {"sensor.xbloom_studio_recent_brews": {"brews": [{"recipe": "Plain", "id": "4"}]}})
    assert "<summary>Plain</summary>" in out


STATS = "sensor.xbloom_studio_brews"
HISTORY = "sensor.xbloom_studio_brew_history"


def _card(build, needle, lang="en"):
    view = build.stats_view(build.TEXT[lang])
    return next(c for c in _cards(view) if c.get("type") == "markdown" and needle in c.get("content", ""))


def test_the_brewers_are_one_line_in_coffee_stats_and_no_section_of_their_own():
    build = _build()
    card = _card(build, "'by_brewer'")
    out = _render(card["content"], {STATS: {"coffee_g": 648, "water_ml": 8492, "by_brewer": {"xBloom Studio": 35, "V60": 1, "other": 2},
                                            "previous_period": {"brews": 32}}})
    assert "- **Brewers:** xBloom Studio (35), V60 (1), Other (2)" in out
    headings = [c["content"] for c in _cards(build.stats_view(build.TEXT["en"])) if c.get("text_only")]
    assert "## By brewer" not in headings


def test_each_coffee_and_recipe_as_a_table():
    build = _build()
    habits = {**HABITS, "by_coffee": [{"name": "Hill Farm", "brews": 8, "coffee_g": 136.0}],
              "by_recipe": [{"name": "Daily | Hot", "brews": 12, "verdicts": {"again": 2, "not_again": 1}}]}
    coffee = _render(_card(build, "'by_coffee'")["content"], {STATS: {"habits": habits}})
    assert "| Coffee | Cups | Grams |" in coffee and "| Hill Farm | 8 | 136 |" in coffee
    recipe = _render(_card(build, "'by_recipe'")["content"], {STATS: {"habits": habits}})
    assert "| Recipe | Cups | Verdicts |" in recipe
    assert "| Daily \\| Hot | 12 | Keep it like this (2), Doesn't suit this coffee (1) |" in recipe


def test_the_history_as_tables_above_the_charts():
    build = _build()
    section = next(s for s in build.stats_view(build.TEXT["en"])["sections"] if HISTORY in str(s))
    kinds = [c["type"] for c in section["cards"]]
    assert kinds.index("markdown", 1) < kinds.index("statistics-graph")
    rows = {"by_month": [{"start": "2026-11-01", "brews": 26, "coffee_g": 460.0, "water_ml": 6800.0}],
            "by_week": [{"start": "2026-11-23", "brews": 2, "coffee_g": 34.0, "water_ml": 510.0}]}
    out = _render(_card(build, "'by_month'")["content"], {HISTORY: rows})
    assert "| Month | Brews | Coffee | Water |" in out and "| November 2026 | 26 | 460 g | 6800 ml |" in out
    assert "| Week of | Brews | Coffee | Water |" in out and "| 23/11 | 2 | 34 g | 510 ml |" in out
    ar = _render(_card(build, "'by_month'", "ar")["content"], {HISTORY: rows})
    assert "نوفمبر 2026" in ar


def test_the_list_is_the_brews_of_this_period():
    build = _build()
    headings = [c["content"] for c in _cards(build.stats_view(build.TEXT["en"])) if c.get("text_only")]
    assert "## Brews in this period" in headings


def test_the_summary_leaves_the_coffee_recipe_and_verdicts_to_their_tables():
    build = _build()
    out = _render(build.summary_card(build.TEXT["en"]), {"sensor.xbloom_studio_brews": {"habits": HABITS}})
    assert "Most brewed" not in out and "Verdicts" not in out


def test_an_empty_coffee_or_recipe_table_shows_nothing():
    build = _build()
    for needle in ("'by_coffee'", "'by_recipe'"):
        card = _card(build, needle)
        assert card.get("show_empty") is False
        assert _render(card["content"], {STATS: {"habits": {"by_coffee": [], "by_recipe": []}}}).strip() == ""


def test_a_week_of_another_year_says_its_year_and_no_water_reads_blank():
    build = _build()
    rows = {"by_month": [], "by_week": [{"start": "2025-12-29", "brews": 1, "coffee_g": 17.0, "water_ml": 0.0}]}
    out = _render(_card(build, "'by_month'")["content"], {HISTORY: rows, "sensor.xbloom_studio_brews": {}})
    assert "| 29/12/2025 | 1 | 17 g |  |" in out


def test_no_history_shows_no_tables():
    build = _build()
    out = _render(_card(build, "'by_month'")["content"], {HISTORY: {"by_month": [], "by_week": []}})
    assert out.strip() == ""
