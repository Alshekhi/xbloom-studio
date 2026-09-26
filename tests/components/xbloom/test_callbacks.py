"""Brew callbacks: signed to the spec, one per brew, facts only."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.xbloom.callbacks import (
    Callbacks, Target, headers_for, signature, target_problem,
)

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


def test_the_signature_matches_the_standard_webhooks_example():
    # The spec's own example, so any receiver's library verifies ours.
    assert signature(
        SECRET, "msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, b'{"test": 2432232314}'
    ) == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_headers_carry_id_timestamp_and_signature():
    target = Target("receiver", "https://example.invalid/hook", SECRET)
    headers = headers_for(target, "msg_1", b"{}", now=100)
    assert headers["webhook-id"] == "msg_1" and headers["webhook-timestamp"] == "100"
    assert headers["webhook-signature"] == signature(SECRET, "msg_1", 100, b"{}")


@pytest.mark.parametrize("name, url, secret, bad", [
    ("receiver", "https://x.invalid", SECRET, set()),
    ("Receiver!", "https://x.invalid", SECRET, {"name"}),
    ("receiver", "ftp://x.invalid", SECRET, {"url"}),
    ("receiver", "https://x.invalid", "whsec_c2hvcnQ=", {"secret"}),
    ("receiver", "https://x.invalid", "not-a-secret", {"secret"}),
])
def test_a_target_is_checked_before_it_is_saved(name, url, secret, bad):
    assert set(target_problem(name, url, secret)) == bad


def _callbacks():
    return Callbacks(MagicMock(), {"receiver": Target("receiver", "https://x.invalid", SECRET)})


def _event(name, **data):
    return SimpleNamespace(event_type=name, data=data)


def _sent(callbacks):
    out = []
    while not callbacks._queue.empty():
        out.append(callbacks._queue.get_nowait())
    return out


def test_a_brew_refused_before_it_ran_still_reaches_its_caller():
    cb = _callbacks()
    cb.arm("r1", "receiver", {"device": "phone"}, progress=False)
    cb.on_event(_event("xbloom_brew_failed", run_id="r1", reason="no_water", recipe_name="K"))
    [message] = _sent(cb)
    assert message.target == "receiver"
    assert message.payload["type"] == "xbloom.brew.failed"
    assert message.payload["context"] == {"device": "phone"}
    data = message.payload["data"]
    assert (data["event"], data["final"], data["reason"], data["recipe"]) == ("failed", True, "no_water", "K")
    assert "message" not in data, "facts only; the receiver words them"


def test_another_brew_s_events_are_not_sent():
    cb = _callbacks()
    cb.arm("mine", "receiver", None, progress=True)
    cb.on_event(_event("xbloom_brew_completed", run_id="someone-else", outcome="confirmed"))
    assert _sent(cb) == []


def test_progress_only_when_asked_but_faults_always():
    for progress in (False, True):
        cb = _callbacks()
        cb.arm("r1", "receiver", None, progress=progress)
        cb.on_event(_event("xbloom_brew_started", run_id="r1", recipe_name="K", total_pours=3))
        cb.on_brew_status("idle", "grinding")
        cb.on_brew_event({"event_type": "pour_started", "pour_index": 0})
        cb.on_machine_status("ok", "no_water")
        cb.on_machine_status("no_water", "ok")
        events = [m.payload["data"]["event"] for m in _sent(cb)]
        expected = ["fault", "fault_cleared"]
        assert events == (["grinding", "pour", *expected] if progress else expected)


def test_one_ending_and_then_silence():
    cb = _callbacks()
    cb.arm("r1", "receiver", None, progress=True)
    cb.on_event(_event("xbloom_brew_started", run_id="r1", recipe_name="K"))
    cb.on_event(_event("xbloom_brew_stopped", run_id="r1", by="machine", context="x"))
    cb.on_event(_event("xbloom_brew_completed", run_id="r1", outcome="presumed"))
    cb.on_machine_status("ok", "no_water")
    [message] = _sent(cb)
    data = message.payload["data"]
    assert (data["event"], data["by"]) == ("stopped", "machine")
    assert "context" not in data, "the caller's context goes once, beside data"


def test_a_pour_is_numbered_from_one_of_the_total():
    cb = _callbacks()
    cb.arm("r1", "receiver", None, progress=True)
    cb.on_event(_event("xbloom_brew_started", run_id="r1", recipe_name="K", total_pours=3))
    cb.on_brew_event({"event_type": "pour_started", "pour_index": 1})
    [message] = _sent(cb)
    assert (message.payload["data"]["pour"], message.payload["data"]["pours"]) == (2, 3)


async def test_the_service_refuses_an_unknown_target_before_anything_fires():
    from homeassistant.exceptions import HomeAssistantError

    from .test_brew_completion_contract import _Entry, _make_hass, _setup_and_get_handlers

    hass, entry = _make_hass(), _Entry()
    handlers = await _setup_and_get_handlers(hass, entry)
    with pytest.raises(HomeAssistantError) as caught:
        await handlers["start_brew"](MagicMock(data={"notify_target": "nobody"}))
    assert caught.value.translation_key == "callback_targets_none"
    assert not [c for c in hass.bus.async_fire.call_args_list if c.args and "brew" in c.args[0]]

