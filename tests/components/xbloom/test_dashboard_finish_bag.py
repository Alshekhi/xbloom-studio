"""The Bags tab's Weigh or finish a bag: a picker, what is left as a typed amount, and Finish."""
from .test_water_wording import _build, _cards

PICKER = "select.xbloom_studio_bag_to_finish"
GRAMS = "number.xbloom_studio_grams_left_in_bag"
BUTTON = "button.xbloom_studio_finish_chosen_bag"


def _section(build, lang="en"):
    view = build.bags_view(build.TEXT[lang])
    return next(s for s in view["sections"] if BUTTON in str(s))


def test_the_section_shows_while_there_is_an_open_bag():
    build = _build()
    section = _section(build)
    assert any(v.get("entity") == PICKER and v.get("state_not") == "unavailable" for v in section["visibility"])
    entities = [c.get("entity") for c in _cards(section)]
    assert PICKER in entities and GRAMS in entities and BUTTON in entities


def test_grams_left_is_a_row_that_takes_a_typed_amount():
    build = _build()
    for lang in ("en", "ar"):
        card = next(c for c in _section(build, lang)["cards"] if GRAMS in str(c))
        assert card["type"] == "entities"
        assert card["entities"] == [{"entity": GRAMS, "name": build.TEXT[lang]["f_grams"]}]
        assert card["visibility"] == [{"condition": "state", "entity": GRAMS, "state_not": "unavailable"}]


def test_finish_asks_for_confirmation():
    build = _build()
    for lang in ("en", "ar"):
        button = next(c for c in _cards(_section(build, lang)) if c.get("entity") == BUTTON)
        assert button["tap_action"]["confirmation"]["text"] == build.TEXT[lang]["f_confirm"]
    assert build.TEXT["en"]["f_confirm"] == "Finish this bag?"
