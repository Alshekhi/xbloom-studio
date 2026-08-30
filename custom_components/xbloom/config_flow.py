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
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BLE_NAME,
    CONF_CLOUD,
    CONF_ENABLE_FLASHING,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_MEMBER_ID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_REMEMBER,
    CONF_CLOUD_TOKEN,
    CONF_IDLE_TIMEOUT,
    CONF_PRODUCT_ID,
    DOMAIN,
)
from xbloom.mode_listener import IDLE_TIMEOUT_SEC
from xbloom import recipe_build, spec
from xbloom.recipe_validate import (
    denom_to_ratio_str,
    guess_ratio,
    snap_ratio,
    validate_recipe,
)


def _num_selector(rng: spec.NumRange, *, mode: str = "slider") -> "selector.NumberSelector":
    """Declarative bridge: build an HA NumberSelector from a spec NumRange.

    This is the seam the adapter talks to the core through — the UI asks the
    spec for a field's bounds and renders a control, instead of hardcoding
    min/max/step a second time. `unit_of_measurement` is omitted when the
    field has no unit, matching how these selectors were written by hand.
    """
    cfg: dict = {"min": rng.min, "max": rng.max, "step": rng.step, "mode": mode}
    if rng.unit:
        cfg["unit_of_measurement"] = rng.unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**cfg))

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
    # Reauth — the stored session token is no longer valid and cannot be  #
    # refreshed (password not remembered, or the credentials changed).    #
    # ------------------------------------------------------------------ #
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Entry point when HA requests re-authentication for this entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt for the password again and mint a fresh session token."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        from xbloom.cloud import XBloomCloudClient, language_type_for
        from xbloom.exceptions import XBloomAPIError

        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        existing = (entry.data.get(CONF_CLOUD) or {}) if entry else {}
        email = existing.get(CONF_CLOUD_EMAIL, "")
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input.get("password") or ""
            remember = bool(user_input.get("remember", True))
            if not password:
                errors["base"] = "credentials_required"
            else:
                client = XBloomCloudClient(
                    async_get_clientsession(self.hass),
                    language_type=language_type_for(self.hass.config.language),
                )
                try:
                    creds = await client.login(email, password)
                except XBloomAPIError as err:
                    _LOGGER.warning("xbloom cloud reauth failed: %s", err)
                    errors["base"] = "cloud_login_failed"
                else:
                    new_cloud = {
                        CONF_CLOUD_EMAIL: email,
                        CONF_CLOUD_MEMBER_ID: creds["memberId"],
                        CONF_CLOUD_TOKEN: creds["token"],
                        CONF_CLOUD_REMEMBER: remember,
                    }
                    if remember:
                        new_cloud[CONF_CLOUD_PASSWORD] = password
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_CLOUD: new_cloud}
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type="password")
                ),
                vol.Required(
                    "remember",
                    default=bool(existing.get(CONF_CLOUD_REMEMBER, True)),
                ): selector.BooleanSelector(),
            }),
            errors=errors,
            description_placeholders={"email": email},
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
    """Discrete '1:N' options over the ratio grid, derived from the spec."""
    r = spec.RATIO_DENOM
    count = int(round((r.max - r.min) / r.step)) + 1
    return [denom_to_ratio_str(r.min + r.step * i) for i in range(count)]


