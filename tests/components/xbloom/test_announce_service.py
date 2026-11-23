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
