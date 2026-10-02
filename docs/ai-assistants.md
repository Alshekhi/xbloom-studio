# AI assistants

The integration offers its controls as tools for AI assistants: **xbloom**, for
the machine — recipes, brewing, the modules, settings — and, while Coffee Lab
is on, **coffee_lab**, for bags, manual brews, history and stats. Each tool's
description names, per action, the arguments that action needs, and lists the
bags on hand. Results are facts for the assistant to put into words in its own
language; a refused call says why, in Home Assistant's language.

`prepare_brew` makes the machine ready for a recipe and its settings without
starting it, and answers once the machine has accepted it; calling it again
with new values adjusts what is prepared, and `brew_status` reports what is
prepared and how it differs from the saved recipe, and `cancel_preparation`
takes it back. `start_brew` then starts exactly what was prepared, preparing
first if nothing matching is ready.

`start_brew` waits for the machine to accept or refuse the brew before it
answers. With Coffee Lab on, it needs the bag the coffee comes from, or
`unattributed`. With `notify_target`, the caller is told how the brew ends by
[callback](events.md#callbacks).

**A conversation agent in Home Assistant:** in its settings, under **Control
Home Assistant**, choose **xBloom Studio**.

**Any MCP client** (Home Assistant 2026.8 or newer): add the **Model Context
Protocol Server** integration and select **xBloom Studio**. The tools are then
served at

```
https://<your Home Assistant>/api/mcp/xbloom
```

with a long-lived access token of an **administrator** in the `Authorization:
Bearer` header — Home Assistant serves any API other than Assist to
administrators only.
