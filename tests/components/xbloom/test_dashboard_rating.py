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
