"""One-shot commands sent while a recipe brew holds the link.

A recipe brew keeps its own Bluetooth link to the machine until it ends, and
that link is how the pours and the ending are heard. Pause and resume used to
open a second link; closing it took the brew's down with it, and nothing from
the machine arrived after that. So while a brew holds the link, they travel
over it.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .test_brew_completion_contract import (
    _Entry, _FakeBle, _make_hass, _setup_and_get_handlers,
)


class _Brewing(_FakeBle):
    """A brew's link that also carries one-shot commands."""

    sent: list[str] = []

    async def send_command(self, name, frame, **_kw):
        _Brewing.sent.append(name)
        return True


@pytest.fixture(autouse=True)
def _reset():
    _Brewing.sent = []
    _Brewing.instances = []
    _FakeBle.instances = []
    _FakeBle.enjoy = True
    yield
    _FakeBle.enjoy = True


def _machine_found():
    return patch("custom_components.xbloom._resolve_ble_device",
                 AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF")))


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_pause_and_resume_during_a_brew_go_over_its_link():
    _FakeBle.enjoy = False
    hass, entry = _make_hass(), _Entry()
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _Brewing):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await _settle()
        await handlers["brew_pause"](MagicMock(data={}))
        await handlers["brew_resume"](MagicMock(data={}))
        opened = len(_FakeBle.instances)
        entry.tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await entry.tasks[0]

    assert _Brewing.sent == ["brew_pause", "brew_resume"]
    assert opened == 1, "a second link tears the brew's down"


async def test_after_the_brew_ends_a_command_opens_its_own_link():
    hass, entry = _make_hass(), _Entry()
    with _machine_found(), patch("xbloom.ble.XBloomBleClient", _Brewing):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["start_brew"](MagicMock(data={}))
        await entry.tasks[0]
        await handlers["tare"](MagicMock(data={}))

    assert _Brewing.sent == ["tare"]
    assert len(_FakeBle.instances) == 2
