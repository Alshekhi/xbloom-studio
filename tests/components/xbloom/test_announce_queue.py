"""One announcement at a time, across every xBloom blueprint."""
import asyncio
from unittest.mock import AsyncMock

from custom_components.xbloom.announce import STORY_STALE_S, AnnouncementQueue, speak_seconds


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _queue():
    clock = _Clock()
    spoken = []
    gates = []

    async def call(domain, service, data, **kw):
        spoken.append((domain, service, data.get("message")))

    async def sleep(seconds):
        clock.now += seconds
        gate = asyncio.Event()
        gates.append(gate)
        await gate.wait()

    queue = AnnouncementQueue(AsyncMock(side_effect=call), sleep=sleep, clock=clock)
    return queue, spoken, gates, clock


def _say(text, kind="announcement", method="alexa"):
    return {"message": text, "method": method, "targets": ["media_player.kitchen"],
            "tts_engine": "", "notify_service": "notify.phone", "alexa_type": "tts", "kind": kind}


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_the_next_announcement_waits_until_the_last_has_been_spoken():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("Pour 2 of 5"))
    queue.add(_say("Pour 3 of 5"))
    await _settle()
    assert [m for _, _, m in spoken] == ["Pour 2 of 5"]
    gates[0].set()
    await _settle()
    assert [m for _, _, m in spoken] == ["Pour 2 of 5", "Pour 3 of 5"]
    queue.stop()


async def test_an_announcement_goes_ahead_of_a_waiting_story_part():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("Pour 2 of 5"))
    await _settle()
    queue.add(_say("A story.", kind="story"))
    queue.add(_say("Your coffee is ready"))
    gates[0].set()
    await _settle()
    assert spoken[-1][2] == "Your coffee is ready"
    queue.stop()


async def test_only_the_newest_story_part_waits():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("Pour 2 of 5"))
    await _settle()
    queue.add(_say("Old part.", kind="story"))
    queue.add(_say("New part.", kind="story"))
    gates[0].set()
    await _settle()
    assert [m for _, _, m in spoken] == ["Pour 2 of 5", "New part."]
    queue.stop()


async def test_a_story_part_whose_moment_passed_is_dropped():
    queue, spoken, gates, clock = _queue()
    queue.add(_say("A long announcement " * 30))
    await _settle()
    queue.add(_say("Late part.", kind="story"))
    clock.now += STORY_STALE_S + 1
    gates[0].set()
    await _settle()
    assert "Late part." not in [m for _, _, m in spoken]
    queue.stop()


async def test_a_notification_does_not_hold_the_queue():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("To the phone", method="notify"))
    queue.add(_say("Pour 2 of 5"))
    await _settle()
    assert [m for _, _, m in spoken] == ["To the phone", "Pour 2 of 5"]
    assert spoken[0][:2] == ("notify", "phone")
    queue.stop()


async def test_each_method_reaches_its_own_action():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("A", method="alexa"))
    await _settle()
    gates[0].set()
    queue.add({**_say("B", method="tts"), "tts_engine": "tts.piper"})
    await _settle()
    assert spoken[0][:2] == ("notify", "alexa_media") and spoken[1][:2] == ("tts", "speak")
    queue.stop()


async def test_a_failed_announcement_does_not_stop_the_ones_after_it():
    calls = []

    async def call(domain, service, data, **kw):
        calls.append(data.get("message"))
        if data.get("message") == "bad":
            raise RuntimeError("speaker gone")

    queue = AnnouncementQueue(AsyncMock(side_effect=call), sleep=AsyncMock(), clock=lambda: 0.0)
    queue.add(_say("bad"))
    queue.add(_say("good"))
    await _settle()
    assert calls == ["bad", "good"]
    queue.stop()


async def test_waiting_for_quiet_ends_once_everything_has_been_spoken():
    queue, spoken, gates, _ = _queue()
    queue.add(_say("Pour 2 of 5"))
    await _settle()
    waiter = asyncio.ensure_future(queue.async_wait_quiet(timeout=60))
    await _settle()
    assert not waiter.done()
    gates[0].set()
    await _settle()
    assert waiter.done()
    queue.stop()


def test_speaking_time_grows_with_the_text_and_has_a_floor():
    assert speak_seconds("Hi") == speak_seconds("Hello")
    assert speak_seconds("word " * 60) > speak_seconds("word " * 10) > speak_seconds("Hi")


async def test_only_a_notify_service_is_ever_called_for_a_notification():
    queue, spoken, gates, _ = _queue()
    queue.add({**_say("x", method="notify"), "notify_service": "lock.unlock"})
    queue.add({**_say("y", method="notify"), "notify_service": "notify.phone"})
    await _settle()
    assert [s[:2] for s in spoken] == [("notify", "phone")]
    queue.stop()


async def test_the_callers_context_goes_with_the_message():
    calls = []

    async def call(domain, service, data, **kw):
        calls.append(kw.get("context"))

    queue = AnnouncementQueue(AsyncMock(side_effect=call), sleep=AsyncMock(), clock=lambda: 0.0)
    marker = object()
    queue.add({**_say("x"), "context": marker})
    await _settle()
    assert calls == [marker]
    queue.stop()


async def test_a_script_is_started_with_what_to_say_and_still_waits_its_turn():
    calls = []

    async def call(domain, service, data, **kw):
        calls.append((domain, service, data))

    gates = []

    async def sleep(seconds):
        gate = asyncio.Event()
        gates.append(gate)
        await gate.wait()

    queue = AnnouncementQueue(AsyncMock(side_effect=call), sleep=sleep, clock=_Clock())
    queue.add({**_say("The coffee is ready"), "method": "script", "script": "script.speak",
               "language": "en", "problem": True})
    queue.add(_say("Pour 2 of 5"))
    await _settle()
    assert calls == [("script", "turn_on", {"entity_id": "script.speak", "variables": {
        "message": "The coffee is ready", "targets": ["media_player.kitchen"], "language": "en",
        "alexa_type": "tts", "kind": "announcement", "problem": True}})]
    gates[0].set()
    await _settle()
    assert calls[1][2]["message"] == "Pour 2 of 5"


async def test_a_script_method_without_a_script_goes_nowhere():
    calls = []
    queue = AnnouncementQueue(AsyncMock(side_effect=lambda *a, **k: calls.append(a)),
                              sleep=AsyncMock(), clock=_Clock())
    queue.add({**_say("Hello"), "method": "script", "script": ""})
    await _settle()
    assert calls == []
