"""A brew is announced as starting once, and as pouring only after grinding.

"Started preparing" is said when the machine accepts the brew and "Pouring
started" when Brew Status turns `brewing`. With the grinder on they are a
grind apart; a recipe with the grinder off goes straight to pouring, and the
two arrived together. Pouring is news only after grinding.
"""
from pathlib import Path

import yaml

BLUEPRINT = (
    Path(__file__).parents[3] / "custom_components" / "xbloom" / "blueprints" / "brew_announce.yaml"
)


class _Loader(yaml.SafeLoader):
    """Reads `!input name` as a plain string, the way a blueprint lists it."""


_Loader.add_constructor("!input", lambda loader, node: loader.construct_scalar(node))


def _trigger(trigger_id: str) -> dict:
    blueprint = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=_Loader)
    return next(t for t in blueprint["trigger"] if t.get("id") == trigger_id)


def test_pouring_is_announced_only_after_grinding() -> None:
    pouring = _trigger("pouring")
    assert pouring["to"] == "brewing"
    assert pouring["from"] == "grinding"
    assert "not_from" not in pouring
