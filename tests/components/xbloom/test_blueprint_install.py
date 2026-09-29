"""Which bundled blueprints are installed, updated or left alone.

Each version of the integration carries its blueprints and installs them. A
blueprint someone edited by hand must never be overwritten; one this
integration wrote and nobody touched follows the integration's updates.
"""

import pytest

from custom_components.xbloom.blueprint_install import bundled_names, decide, issue_id

OLD, NEW, EDITED = "old", "new", "edited"


@pytest.mark.parametrize(
    "installed, written, bundled, action",
    [
        (None, None, NEW, "install"),       # first start
        (None, OLD, NEW, "install"),        # deleted since: put back
        (NEW, OLD, NEW, "current"),         # already the bundled one
        (NEW, None, NEW, "current"),        # the same one, put there by hand
        (OLD, OLD, NEW, "update"),          # ours and untouched
        (EDITED, NEW, NEW, "edited"),       # edited, nothing newer: no notice
        (EDITED, OLD, NEW, "outdated"),     # edited, and a newer one came
        (EDITED, None, NEW, "outdated"),    # a copy we never wrote
        ("unreadable", OLD, NEW, "outdated"),
    ],
)
def test_what_is_done_with_each_blueprint(installed, written, bundled, action):
    assert decide(installed, written, bundled) == action


def test_an_edited_blueprint_is_never_overwritten():
    for written in (None, OLD, NEW):
        assert decide(EDITED, written, NEW) not in ("install", "update")


def test_the_three_announcement_blueprints_are_bundled():
    assert bundled_names() == [
        "brew_announce.yaml", "live_control_announce.yaml", "machine_fault_announce.yaml",
    ]


def test_each_blueprint_has_its_own_notice():
    assert issue_id("xbloom/brew_announce.yaml") != issue_id("xbloom/live_control_announce.yaml")
