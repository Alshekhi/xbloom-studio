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
        "- **Most brewed coffee:** Hill Farm (8)",
        "- **Most brewed recipe:** Daily \\| Hot (12)",
        "- **Usually brewed:** in the morning",
        "- **Verdicts:** Keep it like this (5) · Doesn't suit this coffee (1)",
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
    assert "\u2068Daily \\| Hot\u2069 (12)" in summary
    assert "\u2068Hill Farm\u2069, \u2068Valley Lot\u2069" in summary
    recent = _render(build.recent_card(build.TEXT["en"]), attrs, raw=True)
    assert "\u2068Daily | Hot\u2069 · \u2068Hill Farm\u2069" in recent


def test_a_brew_without_a_verdict_renders_under_strict_templates():
    build = _build()
    out = _render(build.recent_card(build.TEXT["en"]),
                  {"sensor.xbloom_studio_recent_brews": {"brews": [{"recipe": "Plain", "id": "4"}]}})
    assert "<summary>Plain</summary>" in out
