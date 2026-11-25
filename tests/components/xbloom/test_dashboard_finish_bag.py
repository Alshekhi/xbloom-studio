"""The Bags tab's Finish a bag: a picker, what is left in the chosen bag, and Finish."""
import re

from .test_dashboard_stock import _render
from .test_water_wording import _build, _cards

PICKER = "select.xbloom_studio_bag_to_finish"
BUTTON = "button.xbloom_studio_finish_chosen_bag"


def _section(build, lang="en"):
    view = build.bags_view(build.TEXT[lang])
    return next(s for s in view["sections"] if BUTTON in str(s))


def _line(build, lang, chosen, attrs):
    card = next(c for c in _section(build, lang)["cards"] if c.get("type") == "markdown" and PICKER in c.get("content", ""))
    out = _render(card["content"], {PICKER: chosen}, {PICKER: attrs})
    # Markdown escapes, as the card renders them.
    return re.sub(r"\\(.)", r"\1", out).replace("⁨", "").replace("⁩", "").replace("**", "")


def test_the_section_shows_while_there_is_a_bag_to_finish():
    build = _build()
    section = _section(build)
    assert any(v.get("entity") == PICKER and v.get("state_not") == "unavailable" for v in section["visibility"])
    entities = [c.get("entity") for c in _cards(section)]
    assert PICKER in entities and BUTTON in entities


def test_finish_asks_for_confirmation():
    build = _build()
    for lang in ("en", "ar"):
        button = next(c for c in _cards(_section(build, lang)) if c.get("entity") == BUTTON)
        assert button["tap_action"]["confirmation"]["text"] == build.TEXT[lang]["f_confirm"]
    assert build.TEXT["en"]["f_confirm"] == "Finish this bag?"


def test_the_chosen_bag_is_named_with_what_is_left():
    build = _build()
    assert _line(build, "en", "Kenya (2026-09-03)", {"remaining_g": 8.5, "tracked": True}) == "Kenya (2026-09-03): 8.5 g left"
    assert _line(build, "en", "Gayo", {"remaining_g": None, "tracked": False}) == "Gayo: amount not known"
    assert _line(build, "ar", "Gayo", {"remaining_g": None, "tracked": False}) == "Gayo: الكمية غير معروفة"
    assert _line(build, "en", "unknown", {}) == ""
