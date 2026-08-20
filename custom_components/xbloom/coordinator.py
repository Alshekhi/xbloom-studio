"""DataUpdateCoordinator for the xBloom Studio integration.

Two data sources, one surface. The coordinator's ``data`` is always the recipe
library (a list of Recipe dicts) that entities (e.g. the recipe select) read —
but where that library comes from depends on whether the user is logged in to
the xBloom cloud:

  * **Logged out** — the library is HA's local ``Store`` (``storage.py``).
    Recipes are created/edited/deleted locally via the options flow. This is
    the original BLE-only behavior; no cloud/vendor calls happen at all.
  * **Logged in** — the xBloom cloud is the single source of truth. Every
    refresh pulls the user's cloud recipe list and mirrors it into the local
    ``Store`` so entities keep working offline. Create/edit/delete route to the
    cloud, and the next refresh re-pulls the authoritative list.

This module is the Home Assistant *integration layer*: it owns credential
storage (the config entry), the HA data surface, and the local mirror. All
xBloom protocol/API knowledge — login, RSA, re-login-on-expiry — lives in the
portable vendor library (``vendor.xbloom.cloud``). The coordinator only
*supplies* the token to a vendor :class:`XBloomCloudSession` and *persists* a
refreshed one via a callback.

Refresh is fully event-driven — there is no background poll. The library is
re-pulled from the cloud when: a recipe is created/edited/deleted in HA, the
options-flow recipe screens are opened, or the *Refresh Recipes* button is
pressed. (HA gives the backend no "dashboard dropdown opened" event, and the
xBloom recipe API has no push, so a phone-side edit shows on a dashboard
dropdown only after one of those triggers.)
"""
from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CLOUD,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_MEMBER_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REMEMBER,
    CONF_CLOUD_TOKEN,
    DOMAIN,
)
from .storage import XBloomRecipeStore
from .vendor.xbloom.cloud import (
    XBloomAuthError,
    XBloomCloudClient,
    XBloomCloudSession,
)
from .vendor.xbloom.exceptions import XBloomAPIError

_LOGGER = logging.getLogger(__name__)


