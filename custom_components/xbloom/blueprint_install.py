"""Install the announcement blueprints that come with the integration.

Each version of the integration carries the blueprints written for it, under
`blueprints/` beside this file, and puts them in Home Assistant's own blueprint
folder at `automation/xbloom/`. A blueprint is only a template — nothing runs
until someone creates an automation from it — so installing one costs nothing.

Keeping them current is the part that needs care, because a blueprint can be
edited by hand. What this integration last wrote is remembered as a
fingerprint, so an installed blueprint is one of:

  * missing — installed;
  * the same as the bundled one — nothing to do;
  * unchanged since this integration wrote it — replaced by the bundled one,
    and the automations using it reloaded (Home Assistant does that);
  * edited by hand — left alone. When a newer one has come with an update, a
    repair notice offers to replace it; the person decides.

A fingerprint is taken of the blueprint as Home Assistant reads it, not of the
file's bytes, so comments and formatting do not count as edits.

Field names are a promise here: an update that renamed one would break every
automation built on the blueprint until it was saved again.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BUNDLED = Path(__file__).parent / "blueprints"
# Under Home Assistant's blueprints/automation/.
INSTALL_FOLDER = "xbloom"
STORE_KEY = f"{DOMAIN}.blueprints"
STORE_VERSION = 1
# A blueprint on disk that Home Assistant cannot read is somebody's work in
# progress, never ours to replace.
UNREADABLE = "unreadable"
ISSUE_KEY = "blueprint_outdated"


def decide(installed: str | None, written: str | None, bundled: str) -> str:
    """What to do with one blueprint, from three fingerprints.

    `installed` is what is in Home Assistant now (None: nothing), `written`
    what this integration last put there (None: never), `bundled` what this
    version carries.
    """
    if installed is None:
        return "install"
    if installed == bundled:
        return "current"
    if written is not None and installed == written:
        return "update"
    # Edited by hand. Only news when the bundled one moved on since.
    if written is not None and bundled == written:
        return "edited"
    return "outdated"


def bundled_names() -> list[str]:
    """The bundled blueprints' file names. Reads the disk: not on the event loop."""
    return sorted(p.name for p in BUNDLED.glob("*.yaml"))


def issue_id(path: str) -> str:
    return f"{ISSUE_KEY}_{Path(path).stem}"


class _Installer:
    """Reads, compares and writes the bundled blueprints."""

    def __init__(self, hass: HomeAssistant) -> None:
        from homeassistant.components.automation.helpers import async_get_blueprints

        self._hass = hass
        self._blueprints = async_get_blueprints(hass)
        self._store: Store[dict[str, str]] = Store(hass, STORE_VERSION, STORE_KEY)

    @staticmethod
    def _read(file: Path, path: str):
        from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
        from homeassistant.components.blueprint import Blueprint
        from homeassistant.util import yaml as yaml_util

        return Blueprint(
            yaml_util.load_yaml_dict(file), path=path,
            expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA,
        )

    @staticmethod
    def _fingerprint(blueprint) -> str:
        return hashlib.sha256(blueprint.yaml().encode("utf-8")).hexdigest()

    def _installed(self, path: str) -> str | None:
        file = Path(self._hass.config.path("blueprints", "automation", path))
        if not file.exists():
            return None
        try:
            return self._fingerprint(self._read(file, path))
        except Exception:  # noqa: BLE001 — any unreadable file is left alone
            return UNREADABLE

    async def _bundled(self, path: str):
        return await self._hass.async_add_executor_job(
            self._read, BUNDLED / Path(path).name, path,
        )

    async def async_run(self) -> None:
        written = await self._store.async_load() or {}
        names = await self._hass.async_add_executor_job(bundled_names)
        for name in names:
            path = f"{INSTALL_FOLDER}/{name}"
            bundled = await self._bundled(path)
            bundled_fp = self._fingerprint(bundled)
            installed_fp = await self._hass.async_add_executor_job(self._installed, path)
            action = decide(installed_fp, written.get(path), bundled_fp)
            if action in ("install", "update"):
                await self._blueprints.async_add_blueprint(bundled, path, allow_override=True)
                _LOGGER.info(
                    "xbloom: blueprint %s %s", path,
                    {"install": "installed", "update": "updated"}[action],
                )
            if action in ("install", "update", "current"):
                written[path] = bundled_fp
            if action == "outdated":
                ir.async_create_issue(
                    self._hass, DOMAIN, issue_id(path),
                    is_fixable=True, severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_KEY,
                    translation_placeholders={"path": path},
                    data={"path": path},
                )
            else:
                ir.async_delete_issue(self._hass, DOMAIN, issue_id(path))
        await self._store.async_save(written)

    async def async_replace(self, path: str) -> None:
        """Put the bundled blueprint over one edited by hand, as asked."""
        bundled = await self._bundled(path)
        await self._blueprints.async_add_blueprint(bundled, path, allow_override=True)
        written = await self._store.async_load() or {}
        written[path] = self._fingerprint(bundled)
        await self._store.async_save(written)
        ir.async_delete_issue(self._hass, DOMAIN, issue_id(path))
        _LOGGER.info("xbloom: blueprint %s replaced by the bundled one", path)


async def async_install_blueprints(hass: HomeAssistant) -> None:
    """Install or update each bundled blueprint, as `decide` says."""
    await _Installer(hass).async_run()


async def async_replace_blueprint(hass: HomeAssistant, path: str) -> None:
    """Replace an edited blueprint with the bundled one."""
    await _Installer(hass).async_replace(path)
