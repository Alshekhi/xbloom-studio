"""Every xBloom blueprint speaks through xbloom.announce, so none cuts another off."""
from pathlib import Path

import pytest
import yaml

BLUEPRINTS = Path(__file__).parents[3] / "custom_components" / "xbloom" / "blueprints"
SPEAKING = ("brew_announce.yaml", "live_control_announce.yaml", "machine_fault_announce.yaml",
            "story_announce.yaml")


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: f"!input {loader.construct_scalar(node)}")


def _actions(node):
    if isinstance(node, dict):
        if "action" in node and isinstance(node["action"], str):
            yield node
        for value in node.values():
            yield from _actions(value)
    elif isinstance(node, list):
        for value in node:
            yield from _actions(value)


def _load(name):
    return yaml.load((BLUEPRINTS / name).read_text(encoding="utf-8"), Loader=_Loader)


@pytest.mark.parametrize("name", sorted(p.name for p in BLUEPRINTS.glob("*.yaml")))
def test_no_blueprint_speaks_past_the_queue(name):
    for action in _actions(_load(name)["action"]):
        assert action["action"] not in ("notify.alexa_media", "tts.speak"), (name, action)


@pytest.mark.parametrize("name", SPEAKING)
def test_each_speaking_blueprint_announces_through_the_queue(name):
    announces = [a for a in _actions(_load(name)["action"]) if a["action"] == "xbloom.announce"]
    assert announces, name
    for a in announces:
        assert {"message", "method", "targets", "tts_engine", "notify_service", "kind"} <= set(a["data"])


def test_story_parts_are_the_story_kind_and_the_rest_are_announcements():
    for name in SPEAKING:
        kinds = {a["data"]["kind"] for a in _actions(_load(name)["action"]) if a["action"] == "xbloom.announce"}
        assert kinds == ({"story"} if name == "story_announce.yaml" else {"announcement"}), name


def test_a_spoken_rating_question_waits_for_the_announcements_first():
    actions = [a["action"] for a in _actions(_load("rating_ask.yaml")["action"])]
    assert actions.index("xbloom.wait_for_announcements") < actions.index("assist_satellite.start_conversation")


@pytest.mark.parametrize("name", SPEAKING)
def test_a_delivery_field_for_another_method_is_sent_empty(name):
    import jinja2
    env = jinja2.Environment()
    for a in (a for a in _actions(_load(name)["action"]) if a["action"] == "xbloom.announce"):
        # A call that always uses one method (the phone for what to notice)
        # is checked for that method alone.
        fixed = a["data"]["method"]
        methods = (fixed,) if "{{" not in str(fixed) else ("alexa", "tts", "notify")
        for field, own in (("notify_service", "notify"), ("tts_engine", "tts")):
            template = a["data"][field]
            for method in methods:
                rendered = env.from_string(template).render(
                    method=method, notify_service="mobile_app_typed_without_prefix", tts_engine="tts.piper",
                    focus_notify="notify.mobile_app_test")
                assert (rendered != "") == (method == own), (name, field, method, rendered)
