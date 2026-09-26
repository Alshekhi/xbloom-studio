"""Coffee Lab's services, registered only while it is switched on.

Each is one of Coffee Lab's shared actions, so a dashboard script, an
automation and the AI tool all apply the same rules. A service asked for a
response returns the same facts the tool does.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse

from ..const import DOMAIN
from ..tool_common import refuse
from . import actions
from .lab import CoffeeLab
from .models import STATUSES

_BAG = {vol.Exclusive("bean", "bag"): str, vol.Exclusive("bean_id", "bag"): str}
_GRAMS = vol.All(vol.Coerce(float), vol.Range(min=0))
_DETAILS = {
    vol.Optional("bag_size_g"): _GRAMS,
    vol.Optional("status"): vol.In(list(STATUSES)),
    **{vol.Optional(key): str for key in actions.DESCRIPTIVE},
}

# name: (action, schema)
SERVICES: dict[str, tuple[Callable[..., Any], vol.Schema]] = {
    "set_active_bean": (actions.set_active_bean, vol.Schema(_BAG)),
    "consume": (actions.consume, vol.Schema({
        **_BAG, vol.Required("grams"): _GRAMS, vol.Optional("brewer"): str,
    })),
    "start_tracking": (actions.start_tracking, vol.Schema({
        **_BAG, vol.Required("grams"): _GRAMS,
    })),
    "finish_bag": (actions.finish_bag, vol.Schema(_BAG)),
    "add_bean": (actions.add_bean, vol.Schema({
        vol.Required("name"): str, vol.Optional("remaining_g"): _GRAMS, **_DETAILS,
    })),
    "update_bean": (actions.update_bean, vol.Schema({
        **_BAG, vol.Optional("new_name"): str, **_DETAILS,
    })),
}


def async_register_lab_services(hass: HomeAssistant, lab: CoffeeLab) -> Callable[[], None]:
    """Register the services; returns the call that removes them."""

    def _handler(action: Callable[..., Any]) -> Callable[[ServiceCall], Any]:
        async def handle(call: ServiceCall) -> ServiceResponse:
            args = dict(call.data)
            # Every service but add_bean names a bag; the schema can say "not
            # both" but not "one of".
            if action is not actions.add_bean and not (args.get("bean") or args.get("bean_id")):
                raise refuse("missing_arguments", action=call.service, arguments="bean or bean_id")
            facts = await action(lab, args)
            return facts if call.return_response else None

        return handle

    for name, (action, schema) in SERVICES.items():
        hass.services.async_register(
            DOMAIN, name, _handler(action), schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    def unregister() -> None:
        for name in SERVICES:
            hass.services.async_remove(DOMAIN, name)

    return unregister
