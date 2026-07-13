"""DataUpdateCoordinator for the xBloom Studio integration.

Local-only architecture: the coordinator's `data` is the locally-stored
recipe library (a list of Recipe dicts). Recipes are added by the user via
the integration's options flow; the store calls `async_request_refresh()`
when the library changes so the select entity sees the update immediately.

The MQTT-driven entities (sensor, binary_sensor, switch, event) bypass this
coordinator entirely.
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .storage import XBloomRecipeStore

_LOGGER = logging.getLogger(__name__)


class XBloomCoordinator(DataUpdateCoordinator):
    """Surfaces the locally-stored recipe library to entities (e.g. select)."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # local data — refreshed manually when storage changes
        )
        self.config_entry = config_entry
        self.store = XBloomRecipeStore(hass, config_entry.entry_id)

    async def _async_update_data(self) -> list[dict]:
        """Return the current recipe library from local storage."""
        return await self.store.async_load()

    async def async_add_recipe(self, recipe: dict) -> None:
        """Add a recipe and refresh subscribers."""
        await self.store.async_add(recipe)
        await self.async_request_refresh()

    async def async_remove_recipe(self, name: str) -> bool:
        """Remove a recipe by name and refresh subscribers."""
        removed = await self.store.async_remove(name)
        if removed:
            await self.async_request_refresh()
        return removed

    async def async_replace_recipe(self, recipe: dict) -> None:
        """Overwrite (or insert) a recipe by id and refresh subscribers."""
        await self.store.async_replace(recipe)
        await self.async_request_refresh()

    async def async_delete_recipe(self, table_id: str) -> bool:
        """Delete a recipe by id and refresh subscribers."""
        deleted = await self.store.async_delete(table_id)
        if deleted:
            await self.async_request_refresh()
        return deleted
