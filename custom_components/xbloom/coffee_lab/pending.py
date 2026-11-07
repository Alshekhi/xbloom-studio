"""Brews waiting to reach the store.

Counting a brew is two writes to the store — the bag's new amount, then the
brew's row — and a store kept in Notion can fail at either. A brew is
therefore written here first, in Home Assistant's own storage, and leaves only
once the store holds all of it. Until then it is retried: on a timer, at
startup, and before the next brew is counted, oldest first.

Each entry keeps which of its writes have landed. A retry finishes only what
is missing, so the bag is not taken from twice and the row is not written
twice — the row is also looked for by its run id before it is written. One
window remains: Home Assistant stopping between the store taking the bag's
new amount and this file saying so. The retry would then take the dose again,
which shows on the bag and is put right by measuring it.

This is not a copy of the record. An entry exists only while its brew is not
yet in the store; the store stays the only history.
"""
from __future__ import annotations

from typing import Any

from .store import Storage

# What a brew waiting here keeps. `kind` is "brew" for a finished brew and
# "stopped" for one stopped after grinding; `args` are what the counting needs,
# fixed when the brew happened; `bag` is set once its bag write has landed.
EMPTY = {"entries": []}


class PendingBrews:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        data = await self._storage.async_load() or EMPTY
        self._entries = [dict(e) for e in data.get("entries", [])]

    async def _save(self) -> None:
        await self._storage.async_save({"entries": self._entries})

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Oldest first. A copy: change entries through this class."""
        return [dict(e) for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def contains(self, run_id: str) -> bool:
        return any(e["run_id"] == run_id for e in self._entries)

    async def async_add(self, run_id: str, kind: str, args: dict[str, Any], queued_at: str) -> None:
        self._entries.append({
            "run_id": run_id, "kind": kind, "args": args, "queued_at": queued_at,
            "attempts": 0, "last_error": None, "bag": None,
        })
        await self._save()

    async def async_update(self, run_id: str, **changes: Any) -> None:
        for entry in self._entries:
            if entry["run_id"] == run_id:
                entry.update(changes)
        await self._save()

    async def async_remove(self, run_id: str) -> None:
        self._entries = [e for e in self._entries if e["run_id"] != run_id]
        await self._save()

    @property
    def oldest(self) -> dict[str, Any] | None:
        return dict(self._entries[0]) if self._entries else None
