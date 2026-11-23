"""The Brew Story sensor and the Brew Stories select."""
from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from ..ble_entities import _device_info
from . import LANGUAGES, MODES
from .runtime import signal_story

# A state is at most 255 characters; the full text is in the attributes.
_STATE_LIMIT = 255


class XBloomBrewStorySensor(SensorEntity):
    """The story part on screen, with the current pour's line. Live only."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "brew_story"
    _attr_unique_id = "xbloom_brew_story"
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def _runtime(self):
        return self._entry.runtime_data.stories

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def native_value(self) -> str | None:
        heading = self._runtime.current["heading"] if self._runtime else None
        return heading[:_STATE_LIMIT] if heading else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        current = self._runtime.current if self._runtime else {}
        return {key: current.get(key) for key in ("now", "story", "kind", "teaser")}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _changed() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_story(self._entry.entry_id), _changed))


class XBloomBrewStoriesSelect(SelectEntity, RestoreEntity):
    """Off, the built-in stories, or the agent's while one is set."""

    _attr_has_entity_name = True
    _attr_translation_key = "brew_stories"
    _attr_unique_id = "xbloom_brew_stories"
    _attr_icon = "mdi:book-open-page-variant"

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def options(self) -> list[str]:
        runtime = self._entry.runtime_data.stories
        if runtime is not None and runtime.agent_entity:
            return list(MODES)
        return [mode for mode in MODES if mode != "agent"]

    @property
    def current_option(self) -> str | None:
        runtime = self._entry.runtime_data.stories
        return runtime.mode if runtime else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        runtime = self._entry.runtime_data.stories
        if last is not None and last.state in self.options and runtime is not None:
            runtime.mode = last.state

    async def async_select_option(self, option: str) -> None:
        if option in self.options and self._entry.runtime_data.stories is not None:
            self._entry.runtime_data.stories.set_mode(option)
            self.async_write_ha_state()


class XBloomStoryLanguageSelect(SelectEntity):
    """The language the stories are told in, whatever Home Assistant's is.

    Not restored from its state: that shows Home Assistant's language before
    anything is picked, and restoring it would make that a pick. The pick is
    kept in the stories' own storage instead.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "story_language"
    _attr_unique_id = "xbloom_story_language"
    _attr_icon = "mdi:translate"
    _attr_options = LANGUAGES

    def __init__(self, entry) -> None:
        self._entry = entry

    @property
    def device_info(self):
        return _device_info(self._entry.entry_id)

    @property
    def current_option(self) -> str | None:
        runtime = self._entry.runtime_data.stories
        return runtime._language() if runtime else None

    async def async_select_option(self, option: str) -> None:
        if option in LANGUAGES and self._entry.runtime_data.stories is not None:
            await self._entry.runtime_data.stories.async_set_language(option)
            self.async_write_ha_state()
