"""xbloom-py — share-link recipe client + local BLE encoder.

The convenience re-exports (`XBloomClient`, `XBloomAPIError`, `XBloomError`)
are resolved lazily so that importing a leaf module — e.g. `spec` or
`recipe_validate`, which have no third-party deps — does not drag in
`client` and its `aiohttp` requirement. This keeps the pure-Python core
importable on its own (for tests, or a non-HA consumer) while the top-level
names stay available for anyone who wants them.
"""

__all__ = ["XBloomClient", "XBloomAPIError", "XBloomError"]


def __getattr__(name: str):
    if name == "XBloomClient":
        from .client import XBloomClient
        return XBloomClient
    if name in ("XBloomAPIError", "XBloomError"):
        from . import exceptions
        return getattr(exceptions, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
