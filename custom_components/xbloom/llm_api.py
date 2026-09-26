"""The integration's AI tools, as a Home Assistant LLM API.

Registered under the id `xbloom`, so Home Assistant's MCP server serves it at
`/api/mcp/xbloom` and conversation agents can select it. The API is rebuilt on
every request, so a tool's description always reflects the present.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from . import tool_xbloom
from .const import DOMAIN

API_ID = DOMAIN

API_PROMPT = (
    "Use the xbloom tool to control the xBloom Studio coffee machine. Its "
    "results are facts for you to put into words; a refused call says why."
)


class XBloomTool(llm.Tool):
    """The machine: recipes, brewing, and every module on its own."""

    name = "xbloom"

    def __init__(self) -> None:
        self.description = tool_xbloom.describe()
        self.parameters = tool_xbloom.parameters()

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ) -> JsonObjectType:
        # Home Assistant does not validate a tool's arguments before calling
        # it, so the schema is applied here: types coerced, unknown keys
        # refused, then what the action itself cannot run without.
        args: dict[str, Any] = self.parameters(tool_input.tool_args)
        action = args.pop("action")
        tool_xbloom.check_arguments(action, args)
        machine = tool_xbloom.Machine(hass, llm_context.context)
        return await tool_xbloom.ACTIONS[action].run(machine, args)


class XBloomAPI(llm.API):
    """The xBloom tools, for MCP clients and conversation agents."""

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=[XBloomTool()],
        )


def async_register(hass: HomeAssistant) -> Callable[[], None]:
    """Register the API; returns the call that removes it."""
    return llm.async_register_api(hass, XBloomAPI(hass=hass, id=API_ID, name="xBloom Studio"))
