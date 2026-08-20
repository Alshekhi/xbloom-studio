"""Tests for the Connect switch (switch.XBloomConnectSwitch).

The switch is the user-visible handle on a BLE session that can end without the
user touching anything — an idle timeout, or the machine going out of range. A
switch stuck ON after the session died is worse than no switch: it tells a
VoiceOver user the machine is connected when it isn't.

Note the unique_id assertion. PR #2 renamed this entity from
`xbloom_live_control_switch`, which orphans the old entity and breaks any
automation referencing it — the test pins the new id so a further rename is a
deliberate act, not a silent one.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.xbloom.switch import XBloomConnectSwitch


def _make():
    listener = AsyncMock()
    entity = XBloomConnectSwitch(listener)
    entity.hass = MagicMock()
    entity.hass.bus.async_fire = MagicMock()
    entity.hass.bus.async_listen = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity.async_on_remove = MagicMock()
    return entity, listener


def test_identity_is_pinned() -> None:
    """Renamed from xbloom_live_control_switch in PR #2 — a breaking change."""
    assert XBloomConnectSwitch._attr_unique_id == "xbloom_connect_switch"
    assert XBloomConnectSwitch._attr_name == "Connect"


def test_starts_off() -> None:
    entity, _ = _make()
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_turn_on_starts_the_session() -> None:
    entity, listener = _make()
    await entity.async_turn_on()
    listener.start.assert_awaited_once()
    assert entity._attr_is_on is True


@pytest.mark.asyncio
async def test_turn_off_stops_the_session() -> None:
    entity, listener = _make()
    await entity.async_turn_on()
    await entity.async_turn_off()
    listener.stop.assert_awaited_once()
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_turn_off_announces_the_session_end() -> None:
    """Live-only consumers (current_module) must clear on an explicit disconnect."""
    entity, _ = _make()
    await entity.async_turn_off()
    entity.hass.bus.async_fire.assert_called_once_with(
        "xbloom_connect_stopped", {"reason": "user"}
    )


@pytest.mark.asyncio
async def test_removal_releases_the_ble_link() -> None:
    """A reload must not leave the link held, or the iOS app can't reclaim it."""
    entity, listener = _make()
    await entity.async_turn_on()
    await entity.async_will_remove_from_hass()
    listener.stop.assert_awaited_once()


# --------------------------------------------------------------------------- #
# The switch must follow the session, not just command it                     #
# --------------------------------------------------------------------------- #
def _handlers(entity) -> dict:
    """Event name → callback, as registered in async_added_to_hass."""
    return {c.args[0]: c.args[1] for c in entity.hass.bus.async_listen.call_args_list}


@pytest.mark.asyncio
async def _added(entity):
    await entity.async_added_to_hass()
    return _handlers(entity)


@pytest.mark.asyncio
async def test_connect_failure_flips_the_switch_off() -> None:
    entity, _ = _make()
    await entity.async_turn_on()
    handlers = await _added(entity)
    handlers["xbloom_connect_failed"](MagicMock())
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_idle_timeout_flips_the_switch_off() -> None:
    """The session auto-expires so the iOS app can reclaim BLE."""
    entity, _ = _make()
    await entity.async_turn_on()
    handlers = await _added(entity)
    handlers["xbloom_connect_auto_stopped"](MagicMock())
    assert entity._attr_is_on is False


@pytest.mark.asyncio
async def test_lifecycle_events_while_already_off_do_not_rewrite_state() -> None:
    entity, _ = _make()
    handlers = await _added(entity)
    entity.async_write_ha_state.reset_mock()
    handlers["xbloom_connect_failed"](MagicMock())
    handlers["xbloom_connect_auto_stopped"](MagicMock())
    entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_both_lifecycle_events_are_subscribed() -> None:
    entity, _ = _make()
    handlers = await _added(entity)
    assert "xbloom_connect_failed" in handlers
    assert "xbloom_connect_auto_stopped" in handlers
