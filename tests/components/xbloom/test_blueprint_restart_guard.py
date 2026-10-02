"""A restart does not replay the last brew or fault as an announcement.

The entities the blueprints watch are unavailable only while Home Assistant
starts or the integration reloads. They then come back holding their last
value — the brew status restores, and the event entity restores its last
event — so a state trigger without a `from:` saw `unavailable → done` and
announced "Your coffee is ready" with nobody brewing, or a dry tank from before
the restart.

Every such state trigger therefore skips a change out of `unavailable`. A change
out of `unknown` stays allowed: that is a brand-new entity's first real value.
"""
from pathlib import Path

import pytest
import yaml

BLUEPRINTS = (
    Path(__file__).parents[3] / "custom_components" / "xbloom" / "blueprints"
)


class _Loader(yaml.SafeLoader):
    """Reads `!input name` as a plain string, the way a blueprint lists it."""


_Loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


def _state_triggers(path: Path) -> list[dict]:
    blueprint = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    triggers = blueprint.get("trigger") or blueprint.get("triggers") or []
    return [t for t in triggers if (t.get("platform") or t.get("trigger")) == "state"]


@pytest.mark.parametrize("path", sorted(BLUEPRINTS.glob("*.yaml")), ids=lambda p: p.name)
def test_state_triggers_skip_the_restart(path: Path) -> None:
    for trigger in _state_triggers(path):
        if "from" in trigger:
            # A trigger that names its `from` state already excludes `unavailable`.
            assert trigger["from"] != "unavailable", trigger
            continue
        not_from = trigger.get("not_from")
        not_from = [not_from] if isinstance(not_from, str) else (not_from or [])
        assert "unavailable" in not_from, (
            f"{path.name}: trigger {trigger.get('id', trigger['entity_id'])} "
            "fires on the restart's unavailable → last-value change"
        )
        assert "unknown" not in not_from, (
            f"{path.name}: trigger {trigger.get('id', trigger['entity_id'])} "
            "would swallow a new entity's first real value"
        )


def test_the_brew_blueprint_is_covered() -> None:
    """Guard the guard: the brew blueprint really has state triggers to check."""
    assert len(_state_triggers(BLUEPRINTS / "brew_announce.yaml")) >= 5
