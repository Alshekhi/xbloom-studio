"""Config flow for the xBloom Studio integration — BLE-only.

Setup is one screen:

  * Bluetooth-discovery card → one-click confirm with no fields.
  * Manual entry → pick from a dropdown of currently-discovered ``XBLOOM *``
    advertisers, or type the BLE name (printed in the iOS app under
    *Settings → Machine*) if HA's Bluetooth integration can't see the
    machine right now.

No serial number, no account, no MQTT broker. Recipes are added afterwards
via the integration's options flow ("Add recipe by share URL").
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import CONF_BLE_NAME, CONF_PRODUCT_ID, DOMAIN
from .vendor.xbloom.recipe_validate import (
    denom_to_ratio_str,
    guess_ratio,
    snap_ratio,
    validate_recipe,
)

_LOGGER = logging.getLogger(__name__)

_BLE_NAME_PREFIX = "XBLOOM "  # advertiser-name pattern; suffix is per-machine


def _serial_suffix(ble_name: str) -> str:
    """Return the suffix portion of an ``XBLOOM <suffix>`` advertiser name."""
    if not ble_name or not ble_name.startswith(_BLE_NAME_PREFIX):
        return ""
    return ble_name[len(_BLE_NAME_PREFIX):].strip()


class XBloomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Bluetooth-first setup. No MQTT, no account, no serial entry required."""

    VERSION = 3  # bumped from v2; Phase 9 dropped MQTT + status_source

    def __init__(self) -> None:
        self._discovered_ble_name: str | None = None

    # ------------------------------------------------------------------ #
    # Bluetooth auto-discovery entry                                      #
    # ------------------------------------------------------------------ #
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """HA spotted an ``XBLOOM <suffix>`` advertiser."""
        ble_name = (discovery_info.name or "").strip()
        suffix = _serial_suffix(ble_name)
        if not suffix:
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(f"xbloom-{suffix}")
        self._abort_if_unique_id_configured()

        self._discovered_ble_name = ble_name
        self.context["title_placeholders"] = {"name": ble_name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One-click confirm of a discovered machine."""
        ble_name = self._discovered_ble_name or ""
        if user_input is not None:
            return self._create_entry(ble_name=ble_name)

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"name": ble_name},
        )

    # ------------------------------------------------------------------ #
    # Manual user step                                                    #
    # ------------------------------------------------------------------ #
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick from discovery, or type the BLE name manually."""
        errors: dict[str, str] = {}
        discovered = await _gather_discovered_xbloom_names(self.hass)

        existing_ids = {e.unique_id for e in self._async_current_entries()}
        discovered = [
            n for n in discovered
            if f"xbloom-{_serial_suffix(n)}" not in existing_ids
        ]

        if user_input is not None:
            ble_name = (user_input.get(CONF_BLE_NAME) or "").strip()
            if not ble_name:
                errors[CONF_BLE_NAME] = "ble_name_required"
            elif not ble_name.startswith(_BLE_NAME_PREFIX) or not _serial_suffix(ble_name):
                errors[CONF_BLE_NAME] = "ble_name_invalid"
            else:
                suffix = _serial_suffix(ble_name)
                await self.async_set_unique_id(f"xbloom-{suffix}")
                self._abort_if_unique_id_configured()
                return self._create_entry(ble_name=ble_name)

        if discovered:
            ble_field = vol.In({n: n for n in discovered})
        else:
            ble_field = str

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_BLE_NAME): ble_field}),
            errors=errors,
            description_placeholders={"discovered_count": str(len(discovered))},
        )

    # ------------------------------------------------------------------ #
    def _create_entry(self, *, ble_name: str) -> FlowResult:
        suffix = _serial_suffix(ble_name)
        data: dict[str, Any] = {CONF_BLE_NAME: ble_name}
        if suffix:
            data[CONF_PRODUCT_ID] = suffix
        return self.async_create_entry(title=ble_name, data=data)

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "XBloomOptionsFlow":
        return XBloomOptionsFlow(config_entry)


async def _gather_discovered_xbloom_names(hass) -> list[str]:
    """BLE advertiser names matching ``XBLOOM ...`` HA can see right now."""
    try:
        infos = async_discovered_service_info(hass)
    except Exception as err:  # bluetooth integration may not be loaded
        _LOGGER.debug("Bluetooth discovery unavailable: %s", err)
        return []
    names: set[str] = set()
    for info in infos:
        name = (info.name or "").strip()
        if name.startswith(_BLE_NAME_PREFIX) and _serial_suffix(name):
            names.add(name)
    return sorted(names)


