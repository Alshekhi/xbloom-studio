"""Repair flows: replacing an edited blueprint with the one an update brought."""
from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .blueprint_install import async_replace_blueprint


class BlueprintOutdatedFlow(RepairsFlow):
    """Ask before putting the bundled blueprint over one edited by hand."""

    def __init__(self, path: str) -> None:
        self._path = path

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            await async_replace_blueprint(self.hass, self._path)
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm", description_placeholders={"path": self._path},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None,
) -> RepairsFlow:
    return BlueprintOutdatedFlow((data or {})["path"])
