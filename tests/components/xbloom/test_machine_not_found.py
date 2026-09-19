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
