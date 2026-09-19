"""An action that cannot find the machine says so to its caller.

These actions logged "HA bluetooth has not seen …" and returned as if they had
worked. Home Assistant answered the caller with success, and an agent that then
read the machine status got its last value — "ok" — and reported the machine
fine while it was off. A dashboard press showed nothing at all.

start_brew is not here: it reports the same case through
`xbloom_brew_failed` (`machine_not_found`), which is covered on its own.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from .test_held_session import _handlers_with

CALLS = {
    "refresh_status": {},
    "stop_brew": {},
    "ble_connect": {},
    "tare": {},
    "grind": {"size": 50, "speed": 80, "seconds": 0},
    "brew_standalone": {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("service", sorted(CALLS))
async def test_an_action_that_cannot_find_the_machine_is_an_error(service):
    _, _, handlers = await _handlers_with(None)
    with patch("custom_components.xbloom._resolve_ble_device", AsyncMock(return_value=None)):
        with pytest.raises(HomeAssistantError) as err:
            await handlers[service](MagicMock(data=CALLS[service]))
    assert (err.value.translation_domain, err.value.translation_key) == (
        "xbloom", "machine_not_found",
    )


class _Silent:
    """A link that connects, and a machine that reports nothing over it."""

    def __init__(self, *_a, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def read_status_snapshot(self, timeout):
        return None


class _Broken(_Silent):
    async def __aenter__(self):
        raise OSError("le-connection-abort-by-local")


@pytest.mark.asyncio
@pytest.mark.parametrize("client, key", [(_Silent, "no_status"), (_Broken, "connection_failed")])
async def test_a_refresh_that_reads_nothing_is_an_error(client, key):
    # Logged and returned as success, it left the status sensors at their last
    # value, which a caller then read as the machine's state now.
    _, _, handlers = await _handlers_with(None)
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", client):
        with pytest.raises(HomeAssistantError) as err:
            await handlers["refresh_status"](MagicMock(data={}))
    assert err.value.translation_key == key
