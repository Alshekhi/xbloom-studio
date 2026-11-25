"""The dashboard's rating cards: shown when there is something to answer."""
from .test_water_wording import _build, _cards

def _hides_on_unknown(card: dict, entity: str) -> bool:
    return any(
        c.get("entity") == entity and c.get("state_not") == "unknown"
        for c in card.get("visibility") or []
    )


def test_a_select_waiting_for_a_pick_is_not_hidden_for_having_none():
    # With nothing picked a select reads `unknown`: that is when it is asked.
    build = _build()
    for lang in ("en", "ar"):
        for entity in ("select.xbloom_studio_what_was_wrong",):
            shown_by = [c for c in _cards(build.dashboard(lang))
                        if any(v.get("entity") == entity for v in c.get("visibility") or [])]
            assert shown_by, (lang, entity)
            assert not any(_hides_on_unknown(c, entity) for c in shown_by), (lang, entity)


def test_a_rated_version_is_told_by_grind_and_ratio_only():
    build = _build()
    words = build.version_words(build.TEXT["en"], "v")
    assert "v.grind" in words and "v.ratio" in words and "dose" not in words


def test_the_verdicts_say_what_happens_next():
    build = _build()
    assert [build.TEXT["en"][f"verdict_{v}"] for v in ("again", "fine", "not_again")] == [
        "Keep it like this", "Close, needs a tweak", "Doesn't suit this coffee"]


def test_the_question_shows_what_was_to_be_noticed_when_there_is_something():
    build = _build()
    card = build.rating_card(build.TEXT["en"])
    assert "state_attr('sensor.xbloom_studio_brew_to_rate', 'focus')" in card
    assert "{% if f %}" in card


# ── Finish this bag? ─────────────────────────────────────────────────────────

ASKED = "sensor.xbloom_studio_bag_to_finish"


def _finish_section(build, lang="en"):
    brew = build.brew_view(build.TEXT[lang])
    return next(s for s in brew["sections"] if "button.xbloom_studio_finish_bag" in str(s))


def test_the_finish_question_sits_before_buy_again_and_shows_only_when_asked():
    build = _build()
    brew = build.brew_view(build.TEXT["en"])
    order = [i for i, s in enumerate(brew["sections"])
             for key in ("button.xbloom_studio_finish_bag", "select.xbloom_studio_buy_again") if key in str(s)]
    assert order == sorted(order) and len(order) == 2
    section = _finish_section(build)
    shown = section["visibility"]
    assert any(v.get("entity") == ASKED and v.get("state_not") == "unknown" for v in shown)
    assert any(v.get("entity") == "sensor.xbloom_studio_brew_status" for v in shown)
    entities = {c.get("entity") for c in _cards(section)}
    assert {"button.xbloom_studio_finish_bag", "button.xbloom_studio_keep_bag"} <= entities


def test_the_finish_question_names_the_bag_and_the_grams_in_both_languages():
    from .test_dashboard_stock import _render
    build = _build()
    for lang, words in (("en", "Kenya has 8.5 g left."), ("ar", "بقي في Kenya 8.5 غ.")):
        line = next(c for c in _finish_section(build, lang)["cards"] if c.get("type") == "markdown" and ASKED in c.get("content", ""))
        out = _render(line["content"], {ASKED: "Kenya"}, {ASKED: {"remaining_g": 8.5}})
        assert out.replace("⁨", "").replace("⁩", "").replace("**", "") == words, lang
