"""Repo-wide test fixtures.

`custom_components/xbloom/vendor/xbloom/cloud.py` imports `cryptography` at
module scope, and `coordinator.py` imports `cloud` unconditionally — so the
whole component tree is unimportable without it. Home Assistant ships
`cryptography` as a core dependency, so this is only ever a local-dev gap.

Rather than make every contributor install it to run the component tests
(which do not exercise any crypto), stub it when it is genuinely absent and
skip the one suite that needs the real thing.
"""
import os
import sys
import types
from unittest.mock import MagicMock

# The protocol tests import the vendored library as a top-level `xbloom`
# package. A superseded standalone `xbloom/` package still sits at the repo
# root (gitignored), and pytest puts the repo root on sys.path — so whichever
# is imported first wins for the whole session. Pin the vendored copy here,
# before any test module is imported, so the answer never depends on
# collection order.
_VENDOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components", "xbloom", "vendor",
)
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

try:  # pragma: no cover - depends on the local environment
    import cryptography  # noqa: F401

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

# test_cloud.py exercises real RSA/PKCS#1 v1.5 block sizing — a stub would make
# it pass vacuously, which is worse than not running it.
collect_ignore = [] if HAS_CRYPTOGRAPHY else ["test_cloud.py"]


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
