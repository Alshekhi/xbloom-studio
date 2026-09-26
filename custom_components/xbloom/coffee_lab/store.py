"""Where Coffee Lab keeps its bags and brews.

One store per install, never mirrored: a second writer is how inventories
drift. `LocalStore` is Home Assistant's own storage — no setup, and covered by
Home Assistant's backups. A Notion store implements the same interface.

The duplicate-brew guard is kept in Home Assistant's storage whichever store
holds the bags, because it protects the subtraction, not the record.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..const import DOMAIN
from .models import SELECTABLE, Bean, Brew, Review
from .stats import moment

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.coffee_lab"
PROCESSED_KEY = f"{DOMAIN}.coffee_lab_processed"

# Run ids older than this are dropped: a replay that late is not a duplicate.
KEEP_RUN_IDS = 500

# The fields of a bag a person may change; `id` is its identity and never does.
EDITABLE = tuple(f.name for f in fields(Bean) if f.name != "id")


class UnknownBean(LookupError):
    """No bag has that id."""


class Storage(Protocol):
    """What the stores need from Home Assistant's `Store`."""

    async def async_load(self) -> Any: ...
    async def async_save(self, data: Any) -> None: ...


class CoffeeLabStore(ABC):
    """What Coffee Lab asks of any store."""

    @abstractmethod
    async def async_list_beans(self, *, selectable_only: bool = True) -> list[Bean]:
        """Bags, by default only those that can be brewed from."""

    @abstractmethod
    async def async_get_bean(self, bean_id: str) -> Bean:
        """One bag; `UnknownBean` if there is none with this id."""

    @abstractmethod
    async def async_add_bean(self, **values: Any) -> Bean:
        """A new bag, given its fields other than `id`."""

    @abstractmethod
    async def async_update_bean(self, bean_id: str, **changes: Any) -> Bean:
        """Change a bag's fields; `id` cannot change."""

    @abstractmethod
    async def async_list_brews(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[Brew]:
        """Brews, newest first, optionally from `since` on."""

    @abstractmethod
    async def async_create_brew(self, brew: Brew) -> Brew:
        """Record a brew; the store assigns its id."""

    async def async_set_tracking(self, bean_id: str, tracked: bool) -> Bean:
        return await self.async_update_bean(bean_id, tracked=tracked)

    async def async_finish_bag(self, bean_id: str) -> Bean:
        return await self.async_update_bean(bean_id, status="finished")

    async def async_apply_bean_update(
        self, bean_id: str, *, remaining_g: float, open_bag: bool, finish: bool,
        today: str,
    ) -> Bean:
        """What a counted brew does to its bag: the new amount, and its stage."""
        changes: dict[str, Any] = {"remaining_g": remaining_g}
        if finish:
            changes["status"] = "finished"
        elif open_bag:
            changes["status"] = "open"
            changes["opened_on"] = today
        return await self.async_update_bean(bean_id, **changes)


def _check_changes(changes: dict[str, Any]) -> None:
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ValueError(f"not bag fields: {', '.join(sorted(unknown))}")


def _brew_from_dict(data: dict[str, Any]) -> Brew:
    review = data.get("review")
    return Brew(**{**data, "review": Review(**review) if review else None})


class LocalStore(CoffeeLabStore):
    """Coffee Lab in Home Assistant's own storage."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._beans: dict[str, Bean] = {}
        self._brews: list[Brew] = []

    async def async_load(self) -> None:
        data = await self._storage.async_load() or {}
        self._beans = {b["id"]: Bean(**b) for b in data.get("beans", [])}
        self._brews = [_brew_from_dict(b) for b in data.get("brews", [])]

    async def _async_save(self) -> None:
        await self._storage.async_save({
            "beans": [asdict(b) for b in self._beans.values()],
            "brews": [asdict(b) for b in self._brews],
        })

    async def async_list_beans(self, *, selectable_only: bool = True) -> list[Bean]:
        return [
            b for b in self._beans.values()
            if not selectable_only or b.status in SELECTABLE
        ]

    async def async_get_bean(self, bean_id: str) -> Bean:
        try:
            return self._beans[bean_id]
        except KeyError:
            raise UnknownBean(bean_id) from None

    async def async_add_bean(self, **values: Any) -> Bean:
        _check_changes(values)
        bean = Bean(id=uuid.uuid4().hex, **values)
        self._beans[bean.id] = bean
        await self._async_save()
        return bean

    async def async_update_bean(self, bean_id: str, **changes: Any) -> Bean:
        _check_changes(changes)
        bean = replace(await self.async_get_bean(bean_id), **changes)
        self._beans[bean_id] = bean
        await self._async_save()
        return bean

    async def async_list_brews(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[Brew]:
        # Compared as instants: as text, "…Z" and "…+03:00" do not sort in time.
        zone = since.tzinfo if since is not None else timezone.utc
        dated = [
            (m, b) for b in self._brews
            if (m := moment(b.brewed_at or b.recorded_at, zone)) is not None
        ]
        dated.sort(key=lambda pair: pair[0], reverse=True)
        brews = [b for m, b in dated if since is None or m >= since]
        return brews[:limit] if limit is not None else brews

    async def async_create_brew(self, brew: Brew) -> Brew:
        recorded = replace(brew, id=uuid.uuid4().hex)
        self._brews.append(recorded)
        await self._async_save()
        return recorded


class ProcessedRuns:
    """Which brews have already been counted.

    A completion can arrive twice — a restart mid-handling, a replay — and
    subtracting the same dose twice is silent and permanent. A run id is saved
    before the subtraction is reported done.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._run_ids: list[str] = []

    async def async_load(self) -> None:
        data = await self._storage.async_load() or {}
        self._run_ids = list(data.get("run_ids", []))

    def contains(self, run_id: str | None) -> bool:
        return bool(run_id) and run_id in self._run_ids

    async def async_add(self, run_id: str | None) -> None:
        if not run_id or run_id in self._run_ids:
            return
        self._run_ids = [*self._run_ids, run_id][-KEEP_RUN_IDS:]
        await self._storage.async_save({"run_ids": self._run_ids})


async def async_local_store(hass: HomeAssistant) -> LocalStore:
    store = LocalStore(Store(hass, STORAGE_VERSION, STORAGE_KEY))
    await store.async_load()
    return store


async def async_processed_runs(hass: HomeAssistant) -> ProcessedRuns:
    runs = ProcessedRuns(Store(hass, STORAGE_VERSION, PROCESSED_KEY))
    await runs.async_load()
    return runs
