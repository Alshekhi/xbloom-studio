"""xbloom.announce and xbloom.wait_for_announcements reach the one queue."""
from unittest.mock import AsyncMock, MagicMock

from . import test_init as _ti  # noqa: F401
from .test_build_recipe_service import _handlers


async def test_announce_hands_the_message_to_the_queue(mock_config_entry):
    handlers, _ = await _handlers(mock_config_entry)
    queue = MagicMock()
    mock_config_entry.runtime_data.announcements = queue
    call = MagicMock(data={"message": "Pour 2 of 5", "method": "alexa", "targets": ["media_player.k"],
                           "alexa_type": "tts", "kind": "announcement"})
    await handlers["announce"](call)
    item = queue.add.call_args.args[0]
    assert item["message"] == "Pour 2 of 5" and item["targets"] == ["media_player.k"]


async def test_one_target_given_as_text_is_a_list(mock_config_entry):
    handlers, _ = await _handlers(mock_config_entry)
    queue = MagicMock()
    mock_config_entry.runtime_data.announcements = queue
    await handlers["announce"](MagicMock(data={"message": "x", "method": "tts", "targets": "media_player.k"}))
    assert queue.add.call_args.args[0]["targets"] == ["media_player.k"]


async def test_wait_for_announcements_waits_on_the_queue(mock_config_entry):
    handlers, _ = await _handlers(mock_config_entry)
    queue = MagicMock()
    queue.async_wait_quiet = AsyncMock()
    mock_config_entry.runtime_data.announcements = queue
    await handlers["wait_for_announcements"](MagicMock(data={"timeout_s": 45}))
    queue.async_wait_quiet.assert_awaited_once_with(timeout=45)


def test_only_a_notify_service_a_tts_engine_and_media_players_are_accepted():
    import pytest
    from custom_components.xbloom.announce import media_players, notify_service, tts_engine
    for check, bad in ((notify_service, "lock.unlock"), (notify_service, "notify"),
                       (tts_engine, "lock.front"), (media_players, ["lock.front"]),
                       (media_players, "media_player.k; x")):
        with pytest.raises(ValueError):
            check(bad)
    assert notify_service("notify.mobile_app_x") == "notify.mobile_app_x"
    assert notify_service("") == "" and tts_engine("") == ""
    assert tts_engine("tts.piper") == "tts.piper"
    assert media_players("media_player.k") == ["media_player.k"]
    assert media_players(["media_player.a", "media_player.b"]) == ["media_player.a", "media_player.b"]


async def test_announce_carries_the_callers_context(mock_config_entry):
    handlers, _ = await _handlers(mock_config_entry)
    queue = MagicMock()
    mock_config_entry.runtime_data.announcements = queue
    call = MagicMock(data={"message": "x"})
    await handlers["announce"](call)
    assert queue.add.call_args.args[0]["context"] is call.context


def test_only_a_script_is_accepted_to_speak_through():
    import pytest
    from custom_components.xbloom.announce import script_entity
    for bad in ("lock.unlock", "script", "script.a; b", "automation.x"):
        with pytest.raises(ValueError):
            script_entity(bad)
    assert script_entity("script.speak") == "script.speak" and script_entity("") == ""
