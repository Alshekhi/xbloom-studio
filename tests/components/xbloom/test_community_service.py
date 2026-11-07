"""Tests for the community hub services, `search_community` and
`get_community_recipe`.

The hub client is xbloom-py's and is tested there. What matters here is the
wrapper: both services are registered and removed, the call's fields reach
the client unchanged (voluptuous is stubbed in this suite, so the schema
itself is exercised on a live install), and every failure comes back as `ok: false` with a
message rather than as an exception.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from . import test_init as _ti  # noqa: F401

from custom_components.xbloom import async_setup_entry  # noqa: E402
from xbloom.exceptions import XBloomAPIError

PAGE = {"page": 1, "total_pages": 1, "total": 1, "recipes": [{"id": 4021, "name": "Test Kenya"}]}


async def _setup(entry):
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_register = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=lambda: None)
    hass.states = MagicMock()
    entry.async_on_unload = MagicMock()
    community = MagicMock()
    community.search = AsyncMock(return_value=PAGE)
    community.detail = AsyncMock(return_value={"id": 4021, "pours": []})
    with patch("custom_components.xbloom.XBloomCoordinator") as mc, \
         patch("custom_components.xbloom.XBloomClient") as mk, \
         patch("custom_components.xbloom.XBloomCommunityClient", return_value=community):
        mk.return_value = AsyncMock()
        coord = MagicMock()
        coord.async_config_entry_first_refresh = AsyncMock()
        coord.data = []
        mc.return_value = coord
        await async_setup_entry(hass, entry)
    registered = {
        c[0][1]: (c[0][2], c[1].get("schema"))
        for c in hass.services.async_register.call_args_list
        if len(c[0]) >= 3
    }
    return registered, community


def _call(**data):
    call = MagicMock()
    call.data = data
    return call


@pytest.fixture
async def services(mock_config_entry):
    return await _setup(mock_config_entry)


async def test_both_services_are_registered(services) -> None:
    registered, _ = services
    assert {"search_community", "get_community_recipe"} <= set(registered)


async def test_search_forwards_the_filters_and_returns_the_page(services) -> None:
    registered, community = services
    handler = registered["search_community"][0]
    res = await handler(_call(keyword="kenya", machine="Studio", origins=["Kenya"], sort="likes", page=1, page_size=20))
    community.search.assert_awaited_once_with(
        keyword="kenya", machine="Studio", origins=["Kenya"], sort="likes", page=1, page_size=20,
    )
    assert res == {"ok": True, **PAGE}


@pytest.mark.parametrize("error", [
    ValueError("not on the hub: Atlantis"),
    XBloomAPIError("community hub: busy"),
    aiohttp.ClientError("connection refused"),
])
async def test_search_failure_is_reported_not_raised(services, error) -> None:
    registered, community = services
    community.search.side_effect = error
    res = await registered["search_community"][0](_call(machine="Studio"))
    assert res == {"ok": False, "error": str(error)}


async def test_get_community_recipe_returns_the_detail(services) -> None:
    registered, community = services
    res = await registered["get_community_recipe"][0](_call(recipe_id=4021))
    community.detail.assert_awaited_once_with(4021)
    assert res == {"ok": True, "recipe": {"id": 4021, "pours": []}}


async def test_get_community_recipe_failure_is_reported(services) -> None:
    registered, community = services
    community.detail.side_effect = XBloomAPIError("community hub: This requires you to log in first")
    res = await registered["get_community_recipe"][0](_call(recipe_id=1))
    assert res["ok"] is False and "log in" in res["error"]
