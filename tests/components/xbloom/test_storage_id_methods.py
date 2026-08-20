"""Tests for the id-based mutation methods on XBloomRecipeStore.

Plan 09-02 adds:
    - async_replace(recipe)   -> upsert by recipe['id'] (tableId)
    - async_delete(table_id)  -> remove by recipe['id']

homeassistant is not installed in the dev environment, so we inject minimal
sys.modules stubs (matching the pattern in test_config_flow.py) before
importing the storage module.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Inject minimal homeassistant stubs into sys.modules.
# Must happen before any custom_components import.
# ---------------------------------------------------------------------------

def _inject_stubs() -> None:
    def _mod(name: str):
        m = types.ModuleType(name)
        sys.modules.setdefault(name, m)
        return sys.modules[name]

    ha = _mod("homeassistant")
    core = _mod("homeassistant.core")
    core.HomeAssistant = MagicMock

    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = MagicMock

    exc = _mod("homeassistant.exceptions")
    exc.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    exc.ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})

    helpers = _mod("homeassistant.helpers")  # noqa: F841

    aio_client = _mod("homeassistant.helpers.aiohttp_client")
    aio_client.async_get_clientsession = MagicMock()

    uc = _mod("homeassistant.helpers.update_coordinator")
    uc.UpdateFailed = Exception

    storage_mod = _mod("homeassistant.helpers.storage")

    class _StubStore:
        """Real Store will be replaced by a fake instance on the
        XBloomRecipeStore object in fixtures, so this only needs to
        exist as a class for the import to work."""

        def __init__(self, hass, version, key):
            self._hass = hass
            self._version = version
            self._key = key

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

        async def async_remove(self):
            return None

    storage_mod.Store = _StubStore


_inject_stubs()

from custom_components.xbloom.storage import XBloomRecipeStore  # noqa: E402


# ---------------------------------------------------------------------------
# Fake backing Store
# ---------------------------------------------------------------------------


class _FakeStore:
    """In-memory replacement for homeassistant.helpers.storage.Store."""

    def __init__(self) -> None:
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data

    async def async_remove(self):
        self._data = None


@pytest.fixture
def store() -> XBloomRecipeStore:
    """Return an XBloomRecipeStore wired to an in-memory fake."""
    s = XBloomRecipeStore(hass=MagicMock(), entry_id="test_entry")
    s._store = _FakeStore()
    s._cache = None
    return s


def _recipe(table_id: str, name: str | None = None, **extra) -> dict:
    r = {"id": table_id, "name": name or f"recipe-{table_id}"}
    r.update(extra)
    return r


# ---------------------------------------------------------------------------
# async_replace
# ---------------------------------------------------------------------------


async def test_async_replace_appends_when_id_new(store: XBloomRecipeStore) -> None:
    await store.async_replace(_recipe("local-aaa", "First"))
    recipes = await store.async_load()
    assert len(recipes) == 1
    assert recipes[0]["id"] == "local-aaa"
    assert recipes[0]["name"] == "First"


async def test_async_replace_overwrites_when_id_exists(
    store: XBloomRecipeStore,
) -> None:
    await store.async_replace(_recipe("local-aaa", "First"))
    await store.async_replace(_recipe("local-bbb", "Second"))
    await store.async_replace(_recipe("local-aaa", "First-updated", dose_g=18.5))

    recipes = await store.async_load()
    # Order preserved (local-aaa stays in slot 0).
    assert [r["id"] for r in recipes] == ["local-aaa", "local-bbb"]
    assert recipes[0]["name"] == "First-updated"
    assert recipes[0]["dose_g"] == 18.5


async def test_async_replace_preserves_meta_subobject(
    store: XBloomRecipeStore,
) -> None:
    """D-60: unknown keys (incl. `meta` sub-object) survive a round-trip."""
    original = _recipe(
        "local-meta",
        "WithMeta",
        meta={"created_locally": True, "source": "phase-9-test"},
        custom_field="keep-me",
    )
    await store.async_replace(original)

    # Force a re-read from the fake store to mimic process restart.
    store._cache = None
    recipes_after_load = await store.async_load()
    assert recipes_after_load[0]["meta"] == {
        "created_locally": True,
        "source": "phase-9-test",
    }
    assert recipes_after_load[0]["custom_field"] == "keep-me"

    # Replace with new dict that also carries meta — must overwrite fully,
    # NOT merge — but the new meta itself must be preserved.
    updated = _recipe(
        "local-meta",
        "WithMeta",
        meta={"created_locally": True, "edited_at": 12345},
    )
    await store.async_replace(updated)
    store._cache = None
    after = await store.async_load()
    assert after[0]["meta"] == {"created_locally": True, "edited_at": 12345}


async def test_async_replace_raises_without_id(store: XBloomRecipeStore) -> None:
    with pytest.raises(ValueError, match="Recipe is missing 'id'"):
        await store.async_replace({"name": "no-id-here"})

    with pytest.raises(ValueError, match="Recipe is missing 'id'"):
        await store.async_replace({"id": "   ", "name": "blank-id"})


# ---------------------------------------------------------------------------
# async_delete
# ---------------------------------------------------------------------------


async def test_async_delete_returns_true_when_present(
    store: XBloomRecipeStore,
) -> None:
    await store.async_replace(_recipe("local-aaa", "Keep"))
    await store.async_replace(_recipe("local-bbb", "Drop"))

    result = await store.async_delete("local-bbb")
    assert result is True

    recipes = await store.async_load()
    assert [r["id"] for r in recipes] == ["local-aaa"]


async def test_async_delete_returns_false_when_absent(
    store: XBloomRecipeStore,
) -> None:
    await store.async_replace(_recipe("local-aaa", "Keep"))

    result = await store.async_delete("local-not-there")
    assert result is False

    recipes = await store.async_load()
    assert len(recipes) == 1
    assert recipes[0]["id"] == "local-aaa"


async def test_async_delete_only_removes_matching_id(
    store: XBloomRecipeStore,
) -> None:
    await store.async_replace(_recipe("local-aaa", "First"))
    await store.async_replace(_recipe("local-bbb", "Middle"))
    await store.async_replace(_recipe("local-ccc", "Last"))

    result = await store.async_delete("local-bbb")
    assert result is True

    recipes = await store.async_load()
    assert [r["id"] for r in recipes] == ["local-aaa", "local-ccc"]
    assert recipes[0]["name"] == "First"
    assert recipes[1]["name"] == "Last"
