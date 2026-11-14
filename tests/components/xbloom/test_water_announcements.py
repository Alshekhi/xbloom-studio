"""The blueprints speak the water warnings.

The sentences themselves are rendered by Home Assistant's template engine,
which these tests do not run; they check that every water warning reaches a
message, with its amount, and that low water the cup will finish on stays
quiet.
"""
from pathlib import Path

import yaml

BLUEPRINTS = Path(__file__).parents[3] / "custom_components" / "xbloom" / "blueprints"


class _Loader(yaml.SafeLoader):
    """Reads `!input name` as a plain string."""


_Loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


def _load(name: str) -> dict:
    return yaml.load((BLUEPRINTS / name).read_text(encoding="utf-8"), Loader=_Loader)


def test_the_fault_blueprint_speaks_each_water_event_with_its_amount():
    bp = _load("machine_fault_announce.yaml")
    message = bp["variables"]["message"]
    for event_type in ("water_low", "water_paused", "water_refilled"):
        assert f"'{event_type}'" in message
    amount = bp["variables"]["amount"]
    assert "water_short_ml" in amount and "water_needed_ml" in amount
    assert "amount" in message
    # A tank the cup will finish on is not announced.
    assert "enough_to_finish" in message


def test_the_fault_blueprint_still_speaks_the_bare_fault():
    message = _load("machine_fault_announce.yaml")["variables"]["message"]
    assert "out of water" in message


def test_the_fault_blueprint_lets_an_empty_message_drop_the_announcement():
    condition = _load("machine_fault_announce.yaml")["condition"][0]["value_template"]
    assert "message" in condition


def test_the_brew_blueprint_says_what_is_left_after_the_coffee():
    variables = _load("brew_announce.yaml")["variables"]
    assert "water_left_ml" in variables["tank_line"] and "tank_low" in variables["tank_line"]
    finish = variables["message"][variables["message"].index("trigger.id == 'done_recipe'"):]
    assert finish.count("tank_line") >= 2


def test_the_brew_blueprint_says_how_much_water_a_refused_recipe_needs():
    assert "water_needed_ml" in _load("brew_announce.yaml")["variables"]["failure"]


def test_a_pause_for_water_is_left_to_the_water_announcement():
    message = _load("brew_announce.yaml")["variables"]["message"]
    assert "reason" in message and "'water'" in message


def test_spoken_water_text_has_no_dashes():
    for name in ("machine_fault_announce.yaml", "brew_announce.yaml"):
        text = (BLUEPRINTS / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "millilitres" in line or "مليلتر" in line:
                assert "—" not in line and " - " not in line, line


def test_the_knob_is_named_as_elsewhere_in_arabic():
    text = (BLUEPRINTS / "machine_fault_announce.yaml").read_text(encoding="utf-8")
    assert "المقبض" not in text
    assert text.count("اضغط المفتاح الأيمن") == 2


def test_a_pause_while_the_tank_is_low_is_left_to_the_water_announcement():
    """The pause frame can arrive before the water screen says why."""
    bp = _load("brew_announce.yaml")
    assert bp["blueprint"]["input"]["entities"]["input"]["machine_status_entity"]["default"] \
        == "sensor.xbloom_studio_machine_status"
    message = bp["variables"]["message"]
    paused = message[message.index("trigger.id == 'paused'"):message.index("trigger.id == 'resumed'")]
    assert "no_water" in paused


def test_every_finish_comes_from_the_brew_event():
    """One source for the finish, so the water line is part of it whatever
    the announcement says: Brew Status turns `done` before the tank is known."""
    bp = _load("brew_announce.yaml")
    ids = [t.get("id") for t in bp["trigger"]]
    assert "done_simple" not in ids and "tank" not in ids
    message = bp["variables"]["message"]
    finish = message[message.index("trigger.id == 'done_recipe'"):]
    assert "Your coffee is ready" in finish and "قهوتك جاهزة" in finish
