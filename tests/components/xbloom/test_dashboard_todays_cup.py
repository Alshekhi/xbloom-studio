"""The Brew tab's Today's cup: what it says, and when it shows."""
from .test_dashboard_stock import _render
from .test_water_wording import _build, _cards

CUP = "sensor.xbloom_studio_todays_cup"


def _section(build, lang="en"):
    brew = build.brew_view(build.TEXT[lang])
    return next(s for s in brew["sections"] if CUP in str(s))


def _say(build, attrs, lang="en"):
    card = next(c for c in _section(build, lang)["cards"] if c.get("type") == "markdown" and CUP in c.get("content", ""))
    out = _render(card["content"], {CUP: attrs.get("bag", "unknown")}, {CUP: attrs})
    return out.replace("⁨", "").replace("⁩", "")


def test_it_names_the_bag_the_recipe_and_the_dose_and_why():
    build = _build()
    attrs = {"bag": "Hill Farm", "recipe": "Daily", "dose_g": 17.0, "reasons": ["not_yesterday", "rated_again"]}
    assert _say(build, attrs) == (
        "Hill Farm · Daily · 17 g\n\n"
        "Not the coffee you had last, rated Keep it like this with it.")


def test_a_recipe_reason_alone_starts_the_sentence():
    build = _build()
    attrs = {"bag": "Hill Farm", "recipe": "Daily", "dose_g": 17.0, "reasons": ["brewed_with_bag"]}
    assert _say(build, attrs).endswith("Brewed with it before.")


def test_the_bag_alone_with_no_recipe():
    build = _build()
    attrs = {"bag": "Hill Farm", "recipe": None, "dose_g": 17.0, "reasons": ["open_next"]}
    assert _say(build, attrs) == "Hill Farm\n\nTime to open it."


def test_arabic_reads_its_own_words():
    build = _build()
    attrs = {"bag": "Hill Farm", "recipe": "Daily", "dose_g": 17.0, "reasons": ["liked", "community"]}
    out = _say(build, attrs, "ar")
    assert "أعجبتك، وصفة من المجتمع." in out


def test_it_shows_only_when_idle_with_nothing_picked_and_a_cup_to_offer():
    build = _build()
    section = _section(build)
    conditions = str(section["visibility"])
    assert CUP in conditions and "select.xbloom_studio_recipe" in conditions
    assert "sensor.xbloom_studio_brew_status" in conditions
    entities = {c.get("entity") for c in _cards(section)}
    assert {"button.xbloom_studio_use_todays_cup", "button.xbloom_studio_another_cup"} <= entities


def test_the_section_has_a_real_heading():
    build = _build()
    for lang in ("en", "ar"):
        section = _section(build, lang)
        assert section["cards"][0]["content"] == "## " + build.TEXT[lang]["h_todays_cup"]


def test_the_last_cup_of_a_bag_says_so_with_its_dose():
    build = _build()
    attrs = {"bag": "Hill Farm", "recipe": "Daily", "dose_g": 25.5, "reasons": ["past_best", "last_cup"]}
    assert _say(build, attrs) == (
        "Hill Farm · Daily · 25.5 g\n\n"
        "Past its best, the last cup of this bag.")
    assert "آخر كوب من هذا الكيس" in _say(build, attrs, "ar")


def test_the_rest_of_the_bag_button_sits_by_coffee_left_and_shows_only_when_available():
    build = _build()
    brew = build.brew_view(build.TEXT["en"])
    now = next(s for s in brew["sections"] if "sensor.xbloom_studio_coffee_left" in str(s))
    entities = [c.get("entity") for c in now["cards"]]
    left = entities.index("sensor.xbloom_studio_coffee_left")
    assert entities[left + 1] == "button.xbloom_studio_use_rest_of_bag"
    button = now["cards"][left + 1]
    assert any(v.get("entity") == "button.xbloom_studio_use_rest_of_bag" and v.get("state_not") == "unavailable"
               for v in button["visibility"])


def test_by_hand_sits_with_the_todays_cup_buttons():
    build = _build()
    entities = [c.get("entity") for c in _section(build)["cards"]]
    i = entities.index("button.xbloom_studio_another_cup")
    assert entities[i + 1] == "button.xbloom_studio_by_hand"
