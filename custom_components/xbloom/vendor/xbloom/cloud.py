"""XBloomCloudClient — authenticated client for the xBloom cloud (client-api).

Handles email/password login, recipe list/create/update/delete, and a
firmware-version check against ``client-api.xbloom.com``. This is the optional
cloud layer: when the user logs in, the cloud becomes the single source of
truth for recipes; when they don't, the integration stays fully local
(``storage.py``) and BLE-only.

Auth model — confirmed against the shipping ``denull0/xbloom-agent`` MCP server,
which does the same CRUD against the same backend:

  * Login (``tMemberLogin.thtml``) posts **plain** JSON and returns
    ``{token, member.tableId}``. We persist ``memberId`` + ``token`` (and, for
    seamless re-login on expiry, the account email + password live in the
    config entry).
  * User recipe endpoints (``tu*.tuhtml``) **RSA-encrypt the whole JSON body**:
    ``json → 117-byte chunks → RSA/PKCS#1 v1.5 with the baked-in public key →
    concat → base64``, posted as a bare JSON string body. Credentials
    (``memberId`` + ``token``) travel *inside* the encrypted body — there is no
    ``appid``/``nonce``/``sign`` header scheme on this host (that belongs to the
    separate ``api-iot.xbloom.com`` IoT backend).
  * On error code ``10001`` (token expired) the caller re-logs-in.

This host is SSL-pinned in the mobile apps, so the request shapes here come
from static analysis of the iOS binary cross-checked against the working MCP —
see ``discovery/cloud-api-spec.md`` for provenance.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .client import _parse_recipe
from .exceptions import XBloomAPIError
from .models import Recipe

log = logging.getLogger("xbloom.cloud")

API_BASE = "https://client-api.xbloom.com"

# Sent on every client-api request (confirmed from the MCP). The Referer/UA
# mimic the share-h5 web client the endpoint expects.
_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://share-h5.xbloom.com/",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
}

# languageType controls the language of server-returned messages (e.g. error
# text — it has no effect on recipe data). Confirmed from the Android
# LanguageKey/LanguageType constants, cross-checked against the iOS enum.
LANGUAGE_TYPES = {
    "en": 0, "fr": 1, "de": 2,
    "zh-hans": 3, "zh-cn": 3,
    "zh-hant": 4, "zh-tw": 4, "zh-hk": 4,
    "ko": 5, "ja": 6, "ar": 7,
}
DEFAULT_LANGUAGE_TYPE = 0  # English


def language_type_for(code: str | None) -> int:
    """Map a language code (e.g. a Home Assistant locale, BCP-47) to xBloom's
    ``languageType`` int. Falls back to English for anything unrecognised.

    Handles region subtags (``en-US`` → ``en``) and both ``-``/``_`` separators.
    """
    if not code:
        return DEFAULT_LANGUAGE_TYPE
    norm = code.strip().lower().replace("_", "-")
    if norm in LANGUAGE_TYPES:
        return LANGUAGE_TYPES[norm]
    primary = norm.split("-", 1)[0]
    return LANGUAGE_TYPES.get(primary, DEFAULT_LANGUAGE_TYPE)


# The base "envelope" every client-api body carries. languageType is added
# per-client (from the integration layer's locale) via ``_envelope``.
_BASE_ENVELOPE = {
    "interfaceVersion": 20240918,
    "skey": "testskey",
    "clientType": 2,
    "phoneType": "Android",
}

# RSA public key baked into the xBloom clients (1024-bit). Bodies of tu* calls
# are encrypted with it. Verbatim from denull0/xbloom-agent (confirmed working).
_RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC4LF40GZ72SdhMyl765K/i4nY5"
    "CPcHz2Q1IKWKZ9S79xmK7G8pUhbVf4EZLvnNF1+9IvOFQUKV5Z7ZNNviqSpnql9"
    "tAT+8+J/He0R7pcirvVSxgdr2i9V/C/gmqAEZ5qVTzRnd3uWdFoKzPdEBxP0Ipor"
    "J1VBbCv90yBSOhVxO+QIDAQAB"
)
# 117-byte plaintext chunks ⇒ 128-byte (1024-bit) RSA blocks with PKCS#1 v1.5.
_RSA_CHUNK = 117

# xBloom's error code for an expired session token (auth-flow.md).
_TOKEN_EXPIRED_CODE = 10001


def _load_public_key():
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(
            _RSA_PUBLIC_KEY_B64[i : i + 64]
            for i in range(0, len(_RSA_PUBLIC_KEY_B64), 64)
        )
        + "\n-----END PUBLIC KEY-----\n"
    )
    return load_pem_public_key(pem.encode("ascii"))


_PUBLIC_KEY = _load_public_key()


def _rsa_encrypt(payload: dict[str, Any]) -> str:
    """RSA-encrypt a JSON body the way the xBloom clients do.

    JSON-serialize → split into 117-byte chunks → PKCS#1 v1.5 encrypt each →
    concatenate the cipher blocks → base64. The result is the entire request
    body for a ``tu*`` endpoint.
    """
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    blocks = bytearray()
    for i in range(0, len(plaintext), _RSA_CHUNK):
        chunk = plaintext[i : i + _RSA_CHUNK]
        blocks += _PUBLIC_KEY.encrypt(chunk, padding.PKCS1v15())
    return base64.b64encode(bytes(blocks)).decode("ascii")


class XBloomAuthError(XBloomAPIError):
    """Login failed, or the session token expired (code 10001).

    ``expired`` is True when a previously-valid token was rejected as expired
    (the caller should re-login), False for a hard credential failure.
    """

    def __init__(self, message: str, *, expired: bool = False) -> None:
        super().__init__(message)
        self.expired = expired


# --------------------------------------------------------------------------- #
# Recipe field mapping (internal Recipe dict → cloud request body)             #
# --------------------------------------------------------------------------- #
def _ratio_denominator(recipe: dict) -> float:
    """Return the ratio denominator N (of 1:N) for a recipe.

    Recipes carry a ``ratio`` string ("1:16") once normalised; failing that we
    fall back to the ambiguous ``water_ratio``/``grinder`` reconstruction the
    validator uses. The cloud ``grandWater`` field is this denominator, NOT the
    total water in ml (confirmed: the MCP sends ``grandWater = ratio``).
    """
    ratio = recipe.get("ratio")
    if isinstance(ratio, str) and ":" in ratio:
        try:
            return float(ratio.split(":", 1)[1])
        except (ValueError, IndexError):
            pass
    dose = float(recipe.get("dose_g") or 0)
    water = float(recipe.get("water_ratio") or 0)
    if water <= 0:
        return 16.0
    # water ≤ 25 is already a denominator; larger values are total water in ml.
    if water <= 25 or dose <= 0:
        return round(water, 1)
    return round(water / dose, 1)


def _pour_to_cloud(pour: dict, index: int) -> dict:
    """Map one internal pour dict to the cloud pour shape."""
    name = pour.get("name") or ("Bloom" if index == 0 else f"Pour {index + 1}")
    return {
        "theName": name,
        "volume": float(pour.get("volume_ml", 0)),
        "temperature": float(pour.get("temperature_c", 92)),
        "flowRate": float(pour.get("flow_rate", 3.0)),
        # `pattern` is already the cloud API code (1/2/3) in our internal shape.
        "pattern": int(pour.get("pattern", 2)),
        "pausing": int(pour.get("pause_s", 0)),
        # agitate_* already use the cloud 1=on/2=off convention.
        "isEnableVibrationBefore": int(pour.get("agitate_before", 2)),
        "isEnableVibrationAfter": int(pour.get("agitate_after", 2)),
    }


def recipe_to_cloud_body(recipe: dict) -> dict:
    """Build the cloud create/update body fields for an internal recipe dict.

    Returns only the recipe fields (not the auth envelope). The caller adds the
    envelope + credentials and, for updates, the ``tableId``.
    """
    pours = recipe.get("pours") or []
    bypass_enabled = int(recipe.get("bypass_water_enabled", 2))
    body = {
        "theName": (recipe.get("name") or "").strip(),
        "dose": float(recipe.get("dose_g", 0)),
        "grandWater": _ratio_denominator(recipe),
        "grinderSize": float(
            recipe.get("grind_size", recipe.get("grinder_size", 40))
        ),
        "rpm": int(recipe.get("grinder_speed_rpm", recipe.get("rpm", 90))),
        "cupType": int(recipe.get("cup_type", 2)),
        "adaptedModel": int(recipe.get("adapted_model", 1)),
        "isEnableBypassWater": bypass_enabled,
        "isSetGrinderSize": int(recipe.get("grinder_size_enabled", 1)),
        "theColor": recipe.get("color_hex") or "#C9D5B8",
        "theSubsetId": int(recipe.get("subset_id", 0)),
        "subSetType": int(recipe.get("subset_type", 2)) or 2,
        "appPlace": [4],
        "createTimeStamp": int(recipe.get("created_at_ms") or time.time() * 1000),
        "isShortcuts": int(recipe.get("is_shortcut", 2)) or 2,
        "pourDataJSONStr": json.dumps(
            [_pour_to_cloud(p, i) for i, p in enumerate(pours)],
            separators=(",", ":"),
        ),
    }
    if bypass_enabled == 1:
        body["bypassTemp"] = float(recipe.get("bypass_temp_c", 85.0))
        body["bypassVolume"] = float(recipe.get("bypass_volume_ml", 5.0))
    return body


# --------------------------------------------------------------------------- #
# Error surfacing                                                              #
# --------------------------------------------------------------------------- #
_ERROR_KEYS = (
    "msg", "message", "errorMsg", "errorMessage", "error", "reason", "tips",
    "info",
)


def _error_message(resp: dict) -> str:
    for key in _ERROR_KEYS:
        val = resp.get(key)
        if val:
            return str(val)
    return "request failed"


def _find_code(resp: dict) -> int | None:
    for key in ("code", "errorCode", "result", "status"):
        val = resp.get(key)
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _raise_for_result(resp: dict, action: str) -> None:
    """Raise if the response envelope isn't a success. Maps 10001 → auth error."""
    if resp.get("result") == "success":
        return
    if _find_code(resp) == _TOKEN_EXPIRED_CODE:
        raise XBloomAuthError(f"{action}: session token expired", expired=True)
    raise XBloomAPIError(f"{action}: {_error_message(resp)}")


