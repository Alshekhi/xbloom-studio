"""Unit tests for the vendor cloud client (vendor/xbloom/cloud.py).

Pure-logic coverage — no network. Imports the vendor core as the top-level
package `xbloom` (same pattern as test_validate_behaviour). Needs `aiohttp` and
`cryptography` importable; run with:

    uv run --with aiohttp --with cryptography pytest tests/test_cloud.py

Covers the parts most likely to break the wire contract: RSA block sizing, the
internal-recipe → cloud-body field mapping, ratio-denominator inference, and the
session's re-login-on-expiry behaviour.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import sys

_VENDOR = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "xbloom", "vendor",
)
sys.path.insert(0, os.path.abspath(_VENDOR))

from xbloom import cloud  # noqa: E402
from xbloom.cloud import (  # noqa: E402
    XBloomAuthError,
    XBloomCloudSession,
    _ratio_denominator,
    _rsa_encrypt,
    language_type_for,
    recipe_to_cloud_body,
)

# A wizard-shape recipe (mirrors test_validate_behaviour's VALID).
RECIPE = {
    "id": "803560", "name": "Sweet Spot", "dose_g": 20.0,
    "ratio": "1:15", "water_ratio": 300.0, "grind_size": 50,
    "grinder_size": 50, "grinder_size_enabled": 1, "grinder_speed_rpm": 100,
    "rpm": 100, "pour_count": 2, "cup_type": 3, "cup_type_name": "Other",
    "bypass_water_enabled": 2, "color_hex": "#C9D5B8", "created_at_ms": 1700000000000,
    "pours": [
        {"name": "Bloom", "volume_ml": 40, "temperature_c": 92, "pattern": 3,
         "flow_rate": 3.2, "pause_s": 20, "agitate_before": 2, "agitate_after": 1},
        {"name": "Pour 2", "volume_ml": 260, "temperature_c": 90, "pattern": 2,
         "flow_rate": 3.0, "pause_s": 0, "agitate_before": 2, "agitate_after": 2},
    ],
}


# --------------------------------------------------------------------------- #
# RSA encryption block sizing                                                 #
# --------------------------------------------------------------------------- #
def test_rsa_encrypt_is_valid_base64_and_block_sized():
    payload = {"a": 1, "b": "x" * 300}  # forces multiple 117-byte chunks
    out = _rsa_encrypt(payload)
    raw = base64.b64decode(out)  # valid base64 or this raises
    plaintext_len = len(json.dumps(payload, separators=(",", ":")).encode())
    expected_blocks = math.ceil(plaintext_len / 117)
    # 1024-bit key ⇒ 128-byte cipher blocks.
    assert len(raw) == expected_blocks * 128


def test_rsa_encrypt_randomised_padding_differs_but_stable_length():
    payload = {"hello": "world"}
    a, b = _rsa_encrypt(payload), _rsa_encrypt(payload)
    assert a != b  # PKCS#1 v1.5 padding is randomised
    assert len(base64.b64decode(a)) == len(base64.b64decode(b)) == 128


# --------------------------------------------------------------------------- #
# Ratio denominator inference (grandWater)                                     #
# --------------------------------------------------------------------------- #
def test_ratio_denominator_prefers_ratio_string():
    assert _ratio_denominator({"ratio": "1:16", "dose_g": 18, "water_ratio": 999}) == 16.0


def test_ratio_denominator_from_total_water():
    # No ratio string; water_ratio is total ml → divide by dose.
    assert _ratio_denominator({"dose_g": 20, "water_ratio": 300.0}) == 15.0


def test_ratio_denominator_from_bare_denominator():
    # water_ratio already a denominator (≤ 25) → used directly.
    assert _ratio_denominator({"dose_g": 18, "water_ratio": 16.0}) == 16.0


# --------------------------------------------------------------------------- #
# Recipe → cloud body mapping                                                 #
# --------------------------------------------------------------------------- #
def test_recipe_to_cloud_body_core_fields():
    body = recipe_to_cloud_body(RECIPE)
    assert body["theName"] == "Sweet Spot"
    assert body["dose"] == 20.0
    assert body["grandWater"] == 15.0  # 1:15, NOT total water 300
    assert body["grinderSize"] == 50
    assert body["rpm"] == 100
    assert body["cupType"] == 3
    assert body["isEnableBypassWater"] == 2
    assert body["theColor"] == "#C9D5B8"
    assert body["appPlace"] == [4]
    # Bypass disabled → no bypass fields.
    assert "bypassTemp" not in body and "bypassVolume" not in body


def test_recipe_to_cloud_body_pours_are_stringified_json():
    body = recipe_to_cloud_body(RECIPE)
    pours = json.loads(body["pourDataJSONStr"])  # must be a JSON *string*
    assert isinstance(body["pourDataJSONStr"], str)
    assert len(pours) == 2
    first = pours[0]
    assert first["theName"] == "Bloom"
    assert first["volume"] == 40
    assert first["temperature"] == 92
    assert first["pattern"] == 3            # passthrough (cloud API code)
    assert first["isEnableVibrationBefore"] == 2
    assert first["isEnableVibrationAfter"] == 1
    # Missing-name pour would get an auto label; here names are explicit.
    assert pours[1]["theName"] == "Pour 2"


def test_recipe_to_cloud_body_bypass_enabled_adds_fields():
    r = {**RECIPE, "bypass_water_enabled": 1, "bypass_temp_c": 80.0,
         "bypass_volume_ml": 10.0}
    body = recipe_to_cloud_body(r)
    assert body["isEnableBypassWater"] == 1
    assert body["bypassTemp"] == 80.0
    assert body["bypassVolume"] == 10.0


def test_recipe_to_cloud_body_autolabels_unnamed_pours():
    r = {**RECIPE, "pours": [
        {"volume_ml": 30, "temperature_c": 92, "pattern": 2},
        {"volume_ml": 90, "temperature_c": 90, "pattern": 2},
    ]}
    pours = json.loads(recipe_to_cloud_body(r)["pourDataJSONStr"])
    assert pours[0]["theName"] == "Bloom"
    assert pours[1]["theName"] == "Pour 2"


# --------------------------------------------------------------------------- #
# Session re-login on token expiry                                            #
# --------------------------------------------------------------------------- #
class _FakeClient:
    """Minimal stand-in for XBloomCloudClient used by the session tests."""

    def __init__(self, *, expire_first: bool):
        self._expire_first = expire_first
        self.login_calls = 0
        self.list_calls = 0

    async def login(self, email, password):
        self.login_calls += 1
        return {"memberId": 999, "token": "fresh-token"}

    async def list_recipes(self, member_id, token):
        self.list_calls += 1
        if self._expire_first and self.list_calls == 1:
            raise XBloomAuthError("expired", expired=True)
        return [{"id": "1", "member_id": member_id, "token": token}]


def _session(client, **kw):
    seen = {}
    def _persist(mid, tok):
        seen["member_id"] = mid
        seen["token"] = tok
    sess = XBloomCloudSession(
        client, email="a@b.c", password="pw", member_id=1, token="old-token",
        on_token_refreshed=_persist, **kw,
    )
    return sess, seen


def test_session_relogins_once_on_expiry():
    client = _FakeClient(expire_first=True)
    sess, seen = _session(client)
    result = asyncio.run(sess.list_recipes())
    assert client.login_calls == 1          # re-logged in exactly once
    assert client.list_calls == 2           # retried after refresh
    assert result[0]["token"] == "fresh-token"
    assert sess.token == "fresh-token" and sess.member_id == 999
    assert seen == {"member_id": 999, "token": "fresh-token"}  # persisted


def test_session_no_relogin_when_not_expired():
    client = _FakeClient(expire_first=False)
    sess, seen = _session(client)
    result = asyncio.run(sess.list_recipes())
    assert client.login_calls == 0
    assert result[0]["token"] == "old-token"
    assert seen == {}


def test_session_without_password_reraises_on_expiry():
    # User chose not to store the password → session can't refresh; the expiry
    # must propagate (expired=True) so the integration can prompt a re-login.
    client = _FakeClient(expire_first=True)
    sess = XBloomCloudSession(
        client, email="a@b.c", password=None, member_id=1, token="old",
        on_token_refreshed=None,
    )
    try:
        asyncio.run(sess.list_recipes())
    except XBloomAuthError as err:
        assert err.expired
    else:  # pragma: no cover
        raise AssertionError("expected XBloomAuthError on expiry")
    assert client.login_calls == 0  # never attempted a doomed login


def test_session_hard_auth_error_propagates_without_relogin():
    client = _FakeClient(expire_first=False)

    async def boom(member_id, token):
        raise XBloomAuthError("bad creds", expired=False)

    sess, _ = _session(client)
    try:
        asyncio.run(sess._call(boom))
    except XBloomAuthError as err:
        assert not err.expired
    else:  # pragma: no cover
        raise AssertionError("expected XBloomAuthError to propagate")
    assert client.login_calls == 0


# --------------------------------------------------------------------------- #
# list_recipes merges created + shared, tags shared, excludes catalog          #
# --------------------------------------------------------------------------- #
def _raw_recipe(table_id, name, *, shared=False):
    r = {
        "tableId": table_id, "theName": name, "dose": 18.0, "grandWater": 16.0,
        "grinderSize": 40.0, "isSetGrinderSize": 1, "rpm": 90, "pourCount": 1,
        "pourList": [], "cupType": 2, "cupTypeName": "Omni",
        "createTimeStamp": 1700000000000, "creatorId": 18812,
    }
    if shared:
        r["resourceTableId"] = 999000 + table_id  # origin pointer
    return r


def test_list_recipes_merges_created_and_shared():
    from xbloom.cloud import XBloomCloudClient

    responses = {
        "tuMyTeaRecipeCreated.tuhtml": {
            "result": "success",
            "list": [_raw_recipe(1, "Created A"), _raw_recipe(2, "Created B")],
        },
        "tuMyRecipeShared.tuhtml": {
            "result": "success",
            "list": [_raw_recipe(50, "Shared X", shared=True)],
        },
    }
    calls = []

    async def fake_post(endpoint, payload):
        calls.append(endpoint)
        return responses[endpoint]

    client = XBloomCloudClient(session=None)
    client._post_encrypted = fake_post  # type: ignore[method-assign]

    recipes = asyncio.run(client.list_recipes(18812, "tok"))

    names = {r["name"] for r in recipes}
    assert names == {"Created A", "Created B", "Shared X"}
    shared = [r for r in recipes if r.get("shared")]
    assert [r["name"] for r in shared] == ["Shared X"]
    # Created recipes are not tagged shared.
    assert all(not r.get("shared") for r in recipes if r["name"].startswith("Created"))
    # The product/discover catalog is never fetched.
    assert "tuMyRecipeProduct.tuhtml" not in calls
    assert set(calls) == {"tuMyTeaRecipeCreated.tuhtml", "tuMyRecipeShared.tuhtml"}


def test_list_recipes_survives_shared_endpoint_failure():
    from xbloom.cloud import XBloomAPIError, XBloomCloudClient

    async def fake_post(endpoint, payload):
        if endpoint == "tuMyTeaRecipeCreated.tuhtml":
            return {"result": "success", "list": [_raw_recipe(1, "Created A")]}
        raise XBloomAPIError("shared list boom")

    client = XBloomCloudClient(session=None)
    client._post_encrypted = fake_post  # type: ignore[method-assign]

    recipes = asyncio.run(client.list_recipes(18812, "tok"))
    # Created recipes still returned even though the shared list failed.
    assert [r["name"] for r in recipes] == ["Created A"]


# --------------------------------------------------------------------------- #
# language_type_for — HA locale → xBloom languageType                          #
# --------------------------------------------------------------------------- #
def test_language_type_for_known_and_regioned():
    assert language_type_for("en") == 0
    assert language_type_for("fr") == 1
    assert language_type_for("de") == 2
    assert language_type_for("ar") == 7
    # HA uses BCP-47 for Chinese variants.
    assert language_type_for("zh-Hans") == 3
    assert language_type_for("zh-Hant") == 4
    # Region subtags fall back to the primary language.
    assert language_type_for("en-US") == 0
    assert language_type_for("ar-SA") == 7
    # Underscore separator + case are normalised.
    assert language_type_for("EN_us") == 0


def test_language_type_for_unknown_defaults_english():
    assert language_type_for(None) == 0
    assert language_type_for("") == 0
    assert language_type_for("pt-BR") == 0  # unsupported → English


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
