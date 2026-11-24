"""What the announcement blueprints say, rendered as Home Assistant renders them.

Each case is an event the integration fires and the exact sentence spoken for
it, in both languages. The Arabic counted noun follows its number, so the
amounts are checked at each form: 100 مليلتر, 110 مليلترات, 120 مليلترًا.
"""
import pytest

from .blueprint_render import bus_event, event, render

BREW, FAULT = "brew_announce.yaml", "machine_fault_announce.yaml"
NAMED = {"announce_recipe": True, "announce_duration": True}


@pytest.mark.parametrize("lang, expected", [
    ("ar", "تعذر تحضير Water test، الماء لا يكفي، تحتاج الوصفة إلى 500 مليلتر"),
    ("en", "Could not brew Water test: not enough water, the recipe needs 500 millilitres"),
])
def test_a_start_refused_for_water_says_what_the_recipe_needs(lang, expected):
    said = render(BREW, bus_event("failed", reason="no_water", recipe_name="Water test",
                                  water_needed_ml=500), inputs={"language": lang, **NAMED})
    assert said["message"] == expected


@pytest.mark.parametrize("lang, expected", [
    ("ar", "تعذر تحضير قهوتك، الماء لا يكفي"),
    ("en", "Could not brew your coffee: not enough water"),
])
def test_a_refusal_with_no_recipe_or_amount_still_reads_whole(lang, expected):
    # A button start on a recipe Home Assistant did not send: no name, no amount.
    said = render(BREW, bus_event("failed", reason="no_water", recipe_name=None),
                  inputs={"language": lang, **NAMED})
    assert said["message"] == expected


@pytest.mark.parametrize("lang, expected", [
    ("ar", "انتهى تحضير Kenya، واستغرق دقيقتين و52 ثانية. "
           "بقي نحو 140 مليلترًا من الماء، أضف ماءً قبل الكوب القادم"),
    ("en", "Finished preparing Kenya. It took 2 minutes and 52 seconds. "
           "About 140 millilitres of water left. Add water before your next cup."),
])
def test_the_finish_carries_the_water_left_in_one_sentence(lang, expected):
    said = render(BREW, event("brew_done", recipe_name="Kenya", duration_s=172.3,
                              tank_low=True, water_left_ml=143),
                  inputs={"language": lang, **NAMED})
    assert said["message"] == expected


@pytest.mark.parametrize("lang, expected", [
    ("ar", "قهوتك جاهزة. الماء قليل، أضف ماءً قبل الكوب القادم"),
    ("en", "Your coffee is ready. The water is low. Add water before your next cup."),
])
def test_the_plain_finish_says_the_water_is_low_without_an_amount(lang, expected):
    said = render(BREW, event("brew_done", duration_s=30, tank_low=True),
                  inputs={"language": lang})
    assert said["message"] == expected


@pytest.mark.parametrize("left, form", [(100, "100 مليلتر"), (110, "110 مليلترات"),
                                        (120, "120 مليلترًا")])
def test_the_counted_noun_follows_the_amount(left, form):
    said = render(BREW, event("brew_done", tank_low=True, water_left_ml=left),
                  inputs={"language": "ar"})
    assert f"بقي نحو {form} من الماء" in said["message"]


@pytest.mark.parametrize("event_type, data, ar, en", [
    ("water_low", {"water_short_ml": 47, "enough_to_finish": False},
     "الماء لا يكفي لإكمال الوصفة، ينقصه نحو 50 مليلترًا. أضف ماءً الآن",
     "Not enough water to finish. About 50 millilitres short. Add water now."),
    ("water_paused", {"water_needed_ml": 35},
     "توقف التحضير لنفاد الماء ويحتاج إلى نحو 40 مليلترًا. أضف ماءً ثم اضغط المفتاح الأيمن للمتابعة",
     "Paused for water. It needs about 40 millilitres more. Add water, then press the right knob to continue."),
    ("water_paused", {},
     "توقف التحضير لنفاد الماء. أضف ماءً ثم اضغط المفتاح الأيمن للمتابعة",
     "Paused for water. Add water, then press the right knob to continue."),
    ("water_refilled", {},
     "اضغط المفتاح الأيمن للمتابعة",
     "Press the right knob to continue."),
])
def test_the_water_warnings(event_type, data, ar, en):
    for lang, expected in (("ar", ar), ("en", en)):
        said = render(FAULT, event(event_type, **data), inputs={"language": lang})
        assert said["message"] == expected, lang


def test_low_water_the_cup_will_finish_on_says_nothing():
    said = render(FAULT, event("water_low", water_short_ml=0, enough_to_finish=True),
                  inputs={"language": "ar"})
    assert said["message"] == ""


# ── What to notice, said with the coffee being ready ─────────────────────────

FOCUS = "The grind is 47 instead of 50: is it less sour?"


def test_what_to_notice_is_said_with_the_coffee_being_ready():
    said = render(BREW, event("brew_done", recipe_name="Kenya", focus=FOCUS),
                  inputs={"language": "en"})
    assert said["message"] == f"Your coffee is ready. {FOCUS}"
    assert said["home_message"] == f"Your coffee is ready. {FOCUS}"


def test_a_cup_with_nothing_to_notice_says_only_that_it_is_ready():
    said = render(BREW, event("brew_done", recipe_name="Kenya"), inputs={"language": "en"})
    assert said["message"] == "Your coffee is ready"


def _phone_gets_it(data, **inputs):
    import jinja2
    from .blueprint_render import load
    context = render(BREW, event("brew_done", recipe_name="Kenya", **data),
                     inputs={"language": "en", **inputs})
    [step] = [a for a in load(BREW)["action"] if "if" in a]
    template = step["if"][0]["value_template"]
    return jinja2.Environment().from_string(template).render(context).strip() == "True"


def test_the_phone_gets_what_to_notice_only_when_there_is_something_and_no_caller():
    phone = {"focus_notify_service": "notify.mobile_app_test"}
    assert _phone_gets_it({"focus": FOCUS}, **phone)
    assert not _phone_gets_it({}, **phone)
    # A caller told of the brew's end passes it on itself.
    assert not _phone_gets_it({"focus": FOCUS, "notify_target": "test_bot"}, **phone)
    assert not _phone_gets_it({"focus": FOCUS})
    # Never twice to the phone the announcements already go to.
    assert not _phone_gets_it({"focus": FOCUS}, delivery_method="notify",
                              notify_service="notify.mobile_app_test", **phone)


def test_the_rating_question_carries_what_was_to_be_noticed():
    brews = [{"brew_id": "b1", "recipe": "Test Hot", "bag": "Kenya", "changes": [],
              "focus": "The grind is 47 instead of 50: is it less sour? <b>"},
             {"brew_id": "b2", "recipe": "Test Cold", "bag": "Kenya", "changes": [], "focus": None}]
    coffees = render("rating_ask.yaml", bus_event("due", brews=brews),
                     inputs={"language": "en"})["coffees"]
    assert coffees[0]["focus"] == "The grind is 47 instead of 50: is it less sour?  b"
    assert coffees[1]["focus"] == ""
