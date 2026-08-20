"""Text entity for the brew customizer: the name used by 'Save as new recipe'.

Prefills with a suggestion based on the picked recipe (editable), and re-seeds
whenever the recipe picker changes. Pure input — the Save action reads it.
"""
import logging

from homeassistant.components.text import TextEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

# The recipe picker whose selection seeds the suggested name.
_RECIPE_SELECT = "select.xbloom_studio_recipe"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([XBloomNewRecipeName(entry)])


class XBloomNewRecipeName(TextEntity):
    """Editable name for 'Save as new recipe'; suggests '<recipe> (custom)'."""

    _attr_has_entity_name = True
    _attr_name = "New Recipe Name"
    _attr_unique_id = "xbloom_new_recipe_name"
    _attr_icon = "mdi:rename-box"
    _attr_native_max = 60
    _attr_native_min = 0
    _attr_mode = "text"

    def __init__(self, entry) -> None:
        self._entry = entry
        self._attr_native_value = ""

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "xbloom_studio")},
            name="xBloom Studio",
            manufacturer="xBloom",
            model="Studio",
        )

    def _suggested(self) -> str:
        st = self.hass.states.get(_RECIPE_SELECT)
        if st is None or st.state in ("unknown", "unavailable", ""):
            return ""
        return f"{st.state} (custom)"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._attr_native_value = self._suggested()

        @callback
        def _on_recipe_change(_event) -> None:
            # Re-suggest for the newly-picked recipe. (A brew customization is a
            # fresh intent, so overwriting a stale suggestion is expected.)
            self._attr_native_value = self._suggested()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [_RECIPE_SELECT], _on_recipe_change,
            )
        )

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
