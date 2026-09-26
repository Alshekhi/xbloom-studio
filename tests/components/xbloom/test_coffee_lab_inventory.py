"""The inventory rules — the part that can quietly corrupt purchase history."""
import pytest
from xbloom import spec

from custom_components.xbloom.coffee_lab.inventory import Deduct, Flag, Skip, decide_consumption
from custom_components.xbloom.coffee_lab.models import Bean

XPOD = spec.CUP_LABEL_TO_API["xPod"]
OMNI = spec.CUP_LABEL_TO_API["Omni dripper"]


def bag(**over) -> Bean:
    return Bean(**{
        "id": "bag-1", "name": "Kenya", "remaining_g": 180.0,
        "bag_size_g": 250.0, "status": "open", "tracked": True, **over,
    })


def test_a_confirmed_brew_subtracts_its_dose():
    d = decide_consumption(bean=bag(), grams=20)
    assert isinstance(d, Deduct) and d.new_remaining_g == 160


def test_a_duplicate_completion_does_not_subtract_twice():
    d = decide_consumption(bean=bag(), grams=20, already_processed=True)
    assert isinstance(d, Skip) and d.reason == "already_counted" and not d.record_brew


def test_an_xpod_brew_is_recorded_but_against_no_bag():
    d = decide_consumption(bean=bag(), grams=15, cup_type=XPOD)
    assert isinstance(d, Skip) and d.reason == "xpod"
    assert d.record_brew and d.bean_id is None


def test_xpod_is_read_from_spec_not_a_remembered_number():
    assert spec.CUP_API_TO_LABEL[XPOD].lower() == "xpod"
    assert isinstance(decide_consumption(bean=bag(), grams=15, cup_type=OMNI), Deduct)


def test_an_xpod_brew_is_skipped_even_with_no_bag():
    assert isinstance(decide_consumption(bean=None, grams=15, cup_type=XPOD), Skip)


def test_no_bag_is_flagged_never_guessed():
    d = decide_consumption(bean=None, grams=20)
    assert isinstance(d, Flag) and d.reason == "no_bag" and d.detail == {"grams": 20.0}


def test_inventory_is_never_driven_negative():
    d = decide_consumption(bean=bag(remaining_g=10.0), grams=20)
    assert isinstance(d, Flag) and d.reason == "more_than_left"
    assert d.detail == {"bag": "Kenya", "remaining_g": 10.0, "grams": 20.0}


def test_exactly_emptying_a_bag_is_allowed():
    d = decide_consumption(bean=bag(remaining_g=20.0), grams=20)
    assert isinstance(d, Deduct) and d.new_remaining_g == 0 and d.finish


def test_a_bag_with_too_little_left_to_brew_is_finished():
    d = decide_consumption(bean=bag(remaining_g=23.0), grams=20)
    assert isinstance(d, Deduct) and d.finish, "3 g left is a finished bag"


def test_first_use_of_an_unopened_bag_opens_it():
    d = decide_consumption(bean=bag(status="unopened"), grams=20)
    assert isinstance(d, Deduct) and d.open_bag


def test_an_open_bag_is_not_reopened():
    d = decide_consumption(bean=bag(status="open"), grams=20)
    assert isinstance(d, Deduct) and not d.open_bag


@pytest.mark.parametrize("status", ["finished", "archived"])
def test_brewing_from_a_closed_bag_is_flagged(status):
    d = decide_consumption(bean=bag(status=status, remaining_g=0.0), grams=20)
    assert isinstance(d, Flag) and d.reason == "bag_closed"


@pytest.mark.parametrize("grams", [0, None, "x"])
def test_no_dose_does_nothing(grams):
    d = decide_consumption(bean=bag(), grams=grams)
    assert isinstance(d, Skip) and d.reason == "no_dose"


def test_repeated_subtraction_does_not_trail_float_digits():
    remaining = 250.0
    for _ in range(3):
        d = decide_consumption(bean=bag(remaining_g=remaining), grams=20.3)
        remaining = d.new_remaining_g
    assert remaining == 189.1


# A bag opened before tracking began has no trustworthy starting weight. It is
# open and usable; it simply is not counted down. That is a state, not a fault.


def test_an_untracked_bag_records_the_brew_but_subtracts_nothing():
    d = decide_consumption(bean=bag(tracked=False, remaining_g=None), grams=20)
    assert isinstance(d, Skip) and d.reason == "untracked"
    assert d.record_brew and d.bean_id == "bag-1"


def test_untracked_wins_even_if_a_stale_amount_lingers():
    d = decide_consumption(bean=bag(tracked=False, remaining_g=250.0), grams=20)
    assert isinstance(d, Skip) and d.record_brew


def test_tracked_with_no_amount_is_a_real_inconsistency():
    d = decide_consumption(bean=bag(remaining_g=None), grams=20)
    assert isinstance(d, Flag) and d.reason == "tracked_without_amount"


def test_a_new_bag_is_untracked_until_someone_says_otherwise():
    # Absent means untracked: a balance nobody has established must not be
    # counted down from a default.
    assert Bean(id="b", name="n", status="unopened").tracked is False
