"""The integration's AI tools, as a Home Assistant LLM API.

Registered under the id `xbloom`, so Home Assistant's MCP server serves it at
`/api/mcp/xbloom` and conversation agents can select it. The API is rebuilt on
every request, so a tool's description always reflects the present: the
`coffee_lab` tool appears only while Coffee Lab is switched on, and names the
bags there are now.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from . import tool_coffee_lab, tool_xbloom
from .coffee_lab.lab import CoffeeLab
from .const import DOMAIN

API_ID = DOMAIN

API_PROMPT = (
    "Use the xbloom tool to control the xBloom Studio coffee machine. Its "
    "results are facts for you to put into words; a refused call says why."
)


class XBloomTool(llm.Tool):
    """The machine: recipes, brewing, and every module on its own."""

    name = "xbloom"

    def __init__(self, lab: CoffeeLab | None = None, targets: tuple[str, ...] = ()) -> None:
        self._lab = lab
        self.description = tool_xbloom.describe(lab_on=lab is not None, targets=targets)
        self.parameters = tool_xbloom.parameters(lab_on=lab is not None)

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        # Home Assistant does not validate a tool's arguments before calling
        # it, so the schema is applied here: types coerced, unknown keys
        # refused, then what the action itself cannot run without.
        args: dict[str, Any] = self.parameters(tool_input.tool_args)
        action = args.pop("action")
        tool_xbloom.check_arguments(action, args)
        machine = tool_xbloom.Machine(hass, llm_context.context, self._lab)
        return await tool_xbloom.ACTIONS[action].run(machine, args)


class CoffeeLabTool(llm.Tool):
    """The bags of coffee, and what was brewed from them."""

    name = "coffee_lab"

    def __init__(self, lab: CoffeeLab, description: str) -> None:
        self._lab = lab
        self.description = description
        self.parameters = tool_coffee_lab.parameters()

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        args: dict[str, Any] = self.parameters(tool_input.tool_args)
        action = args.pop("action")
        return await tool_coffee_lab.run(self._lab, action, args)


class XBloomAPI(llm.API):
    """The xBloom tools, for MCP clients and conversation agents."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass=hass, id=API_ID, name="xBloom Studio")
        self._entry = entry

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        lab: CoffeeLab | None = self._entry.runtime_data.coffee_lab
        callbacks = self._entry.runtime_data.callbacks
        targets = tuple(sorted(callbacks.targets)) if callbacks is not None else ()
        tools: list[llm.Tool] = [XBloomTool(lab, targets)]
        if lab is not None:
            beans = await lab.store.async_list_beans()
            tools.append(CoffeeLabTool(lab, tool_coffee_lab.describe(beans)))
        return llm.APIInstance(
            api=self, api_prompt=API_PROMPT, llm_context=llm_context, tools=tools,
        )


def async_register(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    """Register the API; returns the call that removes it."""
    return llm.async_register_api(hass, XBloomAPI(hass, entry))
