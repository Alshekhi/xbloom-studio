"""Tests for coordinator.py — the local/cloud recipe library switch.

The coordinator has one job with two modes: logged out, the recipe library is
HA's local Store; logged in, the xBloom cloud is authoritative and the Store
becomes a mirror. Almost every bug worth catching here is a mode confusion —
a cloud call made while logged out, a local write made while logged in, or a
password persisted when the user said not to remember it.

The other theme is *not losing recipes*. A cloud outage must serve the cached
mirror rather than blanking the library, and logging in must not duplicate the
recipes that were mirrored down during a previous session.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.xbloom.const import (
    CONF_CLOUD,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_MEMBER_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REMEMBER,
    CONF_CLOUD_TOKEN,
)
from custom_components.xbloom.coordinator import XBloomCoordinator
from xbloom.cloud import XBloomAuthError
from xbloom.exceptions import XBloomAPIError

CREDS = {
    CONF_CLOUD_EMAIL: "user@example.invalid",
    CONF_CLOUD_MEMBER_ID: 4242,
    CONF_CLOUD_TOKEN: "tok-abc",
    CONF_CLOUD_REMEMBER: False,
}

LOCAL_RECIPE = {"id": "local-1", "name": "Local Blend"}
CLOUD_RECIPE = {"id": "9001", "name": "Cloud Blend"}


def _make(*, creds: dict | None = None, stored: list[dict] | None = None):
    """Build a coordinator with a fake store and cloud client.

    DataUpdateCoordinator.__init__ is stubbed out — we're testing this class's
    own logic, not HA's refresh machinery.
    """
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_CLOUD: creds} if creds else {}
    entry.async_start_reauth = MagicMock()

    cloud = MagicMock()
    cloud.login = AsyncMock(return_value={"memberId": 1, "token": "t"})
    cloud.list_recipes = AsyncMock(return_value=[])
    cloud.create_recipe = AsyncMock()

    with patch.object(XBloomCoordinator, "__init__", lambda *a, **k: None):
        coord = XBloomCoordinator(hass, entry, cloud)
    coord.hass = hass
    coord.config_entry = entry
    coord._cloud = cloud
    coord.data = []
    coord.async_request_refresh = AsyncMock()

    store = MagicMock()
    store.async_load = AsyncMock(return_value=list(stored or []))
    store.async_add = AsyncMock()
    store.async_remove = AsyncMock(return_value=True)
    store.async_replace = AsyncMock()
    store.async_delete = AsyncMock(return_value=True)
    store.async_replace_all = AsyncMock()
    coord.store = store
    return coord


def _saved_creds(coord) -> dict | None:
    """The CONF_CLOUD payload from the most recent config-entry write."""
    call = coord.hass.config_entries.async_update_entry.call_args
    return call.kwargs["data"].get(CONF_CLOUD)


# --------------------------------------------------------------------------- #
# Login state                                                                 #
# --------------------------------------------------------------------------- #
def test_logged_out_without_credentials() -> None:
    assert _make().cloud_logged_in is False


def test_logged_in_with_token_and_member_id() -> None:
    assert _make(creds=CREDS).cloud_logged_in is True


def test_credentials_without_a_token_are_not_a_login() -> None:
    """A half-written creds dict must not be mistaken for a session."""
    creds = {**CREDS}
    del creds[CONF_CLOUD_TOKEN]
    assert _make(creds=creds).cloud_logged_in is False


def test_credentials_without_a_member_id_are_not_a_login() -> None:
    creds = {**CREDS}
    del creds[CONF_CLOUD_MEMBER_ID]
    assert _make(creds=creds).cloud_logged_in is False


def test_member_id_zero_still_counts_as_logged_in() -> None:
    """0 is a falsy int but a legitimate id — the check must be `is not None`."""
    assert _make(creds={**CREDS, CONF_CLOUD_MEMBER_ID: 0}).cloud_logged_in is True


def test_email_is_exposed_for_the_options_screen() -> None:
    assert _make(creds=CREDS).cloud_email == "user@example.invalid"


def test_email_is_none_when_logged_out() -> None:
    assert _make().cloud_email is None


# --------------------------------------------------------------------------- #
# Where the library comes from                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_logged_out_reads_the_local_store() -> None:
    coord = _make(stored=[LOCAL_RECIPE])
    assert await coord._async_update_data() == [LOCAL_RECIPE]


@pytest.mark.asyncio
async def test_logged_out_never_touches_the_cloud() -> None:
    coord = _make(stored=[LOCAL_RECIPE])
    await coord._async_update_data()
    coord._cloud.list_recipes.assert_not_called()


@pytest.mark.asyncio
async def test_logged_in_reads_the_cloud() -> None:
    coord = _make(creds=CREDS)
    with patch.object(
        type(coord._session()), "list_recipes", AsyncMock(return_value=[CLOUD_RECIPE])
    ):
        assert await coord._async_update_data() == [CLOUD_RECIPE]


@pytest.mark.asyncio
async def test_cloud_list_is_mirrored_into_local_storage() -> None:
    """So entities keep working offline, and a later logout leaves a library."""
    coord = _make(creds=CREDS)
    with patch.object(
        type(coord._session()), "list_recipes", AsyncMock(return_value=[CLOUD_RECIPE])
    ):
        await coord._async_update_data()
    coord.store.async_replace_all.assert_awaited_once_with([CLOUD_RECIPE])


@pytest.mark.asyncio
async def test_cloud_outage_serves_the_cached_mirror() -> None:
    """A network blip must not blank the user's recipe list."""
    coord = _make(creds=CREDS, stored=[CLOUD_RECIPE])
    with patch.object(
        type(coord._session()),
        "list_recipes",
        AsyncMock(side_effect=XBloomAPIError("503")),
    ):
        assert await coord._async_update_data() == [CLOUD_RECIPE]