class XBloomCloudClient:
    """Async client for the authenticated xBloom recipe/firmware cloud.

    Stateless with respect to credentials: ``member_id`` + ``token`` are passed
    into each authenticated call so the coordinator can refresh them (via
    :meth:`login`) without rebuilding the client.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        language_type: int = DEFAULT_LANGUAGE_TYPE,
    ) -> None:
        self._session = session
        self._language_type = language_type

    def _envelope(self) -> dict:
        """The base request envelope with this client's language applied."""
        return {**_BASE_ENVELOPE, "languageType": self._language_type}

    # -- transport ---------------------------------------------------------- #
    async def _post_plain(self, endpoint: str, payload: dict) -> dict:
        async with self._session.post(
            f"{API_BASE}/{endpoint}", data=json.dumps(payload), headers=_HEADERS,
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _post_encrypted(self, endpoint: str, payload: dict) -> dict:
        body = json.dumps(_rsa_encrypt(payload))  # bare JSON string body
        async with self._session.post(
            f"{API_BASE}/{endpoint}", data=body, headers=_HEADERS,
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _auth_body(self, member_id: int, token: str, **extra: Any) -> dict:
        return {**self._envelope(), "memberId": member_id, "token": token, **extra}

    # -- auth --------------------------------------------------------------- #
    async def login(self, email: str, password: str) -> dict:
        """Log in with email + password. Returns ``{memberId, token}``.

        Raises :class:`XBloomAuthError` on a credential/format failure.
        """
        payload = {**self._envelope(), "email": email, "password": password}
        try:
            resp = await self._post_plain("tMemberLogin.thtml", payload)
        except aiohttp.ClientError as err:
            raise XBloomAPIError(f"login transport error: {err}") from err
        if resp.get("result") != "success":
            raise XBloomAuthError(f"login failed: {_error_message(resp)}")
        member = resp.get("member") or {}
        member_id = member.get("tableId")
        token = resp.get("token")
        if member_id is None or not token:
            raise XBloomAuthError("login response missing token/member id")
        return {"memberId": int(member_id), "token": str(token)}

    # -- recipes ------------------------------------------------------------ #
    async def _list_endpoint(
        self, endpoint: str, member_id: int, token: str, *, action: str
    ) -> list[Recipe]:
        """POST a recipe-list endpoint and parse ``resp["list"]`` to Recipes."""
        payload = self._auth_body(
            member_id, token,
            pageNumber=1, countPerPage=100, adaptedModel=1,
        )
        resp = await self._post_encrypted(endpoint, payload)
        _raise_for_result(resp, action)
        out: list[Recipe] = []
        for raw in resp.get("list") or []:
            try:
                out.append(_parse_recipe(raw))
            except (KeyError, TypeError, ValueError) as err:
                log.warning("skipping unparseable cloud recipe %s: %s",
                            raw.get("tableId") if isinstance(raw, dict) else raw, err)
        return out

    async def list_recipes(self, member_id: int, token: str) -> list[Recipe]:
        """Return the user's full recipe library: created + downloaded (shared).

        The xBloom app splits these into "My Recipes" (``tuMyTeaRecipeCreated``)
        and "Shared Recipes" (``tuMyRecipeShared`` — recipes you saved from a
        share link). Confirmed against a live account: both are owned by the
        member (``creatorId`` == you) and fully editable, and the two lists are
        disjoint; a shared recipe only differs by carrying a ``resourceTableId``
        back to its origin. HA merges them into one library and tags the shared
        ones ``shared=True`` so a dashboard can group them, with no special edit
        handling. The product/discover catalog (``tuMyRecipeProduct``, 100+
        curated recipes not owned by the user) is deliberately excluded.
        """
        recipes = await self._list_endpoint(
            "tuMyTeaRecipeCreated.tuhtml", member_id, token, action="list recipes"
        )
        seen = {r["id"] for r in recipes}
        try:
            shared = await self._list_endpoint(
                "tuMyRecipeShared.tuhtml", member_id, token,
                action="list shared recipes",
            )
        except XBloomAuthError:
            raise  # let the session re-login; the created list already worked
        except (XBloomAPIError, aiohttp.ClientError) as err:
            log.warning(
                "xbloom cloud: shared recipe list failed (%s) — omitting", err
            )
            shared = []
        for recipe in shared:
            if recipe["id"] in seen:
                continue
            recipe["shared"] = True
            recipes.append(recipe)
        return recipes

    async def create_recipe(
        self, member_id: int, token: str, recipe: dict
    ) -> str:
        """Create a recipe in the cloud. Returns the new server ``tableId``."""
        payload = self._auth_body(
            member_id, token, **recipe_to_cloud_body(recipe)
        )
        resp = await self._post_encrypted("tuRecipeAdd.tuhtml", payload)
        _raise_for_result(resp, "create recipe")
        return str(resp.get("tableId", ""))

    async def update_recipe(
        self, member_id: int, token: str, table_id: str, recipe: dict
    ) -> None:
        """Update the cloud recipe identified by ``table_id``."""
        payload = self._auth_body(
            member_id, token, tableId=table_id, **recipe_to_cloud_body(recipe)
        )
        resp = await self._post_encrypted("tuRecipeUpdate.tuhtml", payload)
        _raise_for_result(resp, "update recipe")

    async def delete_recipe(
        self, member_id: int, token: str, table_id: str
    ) -> None:
        """Delete the cloud recipe identified by ``table_id``."""
        payload = self._auth_body(member_id, token, tableId=table_id)
        resp = await self._post_encrypted("tuRecipeDelete.tuhtml", payload)
        _raise_for_result(resp, "delete recipe")

    # -- firmware ----------------------------------------------------------- #
    async def firmware_check(self, serial_number: str) -> dict | None:
        """Return the latest firmware metadata for a machine serial, or None.

        Plain (unencrypted) ``t*`` endpoint. Best-effort: returns the parsed
        ``{version, download_url, md5, notes_en, notes_zh, force}`` on success,
        None if the backend has nothing for this serial.
        """
        payload = {**self._envelope(), "serialNumber": serial_number, "adaptedModel": 1}
        try:
            resp = await self._post_plain(
                "tUpToDateFirmwareVersion.thtml", payload
            )
        except aiohttp.ClientError as err:
            raise XBloomAPIError(f"firmware check transport error: {err}") from err
        if resp.get("result") != "success":
            log.debug("firmware check: %s", _error_message(resp))
            return None
        version = resp.get("theVersion")
        if not version:
            return None
        # isForceUpgrade uses xBloom's 1=yes / 2=no convention (confirmed in a
        # live capture: a non-forced update returns 2) — NOT a truthy int.
        force_raw = resp.get("isForceUpgrade", resp.get("is_force_upgrade"))
        return {
            "version": str(version),
            "version_id": resp.get("versionId"),
            "download_url": resp.get("resourceLinks"),
            "md5": resp.get("md5_string"),
            "notes_en": resp.get("contentEN"),
            "notes_zh": resp.get("contentZH"),
            "force": force_raw == 1 or force_raw is True,
        }

    # NOTE: there is deliberately no "report firmware version to cloud" here.
    # The endpoint for that (tuMachineUpdate) is, per the Android app's
    # MachineUpdateForm, a FULL machine-settings sync keyed by the machine's
    # tableId (name, grinder, units, water feed, pattern, theVersion, …) — the
    # app always sends the machine's entire current state. Sending a partial
    # payload risks clobbering the user's cloud-stored settings, so after a
    # flash we let the official app sync the version instead.


class XBloomCloudSession:
    """Stateful authenticated session over :class:`XBloomCloudClient`.

    This is the portable seam an integration layer talks to. It owns the
    credential lifecycle — including automatic re-login when the token expires
    (error ``10001``) — so every layer (Home Assistant today; a CLI, Homebridge,
    or ESP32 bridge tomorrow) gets identical behavior without reimplementing it.

    The integration layer's only jobs are to *supply* the credentials and to
    *persist* a refreshed token. Persistence is delegated back via the optional
    ``on_token_refreshed(member_id, token)`` callback — the vendor never touches
    HA config entries, files, or any layer-specific storage.

    Args:
        client: the stateless transport client.
        email: account email.
        password: account password, or ``None`` if the user chose not to store
            it. When absent, an expired token cannot be refreshed silently — the
            session re-raises the expiry so the integration can prompt a
            re-login instead.
        member_id/token: the current session credentials.
        on_token_refreshed: optional sync callback invoked with the new
            ``(member_id, token)`` whenever a re-login mints a fresh token.
    """

    def __init__(
        self,
        client: XBloomCloudClient,
        *,
        email: str,
        password: str | None,
        member_id: int,
        token: str,
        on_token_refreshed: Any = None,
    ) -> None:
        self._client = client
        self._email = email
        self._password = password
        self.member_id = member_id
        self.token = token
        self._on_token_refreshed = on_token_refreshed

    async def _relogin(self) -> None:
        if not self._password:
            # No stored password — we can't refresh. Signal that the caller must
            # re-authenticate (prompt the user for credentials again).
            raise XBloomAuthError(
                "session expired and credentials are not stored", expired=True
            )
        fresh = await self._client.login(self._email, self._password)
        self.member_id = fresh["memberId"]
        self.token = fresh["token"]
        if self._on_token_refreshed is not None:
            self._on_token_refreshed(self.member_id, self.token)

    async def _call(self, fn: Any) -> Any:
        """Invoke ``fn(member_id, token)``, re-logging-in once on expiry."""
        try:
            return await fn(self.member_id, self.token)
        except XBloomAuthError as err:
            if not err.expired:
                raise
            log.info("xbloom cloud: token expired — re-logging in")
            await self._relogin()
            return await fn(self.member_id, self.token)

    async def list_recipes(self) -> list[Recipe]:
        return await self._call(self._client.list_recipes)

    async def create_recipe(self, recipe: dict) -> str:
        return await self._call(
            lambda mid, tok: self._client.create_recipe(mid, tok, recipe)
        )

    async def update_recipe(self, table_id: str, recipe: dict) -> None:
        return await self._call(
            lambda mid, tok: self._client.update_recipe(mid, tok, table_id, recipe)
        )

    async def delete_recipe(self, table_id: str) -> None:
        return await self._call(
            lambda mid, tok: self._client.delete_recipe(mid, tok, table_id)
        )
