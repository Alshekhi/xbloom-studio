"""Repo-wide test fixtures.

`xbloom.cloud` imports `cryptography` at module scope, and `coordinator.py`
imports `cloud` unconditionally — so the whole component tree is unimportable
without it. Home Assistant ships `cryptography` as a core dependency, so this is
only ever a local-dev gap.

Rather than make every contributor install it to run the component tests
(which do not exercise any crypto), stub it when it is genuinely absent.
"""
import sys
import types
from unittest.mock import MagicMock

try:  # pragma: no cover - depends on the local environment
    import cryptography  # noqa: F401

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


def _stub_cryptography() -> None:
    """Register MagicMock-backed `cryptography.*` modules in sys.modules."""
    for name in (
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.primitives",
        "cryptography.hazmat.primitives.asymmetric",
        "cryptography.hazmat.primitives.serialization",
    ):
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        module.__path__ = []  # type: ignore[attr-defined]
        # PEP 562 fallback: any name the component imports resolves to a mock.
        module.__getattr__ = lambda attr, _n=name: MagicMock(name=f"{_n}.{attr}")
        sys.modules[name] = module


if not HAS_CRYPTOGRAPHY:
    _stub_cryptography()
