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
