"""Every registered service is documented, and vice versa.

`services.yaml` is what Developer Tools → Actions renders and what external
callers read to learn the surface. When it drifts from the services actually
registered in `__init__.py`, callers are written against documentation that
was never true — which is how the voice tool ended up addressing entity ids
that had been renamed months earlier.

Parsed with a regex rather than PyYAML: the file's top-level keys are the
service names, one per line at column zero, and PyYAML is not among the test
dependencies.
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_COMPONENT = _ROOT / "custom_components" / "xbloom"

# Registered as `hass.services.async_register(DOMAIN, "<name>", ...)`, whether
# the call fits on one line or is wrapped across several.
_REGISTER_RE = re.compile(
    r"hass\.services\.async_register\(\s*(?:\n\s*)?DOMAIN,\s*(?:\n\s*)?\"([a-z_]+)\"",
)
_SERVICE_KEY_RE = re.compile(r"^([a-z_]+):$", re.M)


# Coffee Lab's services are one table, registered and removed by one loop.
_LAB_SERVICE_RE = re.compile(r'^    "([a-z_]+)": \(actions\.', re.M)


def _registered_by_init() -> set[str]:
    source = (_COMPONENT / "__init__.py").read_text()
    return set(_REGISTER_RE.findall(source))


def _registered() -> set[str]:
    lab = (_COMPONENT / "coffee_lab" / "services.py").read_text()
    return _registered_by_init() | set(_LAB_SERVICE_RE.findall(lab))


def _documented() -> set[str]:
    source = (_COMPONENT / "services.yaml").read_text()
    return set(_SERVICE_KEY_RE.findall(source))


def test_every_registered_service_is_documented() -> None:
    missing = _registered() - _documented()
    assert not missing, f"registered but absent from services.yaml: {sorted(missing)}"


def test_every_documented_service_is_registered() -> None:
    extra = _documented() - _registered()
    assert not extra, f"documented but never registered: {sorted(extra)}"


def test_every_service_is_removed_on_unload() -> None:
    """A service left behind after unload keeps answering with a dead entry."""
    source = (_COMPONENT / "__init__.py").read_text()
    block = re.search(r"for svc in \((.*?)\n    \):", source, re.S)
    assert block, "the unload service tuple moved — update this test"
    unloaded = set(re.findall(r"\"([a-z_]+)\"", block.group(1)))
    missing = _registered_by_init() - unloaded
    assert not missing, f"registered but never removed on unload: {sorted(missing)}"


def test_services_yaml_uses_no_tabs() -> None:
    assert "\t" not in (_COMPONENT / "services.yaml").read_text()


def _translated(path: str) -> dict:
    import json

    return json.loads((_COMPONENT / path).read_text()).get("services", {})


def test_every_service_is_named_and_described_in_every_language() -> None:
    """services.yaml holds fields and selectors; what a person reads is translated."""
    for path in ("strings.json", "translations/en.json", "translations/ar.json"):
        table = _translated(path)
        missing = _documented() - set(table)
        assert not missing, f"{path} lacks {sorted(missing)}"
        for service in _documented():
            assert table[service]["name"] and table[service]["description"], (path, service)


def test_the_arabic_describes_the_same_fields() -> None:
    en, ar = _translated("strings.json"), _translated("translations/ar.json")
    for service, body in en.items():
        assert set(body.get("fields", {})) == set(ar[service].get("fields", {})), service


def test_services_yaml_leaves_names_to_the_translations() -> None:
    source = (_COMPONENT / "services.yaml").read_text()
    assert not re.search(r"^  (name|description):", source, re.M)
