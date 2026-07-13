"""XBloomClient — minimal async client for the xBloom share endpoint.

Public API:
  - get_recipe_by_share_id(share_id) -> Recipe
  - share_id_from_url(url) -> str           (classmethod)

xBloom's authenticated/encrypted endpoints (`tRecipeListOfHome.thtml`,
`tuGetRecipeCode.tuhtml`, `api-iot.xbloom.com/...`) used to live here too,
but the integration now does everything locally:

  * Recipe data comes from the public, unauthenticated `RecipeDetail.html`
    share endpoint (this file).
  * The BLE recipe blob (formerly `theCode` from `tuGetRecipeCode`) is built
    locally by `vendor.xbloom.ble.encode_recipe_blob`.
  * Brewing happens entirely over BLE; no cloud roundtrip.

So all the auth/RSA/token-refresh machinery is gone — see `git log` for the
previous shape.
"""
import logging
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from .exceptions import XBloomAPIError
from .models import Pour, Recipe

log = logging.getLogger("xbloom.client")

_RECIPE_DETAIL_URL = "https://client-api.xbloom.com/RecipeDetail.html"


def _parse_pour(p: dict) -> Pour:
    """Map a raw API pour step dict to Pour field names."""
    return {
        "id": int(p["tableId"]),
        "recipe_id": int(p["recipeId"]),
        "name": str(p["theName"]),
        "volume_ml": float(p["volume"]),
        "temperature_c": float(p["temperature"]),
        "pattern": int(p["pattern"]),
        "flow_rate": float(p["flowRate"]),
        "pause_s": int(p["pausing"]),
        "agitate_before": int(p["isEnableVibrationBefore"]),
        "agitate_after": int(p["isEnableVibrationAfter"]),
    }


def _parse_recipe(r: dict) -> Recipe:
    """Map a raw API recipe dict to Recipe field names.

    All required fields are always mapped. Optional fields (`bypass_temp_c`,
    `bypass_volume_ml`, `pod`) are added only when present and non-None.
    """
    recipe: Recipe = {
        "id": str(r["tableId"]),
        "name": str(r["theName"]),
        "dose_g": float(r["dose"]),
        "water_ratio": float(r["grandWater"]),
        "grinder_size": float(r["grinderSize"]),
        "grinder_size_enabled": int(r["isSetGrinderSize"]),
        "rpm": int(r["rpm"]),
        "pour_count": int(r["pourCount"]),
        "pours": [_parse_pour(p) for p in r.get("pourList", [])],
        "cup_type": int(r["cupType"]),
        "cup_type_name": str(r["cupTypeName"]),
        "bypass_water_enabled": int(r.get("isEnableBypassWater", 2)),
        "color_hex": str(r.get("theColor", "")),
        "adapted_model": int(r.get("adaptedModel", 1)),
        "created_at_ms": int(r["createTimeStamp"]),
        "is_default": int(r.get("isDefault", 0)),
        "is_shortcut": int(r.get("isShortcuts", 0)),
        "subset_type": int(r.get("subSetType", 0)),
        "subset_id": int(r.get("theSubsetId", 0)),
        "share_url": str(r.get("shareRecipeLink", "")),
    }
    if r.get("bypassTemp") is not None:
        recipe["bypass_temp_c"] = float(r["bypassTemp"])
    if r.get("bypassVolume") is not None:
        recipe["bypass_volume_ml"] = float(r["bypassVolume"])
    pod = r.get("podsVo")
    if isinstance(pod, dict) and pod:
        recipe["pod"] = pod
    return recipe


class XBloomClient:
    """Minimal client that fetches recipe data from xBloom share links.

    Construction takes only an `aiohttp.ClientSession` — no credentials,
    tokens, or device IDs. Everything goes through the public share endpoint.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def get_recipe_by_share_id(self, share_id: str) -> Recipe:
        """Fetch a recipe by share ID (the value from share-h5.xbloom.com?id=...).

        Uses `RecipeDetail.html` — the same endpoint the share-h5 web app
        uses. No authentication, no encryption.

        Args:
            share_id: URL-decoded share token, e.g. "7G6KCNhtht2+zWbf9U7Vnw==".
                      The URL-encoded form is also accepted (decoded once).

        Returns:
            A parsed Recipe dict, identical in shape to entries from the
            previous `get_recipes()` cloud path.

        Raises:
            XBloomAPIError if the server reports the recipe doesn't exist or
            the response shape is unexpected.
        """
        decoded = unquote(share_id)
        body = {
            "tableIdOfRSA": decoded,
            "interfaceVersion": 19700101,  # share-page uses this older value
            "skey": "testskey",
        }
        log.debug("Fetching shared recipe %r", decoded)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
        }
        async with self._session.post(_RECIPE_DETAIL_URL, json=body, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("result") != "success":
            raise XBloomAPIError(
                f"RecipeDetail returned: {data.get('info') if isinstance(data, dict) else data!r}"
            )
        recipe_vo = data.get("recipeVo")
        if not isinstance(recipe_vo, dict):
            raise XBloomAPIError("RecipeDetail response missing recipeVo")
        return _parse_recipe(recipe_vo)

    @staticmethod
    def share_id_from_url(url: str) -> str:
        """Extract the `id` query param from a share-h5.xbloom.com URL."""
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        ids = qs.get("id", [])
        if not ids:
            raise ValueError(f"No 'id' query param in share URL: {url!r}")
        return unquote(ids[0])
