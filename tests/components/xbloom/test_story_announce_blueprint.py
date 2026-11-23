"""What the story announcement blueprint speaks, rendered as Home Assistant renders it."""
import pytest

from .blueprint_render import load, render

STORY = "story_announce.yaml"
PARTS = "select.xbloom_studio_spoken_story_parts"


def _part(kind, story, teaser=None):
    return {"platform": "state", "to_state": {"state": "Heading", "attributes": {
        "kind": kind, "story": story, "teaser": teaser, "now": "Pour 2: 76.5 ml at 92 °C."}}}


def _said(kind, story, teaser=None, parts="bag_and_teaser"):
    return render(STORY, _part(kind, story, teaser), states={PARTS: parts})["message"]


@pytest.mark.parametrize("kind, story, teaser, expected", [
    ("bag", "Smell the fruit first.", None, "Smell the fruit first."),
    ("big_story", "The goats danced.", None, ""),
    ("science", "Water is most of the cup.", None, ""),
    ("you", "Check the sweetness. Next cup: something about roasting.",
     "Next cup: something about roasting.", "Next cup: something about roasting."),
])
def test_bag_and_teaser_speaks_the_bag_part_and_the_teaser_alone(kind, story, teaser, expected):
    assert _said(kind, story, teaser) == expected


@pytest.mark.parametrize("kind, story, teaser, expected", [
    ("bag", "Smell the fruit first.", None, "Smell the fruit first."),
    ("big_story", "The goats danced.", None, "The goats danced."),
    ("science", "Water is most of the cup.", None, "Water is most of the cup."),
    ("you", "Check the sweetness. Next cup: something about roasting.",
     "Next cup: something about roasting.", "Check the sweetness. Next cup: something about roasting."),
])
def test_every_part_speaks_each_story_part_whole(kind, story, teaser, expected):
    assert _said(kind, story, teaser, parts="every_part") == expected


def test_a_closing_line_without_a_teaser_says_nothing_under_bag_and_teaser():
    assert _said("you", "Check the sweetness.") == ""


def test_pour_lines_are_never_spoken():
    assert "Pour 2" not in _said("bag", "Smell it.", parts="every_part")


@pytest.mark.parametrize("story, expected", [
    ("Water around 90 to 96 °C is usual.", "Water around 90 to 96 degrees is usual."),
    ("الماء بين 90 و96 °م هو المدى المعتاد.", "الماء بين 90 و96 درجة هو المدى المعتاد."),
    ("Sweet — then bright – then long.", "Sweet, then bright, then long."),
])
def test_what_a_speaker_would_read_out_is_said_in_words(story, expected):
    assert _said("bag", story) == expected


def test_its_input_keys_match_the_other_blueprints_delivery():
    brew = load("brew_announce.yaml")["blueprint"]["input"]["delivery"]["input"]
    story = load(STORY)["blueprint"]["input"]["delivery"]["input"]
    assert {"delivery_method", "speakers", "tts_engine", "notify_service"} <= set(story)
    for key in ("delivery_method", "tts_engine", "notify_service"):
        assert story[key]["selector"] == brew[key]["selector"]