def _ratio_options() -> list[str]:
    """Discrete '1:N' options from 1:5 to 1:25 in 0.5 steps."""
    return [denom_to_ratio_str(5 + 0.5 * i) for i in range(41)]


# Per-cup dose ranges — UI-locked stepper bounds (match the xBloom app).
_CUP_DOSE_UI = {
    "xPod":          (15.0, 15.0, 0.5, 15.0),  # locked
    "Omni dripper":  (5.0, 18.0, 0.5, 18.0),
    "Other":         (5.0, 25.0, 0.5, 18.0),
    "Tea":           (1.0, 5.0, 0.5, 3.0),
}


# --------------------------------------------------------------------- #
# Options flow — manage the local recipe library.                       #
# --------------------------------------------------------------------- #
class XBloomOptionsFlow(config_entries.OptionsFlow):
    """Add or remove recipes after initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # HA 2025.x makes OptionsFlow.config_entry a framework-managed
        # read-only property. Don't assign it; the framework injects it.
        self._draft: dict | None = None
        self._delete_target: dict | None = None
        self._post_save: dict | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "create_recipe",
                "edit_recipe",
                "delete_recipe",
                "add_recipe",
                "done",
            ],
        )

    async def async_step_add_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Paste an xBloom share URL (or raw share id) to import the recipe."""
        errors: dict[str, str] = {}
        coordinator = self.config_entry.runtime_data.coordinator
        client = self.config_entry.runtime_data.client

        if user_input is not None:
            raw = (user_input.get("share_url_or_id") or "").strip()
            if not raw:
                errors["share_url_or_id"] = "required"
            else:
                try:
                    if raw.startswith("http"):
                        share_id = client.share_id_from_url(raw)
                    else:
                        share_id = raw
                    recipe = await client.get_recipe_by_share_id(share_id)
                    await coordinator.async_add_recipe(recipe)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("xbloom add_recipe: %s", err)
                    errors["share_url_or_id"] = "invalid_share"
                else:
                    return self.async_create_entry(
                        title="",
                        data={"_last_added": recipe.get("name")},
                    )

        return self.async_show_form(
            step_id="add_recipe",
            data_schema=vol.Schema({vol.Required("share_url_or_id"): str}),
            errors=errors,
        )

    # ------------------------------------------------------------------ #
    # Create flow — Phase 9 plan 04                                       #
    # ------------------------------------------------------------------ #
    async def async_step_create_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1 of create — pick name + cup type. Cup type gates dose range
        in the next step so the UI can lock dose to the cup's allowed values."""
        errors: dict[str, str] = {}
        # Draft may already be populated when coming from the edit flow.
        draft_name = (self._draft or {}).get("name", "")
        draft_cup = (self._draft or {}).get("cup_type_label", "Omni dripper")

        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            cup_label = user_input["cup_type"]
            if not name:
                errors["name"] = "name_required"
            if not errors:
                if self._draft is None:
                    # Fresh create — seed minimal draft.
                    self._draft = {}
                # Update name + cup; preserve any existing brew/pour data
                # so edit mode keeps the current values as defaults.
                self._draft["name"] = name
                self._draft["cup_type_label"] = cup_label
                return await self.async_step_create_recipe_brew()

        schema = vol.Schema({
            vol.Required("name", default=draft_name): str,
            vol.Required("cup_type", default=draft_cup): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["Omni dripper", "xPod", "Tea", "Other"],
                    mode="dropdown",
                )
            ),
        })
        return self.async_show_form(
            step_id="create_recipe",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_create_recipe_brew(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2 of create — brew params with cup-locked dose stepper."""
        errors: dict[str, str] = {}
        cup_label = self._draft.get("cup_type_label", "Omni dripper")
        dose_min, dose_max, dose_step, dose_default = _CUP_DOSE_UI.get(
            cup_label, _CUP_DOSE_UI["Other"]
        )

        if user_input is not None:
            self._draft.update({
                "dose_g": float(user_input["dose_g"]),
                "ratio": str(user_input["ratio"]),
                "grind_size": float(user_input["grind_size"]),
                "grinder_speed_rpm": int(user_input["grinder_speed_rpm"]),
                "pour_count": int(user_input["pour_count"]),
                "bypass_water_enabled": bool(
                    user_input.get("enable_bypass_water", False)
                ),
                "bypass_volume_ml": user_input.get("bypass_volume_ml"),
                "bypass_temp_c": user_input.get("bypass_temp_c"),
            })
            if self._draft["pour_count"] < 1:
                errors["pour_count"] = "pour_count_mismatch"
            if self._draft["bypass_water_enabled"]:
                if self._draft["bypass_volume_ml"] in (None, ""):
                    errors["bypass_volume_ml"] = "bypass_volume_required"
                if self._draft["bypass_temp_c"] in (None, ""):
                    errors["bypass_temp_c"] = "bypass_temp_required"
            if not errors:
                old_pours = self._draft.get("pours") or []
                old_pour_count = len(old_pours)
                new_pour_count = self._draft["pour_count"]
                if not old_pours or old_pour_count != new_pour_count:
                    # No pours yet or count changed — full recalculate.
                    self._draft["pours"] = self._auto_fill_pours(self._draft)
                else:
                    # Count unchanged — recalculate volumes from new ratio/dose
                    # but keep each pour's temperature, pattern, flow, pause, vibrate.
                    ratio_denom = float(self._draft["ratio"].split(":", 1)[1])
                    total_ml = round(float(self._draft["dose_g"]) * ratio_denom, 1)
                    per_volume = round(total_ml / new_pour_count, 1)
                    new_pours = [{**p, "volume_ml": per_volume} for p in old_pours]
                    drift = round(total_ml - sum(p["volume_ml"] for p in new_pours), 1)
                    if drift:
                        new_pours[-1]["volume_ml"] = round(
                            new_pours[-1]["volume_ml"] + drift, 1
                        )
                    self._draft["pours"] = new_pours
                return await self.async_step_create_recipe_pours()

        # Use draft values as defaults so edits pre-fill current recipe values.
        d = self._draft or {}
        bypass_enabled = d.get("bypass_water_enabled", False)
        schema_fields: dict = {
            vol.Required("dose_g", default=d.get("dose_g", dose_default)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=dose_min, max=dose_max, step=dose_step, mode="slider", unit_of_measurement="g")
            ),
            vol.Required("ratio", default=d.get("ratio", "1:16")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_ratio_options(), mode="dropdown",
                )
            ),
            vol.Required("grind_size", default=d.get("grind_size", 40)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=80, step=1, mode="slider")
            ),
            vol.Required("grinder_speed_rpm", default=d.get("grinder_speed_rpm", 90)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=60, max=120, step=10, mode="slider", unit_of_measurement="RPM")
            ),
            vol.Required("pour_count", default=d.get("pour_count", 3)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=9, step=1, mode="slider")
            ),
            vol.Required("enable_bypass_water", default=bypass_enabled): selector.BooleanSelector(),
        }
        if bypass_enabled:
            schema_fields[vol.Optional("bypass_volume_ml", default=d.get("bypass_volume_ml", vol.UNDEFINED))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=100, step=1, mode="slider", unit_of_measurement="ml")
            )
            schema_fields[vol.Optional("bypass_temp_c", default=d.get("bypass_temp_c", vol.UNDEFINED))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=20, max=98, step=1, mode="slider", unit_of_measurement="°C")
            )
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="create_recipe_brew",
            data_schema=schema,
            errors=errors,
            description_placeholders={"cup": cup_label},
        )

    def _auto_fill_pours(self, draft: dict) -> list[dict]:
        """xbloom-app heuristic — D-20 verbatim."""
        ratio_denom = float(draft["ratio"].split(":", 1)[1])
        total_ml = round(draft["dose_g"] * ratio_denom, 1)
        n = max(1, int(draft["pour_count"]))
        per_volume = round(total_ml / n, 1)
        pours: list[dict] = []
        for i in range(n):
            # Temperature: start 92°C, descend 1°C per subsequent pour.
            temp = max(20, 92 - i * 1)
            pours.append({
                "id": i,
                "recipe_id": 0,
                "name": "",
                "volume_ml": per_volume,
                "temperature_c": float(temp),
                "pattern": 3,            # spiral
                "flow_rate": 3.0,
                "pause_s": 0,
                "agitate_before": 2,     # off (2 per client.py convention)
                "agitate_after": 2,
            })
        # Adjust last pour for rounding drift so volumes sum to total exactly.
        drift = round(total_ml - sum(p["volume_ml"] for p in pours), 1)
        if drift:
            pours[-1]["volume_ml"] = round(pours[-1]["volume_ml"] + drift, 1)
        return pours

    async def async_step_create_recipe_pours(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Tweak the auto-filled pours, validate, save (D-21)."""
        assert self._draft is not None, "Draft missing — restart create flow"
        errors: dict[str, str] = {}
        pours_now = self._draft["pours"]

        if user_input is not None:
            new_pours: list[dict] = []
            for i in range(len(pours_now)):
                new_pours.append({
                    **pours_now[i],
                    "volume_ml": float(user_input[f"pour_{i}_volume_ml"]),
                    "temperature_c": float(user_input[f"pour_{i}_temperature_c"]),
                    "pattern": {"centered": 1, "circular": 2, "spiral": 3}[
                        user_input[f"pour_{i}_pattern"]
                    ],
                    "flow_rate": float(user_input[f"pour_{i}_flow_rate"]),
                    "pause_s": int(user_input[f"pour_{i}_pause_s"]),
                    "agitate_before": 1 if user_input.get(f"pour_{i}_vib_before") else 2,
                    "agitate_after": 1 if user_input.get(f"pour_{i}_vib_after") else 2,
                })
            candidate = self._build_recipe(self._draft, new_pours)
            errors = self._map_errors_to_form(validate_recipe(candidate))
            if not errors:
                coordinator = self.config_entry.runtime_data.coordinator
                if self._draft.get("edit_existing"):
                    candidate["id"] = self._draft["id"]   # preserve original tableId (D-61)
                    await coordinator.async_replace_recipe(candidate)
                    result_key = "_last_edited"
                else:
                    await coordinator.async_add_recipe(candidate)
                    result_key = "_last_created"
                saved_name = candidate["name"]
                self._draft = None
                # D-52: optional write-to-slot sub-step. Stash saved name so
                # async_step_write_to_slot can read it.
                self._post_save = {"action": result_key, "name": saved_name}
                return await self.async_step_write_to_slot()
            self._draft["pours"] = new_pours

        fields: dict = {}
        pattern_label = {1: "centered", 2: "circular", 3: "spiral"}
        for i, p in enumerate(self._draft["pours"]):
            fields[vol.Required(f"pour_{i}_volume_ml", default=p["volume_ml"])] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=240, step=1, mode="slider", unit_of_measurement="ml")
                )
            )
            fields[vol.Required(f"pour_{i}_temperature_c", default=p["temperature_c"])] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=20, max=98, step=1, mode="slider", unit_of_measurement="°C")
                )
            )
            fields[vol.Required(f"pour_{i}_pattern", default=pattern_label[p["pattern"]])] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["centered", "circular", "spiral"], mode="dropdown"
                    )
                )
            )
            fields[vol.Required(f"pour_{i}_flow_rate", default=p["flow_rate"])] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=3.0, max=3.5, step=0.1, mode="slider")
                )
            )
            fields[vol.Required(f"pour_{i}_pause_s", default=p["pause_s"])] = (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=59, step=1, mode="slider", unit_of_measurement="s")
                )
            )
            fields[vol.Required(
                f"pour_{i}_vib_before",
                default=(p["agitate_before"] == 1),
            )] = selector.BooleanSelector()
            fields[vol.Required(
                f"pour_{i}_vib_after",
                default=(p["agitate_after"] == 1),
            )] = selector.BooleanSelector()
        ratio_denom = float(self._draft["ratio"].split(":", 1)[1])
        total_ml = round(float(self._draft["dose_g"]) * ratio_denom, 1)
        n = max(1, len(self._draft["pours"]))
        per_pour_ml = round(total_ml / n, 1)
        # Compute the current running total so the description can show it
        # when the user has tweaked values (and especially after a mismatch error).
        current_total = round(
            sum(float(p.get("volume_ml", 0) or 0) for p in self._draft["pours"]
                if isinstance(p, dict)),
            1,
        )
        return self.async_show_form(
            step_id="create_recipe_pours",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={
                "total_ml": str(total_ml),
                "dose": str(self._draft["dose_g"]),
                "ratio": self._draft["ratio"],
                "per_pour_ml": str(per_pour_ml),
                "current_total_ml": str(current_total),
            },
        )

    def _build_recipe(self, draft: dict, pours: list[dict]) -> dict:
        """Assemble the final recipe dict to hand to the validator + store."""
        cup_label = draft["cup_type_label"]
        cup_int = {"xPod": 1, "Omni dripper": 2, "Other": 3, "Tea": 4}[cup_label]
        ratio_denom = float(draft["ratio"].split(":", 1)[1])
        recipe: dict = {
            "id": f"local-{uuid.uuid4()}",
            "name": draft["name"],
            "dose_g": draft["dose_g"],
            "ratio": draft["ratio"],
            "water_ratio": round(draft["dose_g"] * ratio_denom, 1),
            "grind_size": draft["grind_size"],
            "grinder_size": draft["grind_size"],
            "grinder_size_enabled": 1,
            "grinder_speed_rpm": draft["grinder_speed_rpm"],
            "rpm": draft["grinder_speed_rpm"],
            "pour_count": int(draft["pour_count"]),
            "cup_type": cup_int,
            "cup_type_name": cup_label,
            "bypass_water_enabled": 1 if draft["bypass_water_enabled"] else 2,
            "pours": pours,
            "meta": {"created_locally": True},
        }
        if draft["bypass_water_enabled"]:
            if draft.get("bypass_volume_ml") not in (None, ""):
                recipe["bypass_volume_ml"] = float(draft["bypass_volume_ml"])
            if draft.get("bypass_temp_c") not in (None, ""):
                recipe["bypass_temp_c"] = float(draft["bypass_temp_c"])
        return recipe

    def _map_errors_to_form(self, errors_map: dict[str, str]) -> dict[str, str]:
        """Translate validator field paths into form keys for the pours step.

        Pour-level paths like 'pours.0.temperature_c' become 'pour_0_temperature_c'.
        Top-level 'pours' (sum mismatch) attaches to 'base'.
        """
        out: dict[str, str] = {}
        for path, key in errors_map.items():
            if path.startswith("pours.") and path.count(".") == 2:
                _, idx, field = path.split(".")
                out[f"pour_{idx}_{field}"] = key
            elif path == "pours":
                out["base"] = key
            else:
                out[path] = key
        return out

    # ------------------------------------------------------------------ #
    # Edit flow — Phase 9 plan 05                                         #
    # ------------------------------------------------------------------ #
    async def async_step_edit_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick a recipe to edit, then re-use the create_recipe_pours UI."""
        coordinator = self.config_entry.runtime_data.coordinator
        recipes: list[dict] = await coordinator.store.async_load()
        if not recipes:
            return self.async_abort(reason="no_recipes")

        id_to_label: dict[str, str] = {}
        seen: dict[str, int] = {}
        for r in recipes:
            rid = r.get("id")
            if not rid:
                continue
            base = r.get("name") or rid
            n = seen.get(base, 0) + 1
            seen[base] = n
            id_to_label[rid] = base if n == 1 else f"{base} ({n})"

        if user_input is not None:
            table_id = user_input["recipe_id"]
            recipe = next((r for r in recipes if r.get("id") == table_id), None)
            if recipe is None:
                return self.async_abort(reason="no_recipes")
            self._draft = self._draft_from_recipe(recipe)
            # Route through all three steps so name/cup/brew are editable too.
            return await self.async_step_create_recipe()

        return self.async_show_form(
            step_id="edit_recipe",
            data_schema=vol.Schema({vol.Required("recipe_id"): vol.In(id_to_label)}),
        )

    def _draft_from_recipe(self, recipe: dict) -> dict:
        """Inverse of `_build_recipe` — produce the draft shape used by the
        pours step, pre-filled from a stored recipe (D-40)."""
        cup_int = int(recipe.get("cup_type", 3))
        cup_label = {1: "xPod", 2: "Omni dripper", 3: "Other", 4: "Tea"}.get(cup_int, "Other")
        return {
            "id": recipe.get("id"),                  # carries through; triggers replace path
            "name": recipe.get("name", ""),
            "dose_g": float(recipe.get("dose_g", 18)),
            # Snap rather than preserve: this value feeds a fixed dropdown, so
            # it must land on a real option. (normalize_recipe deliberately
            # keeps a malformed ratio instead — see recipe_validate.)
            "ratio": snap_ratio(recipe.get("ratio") or guess_ratio(recipe)),
            "grind_size": float(recipe.get("grind_size", recipe.get("grinder_size", 40))),
            "grinder_speed_rpm": int(recipe.get("grinder_speed_rpm", recipe.get("rpm", 90))),
            "pour_count": int(recipe.get("pour_count", len(recipe.get("pours") or []))),
            "cup_type_label": cup_label,
            "bypass_water_enabled": int(recipe.get("bypass_water_enabled", 2)) == 1,
            "bypass_volume_ml": recipe.get("bypass_volume_ml"),
            "bypass_temp_c": recipe.get("bypass_temp_c"),
            "pours": [
                {
                    "id": p.get("id", i),
                    "recipe_id": p.get("recipe_id", 0),
                    "name": p.get("name", ""),
                    "volume_ml": float(p.get("volume_ml", 0)),
                    "temperature_c": float(p.get("temperature_c", 92)),
                    "pattern": int(p.get("pattern", 3)),
                    "flow_rate": float(p.get("flow_rate", 3.0)),
                    "pause_s": int(p.get("pause_s", 0)),
                    "agitate_before": int(p.get("agitate_before", 2)),
                    "agitate_after": int(p.get("agitate_after", 2)),
                }
                for i, p in enumerate(recipe.get("pours") or [])
            ],
            "edit_existing": True,                   # marker; create_recipe_pours uses this
        }

    # ------------------------------------------------------------------ #
    # Delete flow — Phase 9 plan 05                                       #
    # ------------------------------------------------------------------ #
    async def async_step_delete_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick a recipe to delete (id-keyed for D-61 rename safety)."""
        coordinator = self.config_entry.runtime_data.coordinator
        recipes: list[dict] = await coordinator.store.async_load()
        if not recipes:
            return self.async_abort(reason="no_recipes")

        id_to_label = {r["id"]: r.get("name", r["id"]) for r in recipes if r.get("id")}

        if user_input is not None:
            self._delete_target = {
                "id": user_input["recipe_id"],
                "name": id_to_label.get(user_input["recipe_id"], user_input["recipe_id"]),
            }
            return await self.async_step_delete_recipe_confirm()

        return self.async_show_form(
            step_id="delete_recipe",
            data_schema=vol.Schema({vol.Required("recipe_id"): vol.In(id_to_label)}),
        )

    async def async_step_delete_recipe_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Two-step confirm before calling async_delete_recipe (D-41)."""
        assert self._delete_target is not None
        if user_input is not None:
            if user_input.get("confirm"):
                coordinator = self.config_entry.runtime_data.coordinator
                deleted = await coordinator.async_delete_recipe(self._delete_target["id"])
                name = self._delete_target["name"]
                self._delete_target = None
                if deleted:
                    return self.async_create_entry(title="", data={"_last_deleted": name})
                return self.async_abort(reason="no_recipes")
            # User unchecked — abort cleanly
            self._delete_target = None
            return self.async_create_entry(title="", data={"_cancelled": True})

        return self.async_show_form(
            step_id="delete_recipe_confirm",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): selector.BooleanSelector(),
            }),
            description_placeholders={"recipe_name": self._delete_target["name"]},
        )

    # ------------------------------------------------------------------ #
    # Optional Write-to-slot sub-step (D-52)                              #
    # ------------------------------------------------------------------ #
    async def async_step_write_to_slot(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """After a successful create/edit, optionally push to slot A/B/C."""
        assert self._post_save is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            slot = user_input.get("slot")
            if slot in (None, "skip", ""):
                meta = self._post_save
                self._post_save = None
                return self.async_create_entry(
                    title="", data={meta["action"]: meta["name"]}
                )
            try:
                await self.hass.services.async_call(
                    "xbloom",
                    "write_slot",
                    {"slot": slot, "recipe_name": self._post_save["name"]},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("xbloom write_slot failed: %s", err)
                errors["slot"] = "slot_write_failed"
            else:
                meta = self._post_save
                self._post_save = None
                return self.async_create_entry(
                    title="",
                    data={
                        meta["action"]: meta["name"],
                        "_slot_written": slot,
                    },
                )

        return self.async_show_form(
            step_id="write_to_slot",
            data_schema=vol.Schema({
                vol.Optional("slot", default="skip"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["skip", "A", "B", "C"],
                        mode="dropdown",
                    )
                ),
            }),
            errors=errors,
            description_placeholders={"recipe_name": self._post_save["name"]},
        )

    async def async_step_done(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_create_entry(title="", data={})