class XBloomCoordinator(DataUpdateCoordinator):
    """Surfaces the recipe library (local or cloud) to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        cloud: XBloomCloudClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # event-driven; no background poll
        )
        self.config_entry = config_entry
        self.store = XBloomRecipeStore(hass, config_entry.entry_id)
        self._cloud = cloud

    # ------------------------------------------------------------------ #
    # Credential state (integration-layer concern)                        #
    # ------------------------------------------------------------------ #
    def _creds(self) -> dict | None:
        return self.config_entry.data.get(CONF_CLOUD)

    @property
    def cloud_logged_in(self) -> bool:
        creds = self._creds()
        return bool(
            creds
            and creds.get(CONF_CLOUD_TOKEN)
            and creds.get(CONF_CLOUD_MEMBER_ID) is not None
        )

    @property
    def cloud_email(self) -> str | None:
        creds = self._creds()
        return creds.get(CONF_CLOUD_EMAIL) if creds else None

    def _save_creds(self, creds: dict | None) -> None:
        """Persist (or clear) cloud credentials on the config entry."""
        if creds is None:
            data = {
                k: v for k, v in self.config_entry.data.items() if k != CONF_CLOUD
            }
        else:
            data = {**self.config_entry.data, CONF_CLOUD: creds}
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)

    @callback
    def _on_token_refreshed(self, member_id: int, token: str) -> None:
        """Vendor session re-logged-in — persist the fresh token."""
        creds = self._creds() or {}
        self._save_creds({
            **creds,
            CONF_CLOUD_MEMBER_ID: member_id,
            CONF_CLOUD_TOKEN: token,
        })

    def _session(self) -> XBloomCloudSession | None:
        """Build a vendor session from stored creds, or None if logged out.

        The password may be absent (the user didn't opt to remember it); the
        session then can't self-refresh and re-raises on token expiry, which we
        turn into a reauth prompt.
        """
        creds = self._creds()
        if not creds:
            return None
        return XBloomCloudSession(
            self._cloud,
            email=creds[CONF_CLOUD_EMAIL],
            password=creds.get(CONF_CLOUD_PASSWORD),
            member_id=creds[CONF_CLOUD_MEMBER_ID],
            token=creds[CONF_CLOUD_TOKEN],
            on_token_refreshed=self._on_token_refreshed,
        )

    def _start_reauth(self) -> None:
        """Ask HA to open the reauth flow (user must log in again)."""
        _LOGGER.warning(
            "xbloom cloud: session needs re-authentication for %s",
            self.cloud_email,
        )
        self.config_entry.async_start_reauth(self.hass)

    # ------------------------------------------------------------------ #
    # Data source                                                         #
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> list[dict]:
        """Return the current recipe library (cloud when logged in, else local)."""
        session = self._session()
        if session is None:
            return await self.store.async_load()
        try:
            recipes = await session.list_recipes()
        except XBloomAuthError as err:
            # Token invalid/expired and we can't refresh (no stored password, or
            # the credentials themselves are no longer valid). Prompt re-login.
            raise ConfigEntryAuthFailed(str(err)) from err
        except (XBloomAPIError, aiohttp.ClientError) as err:
            _LOGGER.warning(
                "xbloom cloud: recipe list failed (%s) — serving last cached copy",
                err,
            )
            return await self.store.async_load()
        # Mirror the authoritative cloud list into local storage so entities
        # keep working offline (and so a later logout leaves a usable library).
        await self.store.async_replace_all(recipes)
        return recipes

    # ------------------------------------------------------------------ #
    # Recipe CRUD — routed to cloud when logged in, else local            #
    # ------------------------------------------------------------------ #
    async def _cloud_op(self, coro):
        """Await a cloud coroutine, opening a reauth prompt on auth failure."""
        try:
            return await coro
        except XBloomAuthError:
            self._start_reauth()
            raise

    async def async_add_recipe(self, recipe: dict) -> None:
        """Add a recipe and refresh subscribers."""
        session = self._session()
        if session is not None:
            await self._cloud_op(session.create_recipe(recipe))
        else:
            await self.store.async_add(recipe)
        await self.async_request_refresh()

    async def async_remove_recipe(self, name: str) -> bool:
        """Remove a recipe by name and refresh subscribers."""
        session = self._session()
        if session is not None:
            table_id = next(
                (str(r["id"]) for r in (self.data or []) if r.get("name") == name),
                None,
            )
            if table_id is None:
                return False
            await self._cloud_op(session.delete_recipe(table_id))
            await self.async_request_refresh()
            return True
        removed = await self.store.async_remove(name)
        if removed:
            await self.async_request_refresh()
        return removed

    async def async_replace_recipe(self, recipe: dict) -> None:
        """Overwrite (or insert) a recipe by id and refresh subscribers."""
        session = self._session()
        if session is not None:
            table_id = str(recipe.get("id") or "")
            if table_id and not table_id.startswith("local-"):
                await self._cloud_op(session.update_recipe(table_id, recipe))
            else:
                # A locally-created recipe saved while logged in — create it in
                # the cloud so it gets a real tableId.
                await self._cloud_op(session.create_recipe(recipe))
            await self.async_request_refresh()
            return
        await self.store.async_replace(recipe)
        await self.async_request_refresh()

    async def async_delete_recipe(self, table_id: str) -> bool:
        """Delete a recipe by id and refresh subscribers."""
        session = self._session()
        if session is not None:
            await self._cloud_op(session.delete_recipe(table_id))
            await self.async_request_refresh()
            return True
        deleted = await self.store.async_delete(table_id)
        if deleted:
            await self.async_request_refresh()
        return deleted

    # ------------------------------------------------------------------ #
    # Login / logout / first-login reconciliation                         #
    # ------------------------------------------------------------------ #
    async def async_validate_login(self, email: str, password: str) -> dict:
        """Verify credentials without persisting them. Returns ``{memberId, token}``.

        Raises ``XBloomAuthError``/``XBloomAPIError`` on failure so the options
        flow can show an error.
        """
        return await self._cloud.login(email, password)

    @staticmethod
    def _build_creds(
        *, email: str, password: str, member_id: int, token: str, remember: bool
    ) -> dict:
        """Assemble the stored credential dict.

        The password is persisted only when ``remember`` is set — otherwise just
        the token is kept, and an expired token later triggers a reauth prompt.
        """
        creds = {
            CONF_CLOUD_EMAIL: email,
            CONF_CLOUD_MEMBER_ID: member_id,
            CONF_CLOUD_TOKEN: token,
            CONF_CLOUD_REMEMBER: remember,
        }
        if remember:
            creds[CONF_CLOUD_PASSWORD] = password
        return creds

    async def async_local_only_recipes(
        self, member_id: int, token: str
    ) -> list[dict]:
        """Local recipes that are NOT already in the user's cloud library.

        Compared by recipe id. This is what "your local recipes" really means at
        login time: a recipe whose id already exists in the cloud is a cached
        mirror from a previous session (a log-out/log-in round trip), not a
        genuinely-local recipe — uploading it would duplicate it. A hand-made
        local recipe (``local-…`` id) or a share-import (a foreign id) won't
        match any cloud id, so it's correctly treated as local.
        """
        cloud = await self._cloud.list_recipes(member_id, token)
        cloud_ids = {str(r.get("id")) for r in cloud}
        local = await self.store.async_load()
        return [r for r in local if str(r.get("id") or "") not in cloud_ids]

    async def async_finalize_login(
        self,
        *,
        email: str,
        password: str,
        member_id: int,
        token: str,
        remember: bool,
        upload_local: bool,
    ) -> None:
        """Persist credentials and reconcile the pre-existing local library.

        ``upload_local`` True pushes the genuinely-local recipes (those not
        already in the cloud — see :meth:`async_local_only_recipes`) up to the
        cloud; False discards the local library. Either way the local ``Store``
        is cleared — the subsequent refresh repopulates it as a mirror of the
        cloud, which becomes the single source of truth. Uploading only the
        local-only set avoids duplicating a cached mirror on a re-login.
        """
        if upload_local:
            for recipe in await self.async_local_only_recipes(member_id, token):
                try:
                    await self._cloud.create_recipe(member_id, token, recipe)
                except XBloomAPIError as err:
                    _LOGGER.warning(
                        "xbloom cloud: uploading local recipe %r failed: %s",
                        recipe.get("name"), err,
                    )
        await self.store.async_replace_all([])
        self._save_creds(self._build_creds(
            email=email, password=password, member_id=member_id,
            token=token, remember=remember,
        ))
        await self.async_request_refresh()

    async def async_apply_reauth(
        self, *, email: str, password: str, member_id: int, token: str,
        remember: bool,
    ) -> None:
        """Update stored credentials after a successful reauth (no reconcile)."""
        self._save_creds(self._build_creds(
            email=email, password=password, member_id=member_id,
            token=token, remember=remember,
        ))
        await self.async_request_refresh()

    async def async_cloud_logout(self) -> None:
        """Clear cloud credentials; fall back to the local (mirrored) library."""
        self._save_creds(None)
        await self.async_request_refresh()