@pytest.mark.asyncio
async def test_cloud_outage_does_not_overwrite_the_mirror() -> None:
    """Serving the cache must not then write the cache back over itself."""
    coord = _make(creds=CREDS, stored=[CLOUD_RECIPE])
    with patch.object(
        type(coord._session()),
        "list_recipes",
        AsyncMock(side_effect=XBloomAPIError("503")),
    ):
        await coord._async_update_data()
    coord.store.async_replace_all.assert_not_called()


@pytest.mark.asyncio
async def test_expired_token_raises_config_entry_auth_failed() -> None:
    """This is what makes HA show the 'reconfigure' prompt."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    coord = _make(creds=CREDS)
    with patch.object(
        type(coord._session()),
        "list_recipes",
        AsyncMock(side_effect=XBloomAuthError("expired", expired=True)),
    ):
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


# --------------------------------------------------------------------------- #
# CRUD routing                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_add_writes_locally_when_logged_out() -> None:
    coord = _make()
    await coord.async_add_recipe(LOCAL_RECIPE)
    coord.store.async_add.assert_awaited_once_with(LOCAL_RECIPE)
    coord.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_goes_to_the_cloud_when_logged_in() -> None:
    coord = _make(creds=CREDS)
    with patch.object(type(coord._session()), "create_recipe", AsyncMock()) as create:
        await coord.async_add_recipe(CLOUD_RECIPE)
    create.assert_awaited_once()
    coord.store.async_add.assert_not_called()


@pytest.mark.asyncio
async def test_delete_removes_locally_when_logged_out() -> None:
    coord = _make()
    assert await coord.async_delete_recipe("local-1") is True
    coord.store.async_delete.assert_awaited_once_with("local-1")


@pytest.mark.asyncio
async def test_delete_goes_to_the_cloud_when_logged_in() -> None:
    coord = _make(creds=CREDS)
    with patch.object(type(coord._session()), "delete_recipe", AsyncMock()) as delete:
        assert await coord.async_delete_recipe("9001") is True
    delete.assert_awaited_once_with("9001")
    coord.store.async_delete.assert_not_called()


@pytest.mark.asyncio
async def test_local_delete_that_removed_nothing_skips_the_refresh() -> None:
    coord = _make()
    coord.store.async_delete = AsyncMock(return_value=False)
    assert await coord.async_delete_recipe("nope") is False
    coord.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_remove_by_name_resolves_the_cloud_table_id() -> None:
    coord = _make(creds=CREDS)
    coord.data = [CLOUD_RECIPE]
    with patch.object(type(coord._session()), "delete_recipe", AsyncMock()) as delete:
        assert await coord.async_remove_recipe("Cloud Blend") is True
    delete.assert_awaited_once_with("9001")


@pytest.mark.asyncio
async def test_remove_by_unknown_name_is_a_no_op() -> None:
    coord = _make(creds=CREDS)
    coord.data = [CLOUD_RECIPE]
    with patch.object(type(coord._session()), "delete_recipe", AsyncMock()) as delete:
        assert await coord.async_remove_recipe("Nonexistent") is False
    delete.assert_not_called()


@pytest.mark.asyncio
async def test_editing_a_cloud_recipe_updates_it() -> None:
    coord = _make(creds=CREDS)
    with patch.object(type(coord._session()), "update_recipe", AsyncMock()) as update:
        await coord.async_replace_recipe(CLOUD_RECIPE)
    update.assert_awaited_once()


@pytest.mark.asyncio
async def test_saving_a_local_recipe_while_logged_in_creates_it_in_the_cloud() -> None:
    """A `local-…` id has no cloud counterpart to update, so it must be created."""
    coord = _make(creds=CREDS)
    session_cls = type(coord._session())
    with patch.object(session_cls, "update_recipe", AsyncMock()) as update, \
         patch.object(session_cls, "create_recipe", AsyncMock()) as create:
        await coord.async_replace_recipe(LOCAL_RECIPE)
    create.assert_awaited_once()
    update.assert_not_called()


@pytest.mark.asyncio
async def test_saving_an_id_less_recipe_while_logged_in_creates_it() -> None:
    coord = _make(creds=CREDS)
    session_cls = type(coord._session())
    with patch.object(session_cls, "update_recipe", AsyncMock()) as update, \
         patch.object(session_cls, "create_recipe", AsyncMock()) as create:
        await coord.async_replace_recipe({"name": "No id"})
    create.assert_awaited_once()
    update.assert_not_called()


@pytest.mark.asyncio
async def test_auth_failure_during_a_write_opens_the_reauth_flow() -> None:
    coord = _make(creds=CREDS)
    with patch.object(
        type(coord._session()),
        "create_recipe",
        AsyncMock(side_effect=XBloomAuthError("expired", expired=True)),
    ):
        with pytest.raises(XBloomAuthError):
            await coord.async_add_recipe(CLOUD_RECIPE)
    coord.config_entry.async_start_reauth.assert_called_once()


# --------------------------------------------------------------------------- #
# Credential persistence                                                      #
# --------------------------------------------------------------------------- #
def test_password_is_stored_only_when_remember_is_set() -> None:
    creds = XBloomCoordinator._build_creds(
        email="a@b.c", password="hunter2", member_id=1, token="t", remember=True
    )
    assert creds[CONF_CLOUD_PASSWORD] == "hunter2"


def test_password_is_not_stored_when_remember_is_unset() -> None:
    """Opting out of 'remember me' must not leave the password on disk."""
    creds = XBloomCoordinator._build_creds(
        email="a@b.c", password="hunter2", member_id=1, token="t", remember=False
    )
    assert CONF_CLOUD_PASSWORD not in creds


def test_a_refreshed_token_is_persisted() -> None:
    coord = _make(creds=CREDS)
    coord._on_token_refreshed(4242, "tok-new")
    assert _saved_creds(coord)[CONF_CLOUD_TOKEN] == "tok-new"


def test_a_refreshed_token_keeps_the_stored_email() -> None:
    coord = _make(creds=CREDS)
    coord._on_token_refreshed(4242, "tok-new")
    assert _saved_creds(coord)[CONF_CLOUD_EMAIL] == CREDS[CONF_CLOUD_EMAIL]


@pytest.mark.asyncio
async def test_logout_clears_the_credentials() -> None:
    coord = _make(creds=CREDS)
    await coord.async_cloud_logout()
    assert _saved_creds(coord) is None


@pytest.mark.asyncio
async def test_logout_falls_back_to_the_mirrored_library() -> None:
    """The mirror is what makes logout non-destructive."""
    coord = _make(creds=CREDS, stored=[CLOUD_RECIPE])
    await coord.async_cloud_logout()
    coord.async_request_refresh.assert_awaited_once()
    coord.config_entry.data = {}
    assert await coord._async_update_data() == [CLOUD_RECIPE]


# --------------------------------------------------------------------------- #
# First-login reconciliation                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_local_only_excludes_recipes_already_in_the_cloud() -> None:
    """A mirrored recipe from a previous session is not 'local' — uploading it
    would duplicate it on every logout/login round trip."""
    coord = _make(stored=[LOCAL_RECIPE, CLOUD_RECIPE])
    coord._cloud.list_recipes = AsyncMock(return_value=[CLOUD_RECIPE])
    assert await coord.async_local_only_recipes(1, "t") == [LOCAL_RECIPE]


@pytest.mark.asyncio
async def test_local_only_keeps_share_imports() -> None:
    """A share-import has a foreign id that matches no cloud id — still local."""
    imported = {"id": "77", "name": "Shared"}
    coord = _make(stored=[imported])
    coord._cloud.list_recipes = AsyncMock(return_value=[CLOUD_RECIPE])
    assert await coord.async_local_only_recipes(1, "t") == [imported]


@pytest.mark.asyncio
async def test_login_uploads_local_recipes_when_asked() -> None:
    coord = _make(stored=[LOCAL_RECIPE])
    coord._cloud.list_recipes = AsyncMock(return_value=[])
    await coord.async_finalize_login(
        email="a@b.c", password="p", member_id=1, token="t",
        remember=False, upload_local=True,
    )
    coord._cloud.create_recipe.assert_awaited_once_with(1, "t", LOCAL_RECIPE)


@pytest.mark.asyncio
async def test_login_discards_local_recipes_when_not_asked() -> None:
    coord = _make(stored=[LOCAL_RECIPE])
    coord._cloud.list_recipes = AsyncMock(return_value=[])
    await coord.async_finalize_login(
        email="a@b.c", password="p", member_id=1, token="t",
        remember=False, upload_local=False,
    )
    coord._cloud.create_recipe.assert_not_called()


@pytest.mark.asyncio
async def test_login_clears_the_local_store_either_way() -> None:
    """The store becomes a mirror of the cloud; stale local rows must go."""
    coord = _make(stored=[LOCAL_RECIPE])
    coord._cloud.list_recipes = AsyncMock(return_value=[])
    await coord.async_finalize_login(
        email="a@b.c", password="p", member_id=1, token="t",
        remember=False, upload_local=False,
    )
    coord.store.async_replace_all.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_a_failed_upload_does_not_abort_the_login() -> None:
    """One rejected recipe must not leave the user half-logged-in."""
    coord = _make(stored=[LOCAL_RECIPE])
    coord._cloud.list_recipes = AsyncMock(return_value=[])
    coord._cloud.create_recipe = AsyncMock(side_effect=XBloomAPIError("rejected"))
    await coord.async_finalize_login(
        email="a@b.c", password="p", member_id=1, token="t",
        remember=True, upload_local=True,
    )
    assert _saved_creds(coord)[CONF_CLOUD_TOKEN] == "t"


@pytest.mark.asyncio
async def test_reauth_updates_credentials_without_reconciling() -> None:
    """Reauth is a token refresh, not a first login — nothing may be uploaded."""
    coord = _make(creds=CREDS, stored=[LOCAL_RECIPE])
    await coord.async_apply_reauth(
        email="a@b.c", password="p", member_id=7, token="tok-fresh", remember=True,
    )
    assert _saved_creds(coord)[CONF_CLOUD_TOKEN] == "tok-fresh"
    coord._cloud.create_recipe.assert_not_called()
    coord.store.async_replace_all.assert_not_called()