# Per-cup dose stepper bounds (min, max, step, default), keyed by label —
# derived from the spec so the UI and the validator share one dose table.
_CUP_DOSE_UI = {
    c.label: (c.dose.min, c.dose.max, c.dose.step, c.dose.default)
    for c in spec.CUP_TYPES
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
        self._pending_login: dict | None = None
        self._reconcile_count: int = 0

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        coordinator = self.config_entry.runtime_data.coordinator
        # The cloud entry is contextual: offer login when logged out, and
        # logout when logged in. Everything else (recipe CRUD) is identical —
        # the coordinator routes it to the cloud or local storage transparently.
        cloud_option = "cloud_logout" if coordinator.cloud_logged_in else "cloud_login"
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "create_recipe",
                "edit_recipe",
                "delete_recipe",
                "add_recipe",
                cloud_option,
                "connection",
                "firmware_flashing",
                "done",
            ],
        )

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Set the idle auto-disconnect window for a Connect (live) session.

        HA holds the BLE link server-side, so — unlike the phone app, which the
        OS disconnects when it backgrounds — a session that no one closes would
        keep the machine from the iOS app indefinitely. This window is HA's
        substitute: after this many seconds of silence the session auto-ends and
        the machine returns to the app.
        """
        entry = self.config_entry
        current = int(entry.data.get(CONF_IDLE_TIMEOUT, IDLE_TIMEOUT_SEC))
        if user_input is not None:
            seconds = int(user_input["idle_timeout_s"])
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_IDLE_TIMEOUT: seconds}
            )
            # Reload so the Connect switch rebuilds its listener with the new
            # window.
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry.entry_id)
            )
            return self.async_create_entry(title="", data={"_idle_timeout": seconds})

        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema({
                vol.Required(
                    "idle_timeout_s", default=current,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=60, max=1800, step=30, mode="slider",
                        unit_of_measurement="s",
                    )
                ),
            }),
        )

    async def async_step_firmware_flashing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Arm/disarm the firmware Install button (off by default)."""
        entry = self.config_entry
        current = bool(entry.data.get(CONF_ENABLE_FLASHING))
        if user_input is not None:
            enabled = bool(user_input.get("enable"))
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_ENABLE_FLASHING: enabled}
            )
            # Reload so the Firmware entity's Install button reflects the change.
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry.entry_id)
            )
            return self.async_create_entry(title="", data={"_flashing": enabled})

        return self.async_show_form(
            step_id="firmware_flashing",
            data_schema=vol.Schema({
                vol.Required("enable", default=current): selector.BooleanSelector(),
            }),
        )

    # ------------------------------------------------------------------ #
    # Cloud account — login / first-login reconciliation / logout        #
    # ------------------------------------------------------------------ #
    async def async_step_cloud_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Log in to the xBloom cloud with email + password."""
        from xbloom.exceptions import XBloomAPIError

        errors: dict[str, str] = {}
        coordinator = self.config_entry.runtime_data.coordinator

        if user_input is not None:
            email = (user_input.get("email") or "").strip()
            password = user_input.get("password") or ""
            remember = bool(user_input.get("remember", True))
            if not email or not password:
                errors["base"] = "credentials_required"
            else:
                try:
                    creds = await coordinator.async_validate_login(email, password)
                except XBloomAPIError as err:
                    _LOGGER.warning("xbloom cloud login failed: %s", err)
                    errors["base"] = "cloud_login_failed"
                else:
                    self._pending_login = {
                        "email": email,
                        "password": password,
                        "member_id": creds["memberId"],
                        "token": creds["token"],
                        "remember": remember,
                    }
                    # Only prompt about recipes that are genuinely local (not
                    # already in the cloud). A pure cached mirror from a previous
                    # session needs no reconciliation — switch straight over.
                    local_only = await coordinator.async_local_only_recipes(
                        creds["memberId"], creds["token"]
                    )
                    if local_only:
                        self._reconcile_count = len(local_only)
                        return await self.async_step_cloud_reconcile()
                    await coordinator.async_finalize_login(
                        **self._pending_login, upload_local=False
                    )
                    self._pending_login = None
                    return self.async_create_entry(title="", data={"_cloud": "login"})

        return self.async_show_form(
            step_id="cloud_login",
            data_schema=vol.Schema({
                vol.Required("email"): selector.TextSelector(
                    selector.TextSelectorConfig(type="email")
                ),
                vol.Required("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type="password")
                ),
                vol.Required("remember", default=True): selector.BooleanSelector(),
            }),
            errors=errors,
        )

    async def async_step_cloud_reconcile(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First login with genuinely-local recipes — upload or discard them."""
        assert self._pending_login is not None
        return self.async_show_menu(
            step_id="cloud_reconcile",
            menu_options=["cloud_upload", "cloud_replace"],
            description_placeholders={"count": str(self._reconcile_count)},
        )

    async def async_step_cloud_upload(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconcile choice: upload local recipes to the cloud, then switch."""
        return await self._finalize_cloud_login(upload_local=True)

    async def async_step_cloud_replace(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconcile choice: discard local recipes, cloud becomes authoritative."""
        return await self._finalize_cloud_login(upload_local=False)

    async def _finalize_cloud_login(self, *, upload_local: bool) -> FlowResult:
        assert self._pending_login is not None
        coordinator = self.config_entry.runtime_data.coordinator
        await coordinator.async_finalize_login(
            **self._pending_login, upload_local=upload_local
        )
        self._pending_login = None
        return self.async_create_entry(
            title="", data={"_cloud": "upload" if upload_local else "replace"}
        )

    async def async_step_cloud_logout(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm, then log out of the cloud and revert to the local library."""
        coordinator = self.config_entry.runtime_data.coordinator
        if user_input is not None:
            if user_input.get("confirm"):
                await coordinator.async_cloud_logout()
                return self.async_create_entry(title="", data={"_cloud": "logout"})
            return self.async_create_entry(title="", data={"_cancelled": True})

        return self.async_show_form(
            step_id="cloud_logout",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): selector.BooleanSelector(),
            }),
            description_placeholders={"email": coordinator.cloud_email or ""},
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
        draft_cup = (self._draft or {}).get("cup_type_label", spec.DEFAULT_CUP_LABEL)

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
                    # Labels from the spec; the display order (Omni first) is a
                    # UI choice, expressed as cup api ids.
                    options=[spec.CUP_API_TO_LABEL[i] for i in (2, 1, 4, 3)],
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
        cup_label = self._draft.get("cup_type_label", spec.DEFAULT_CUP_LABEL)
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
                    # Count unchanged — move the existing pours onto the new
                    # total without levelling the user's distribution.
                    ratio_denom = float(self._draft["ratio"].split(":", 1)[1])
                    total_ml = round(float(self._draft["dose_g"]) * ratio_denom, 1)
                    self._draft["pours"] = recipe_build.redistribute_pours(
                        old_pours, total_ml=total_ml, pour_count=new_pour_count,
                    )
                return await self.async_step_create_recipe_pours()

        # Use draft values as defaults so edits pre-fill current recipe values.
        d = self._draft or {}
        bypass_enabled = d.get("bypass_water_enabled", False)
        dose_rng = spec.NumRange(dose_min, dose_max, dose_step, dose_default, "g")
        schema_fields: dict = {
            vol.Required("dose_g", default=d.get("dose_g", dose_default)): _num_selector(dose_rng),
            vol.Required("ratio", default=d.get("ratio", "1:16")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_ratio_options(), mode="dropdown",
                )
            ),
            vol.Required("grind_size", default=d.get("grind_size", spec.field("grind_size").default)): _num_selector(spec.field("grind_size")),
            vol.Required("grinder_speed_rpm", default=d.get("grinder_speed_rpm", spec.field("grinder_speed_rpm").default)): _num_selector(spec.field("grinder_speed_rpm")),
            vol.Required("pour_count", default=d.get("pour_count", spec.field("pour_count").default)): _num_selector(spec.field("pour_count")),
            vol.Required("enable_bypass_water", default=bypass_enabled): selector.BooleanSelector(),
        }
        if bypass_enabled:
            schema_fields[vol.Optional("bypass_volume_ml", default=d.get("bypass_volume_ml", vol.UNDEFINED))] = _num_selector(spec.field("bypass_volume_ml"))
            schema_fields[vol.Optional("bypass_temp_c", default=d.get("bypass_temp_c", vol.UNDEFINED))] = _num_selector(spec.field("bypass_temp_c"))
        schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="create_recipe_brew",
            data_schema=schema,
            errors=errors,
            description_placeholders={"cup": cup_label},
        )

    def _auto_fill_pours(self, draft: dict) -> list[dict]:
        """xbloom-app heuristic — D-20 verbatim."""
        return recipe_build.auto_fill_pours(draft)

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
                    "pattern": spec.PATTERN_NAME_TO_API[
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
        for i, p in enumerate(self._draft["pours"]):
            fields[vol.Required(f"pour_{i}_volume_ml", default=p["volume_ml"])] = (
                _num_selector(spec.field("pour_volume_ml"))
            )
            fields[vol.Required(f"pour_{i}_temperature_c", default=p["temperature_c"])] = (
                _num_selector(spec.field("pour_temperature_c"))
            )
            fields[vol.Required(f"pour_{i}_pattern", default=spec.PATTERN_API_TO_NAME[p["pattern"]])] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(spec.PATTERN_NAMES), mode="dropdown"
                    )
                )
            )
            fields[vol.Required(f"pour_{i}_flow_rate", default=p["flow_rate"])] = (
                _num_selector(spec.field("pour_flow_rate"))
            )
            fields[vol.Required(f"pour_{i}_pause_s", default=p["pause_s"])] = (
                _num_selector(spec.field("pour_pause_s"))
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
        return recipe_build.assemble(draft, pours)

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
    # Recipe picker labels — shared by the edit and delete steps.         #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _recipe_id_labels(recipes: list[dict]) -> dict[Any, str]:
        """Build the id → label map used by both the edit and delete pickers.

        Two recipes can carry the same name — most often a downloaded (shared)
        recipe sitting next to your own copy of it. A bare name is ambiguous,
        and with a screen reader two identical option labels are impossible to
        tell apart. So we make every label distinct and audible:

        * shared/downloaded recipes get a trailing ``(shared)`` tag, and
        * any labels that are *still* identical get a numeric ``(n)`` suffix.

        Both pickers go through here so they can never drift apart again (the
        old delete step listed duplicates with identical labels — D-?? ).
        """
        labels: dict[Any, str] = {}
        seen: dict[str, int] = {}
        for r in recipes:
            rid = r.get("id")
            if not rid:
                continue
            base = str(r.get("name") or rid)
            if r.get("shared"):
                base = f"{base} (shared)"
            n = seen.get(base, 0) + 1
            seen[base] = n
            labels[rid] = base if n == 1 else f"{base} ({n})"
        return labels

    # ------------------------------------------------------------------ #
    # Edit flow — Phase 9 plan 05                                         #
    # ------------------------------------------------------------------ #
    async def async_step_edit_recipe(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick a recipe to edit, then re-use the create_recipe_pours UI."""
        coordinator = self.config_entry.runtime_data.coordinator
        # Pull the latest list on entry so cloud-side edits (e.g. from the phone)
        # are reflected — event-driven, not waiting on the background poll.
        await coordinator.async_refresh()
        recipes: list[dict] = list(coordinator.data or [])
        if not recipes:
            return self.async_abort(reason="no_recipes")

        id_to_label = self._recipe_id_labels(recipes)

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
        cup_label = spec.CUP_API_TO_LABEL.get(cup_int, "Other")
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
        # Pull the latest list on entry (see edit_recipe) so the dropdown is fresh.
        await coordinator.async_refresh()
        recipes: list[dict] = list(coordinator.data or [])
        if not recipes:
            return self.async_abort(reason="no_recipes")

        id_to_label = self._recipe_id_labels(recipes)

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
