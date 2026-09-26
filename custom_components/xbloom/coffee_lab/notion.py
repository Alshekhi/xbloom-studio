"""Coffee Lab in Notion: the Coffee Beans and Brews databases.

Chosen instead of Home Assistant's own storage, never beside it: one store per
install, never mirrored. Set up with an internal integration token and one page
shared with that integration; the two databases are found inside the page, or
created there with every field Coffee Lab uses. Fields Coffee Lab does not use —
tasting notes, ratings — are left to whoever fills them in.

Everything is addressed by page id: two bags of one coffee are two pages.

Calls use Home Assistant's own HTTP session and time out, because this code
runs inside Home Assistant: a call that hung would hold up whatever waited on
it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from ..tool_common import fail
from .models import SELECTABLE, Bean, Brew, Review
from .stats import moment
from .store import CoffeeLabStore, UnknownBean, _check_changes

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT = aiohttp.ClientTimeout(total=15)

BEANS_TITLE = "Coffee Beans"
BREWS_TITLE = "Brews"

# The fields Coffee Lab reads and writes, and their Notion types. A database
# found in the page must have each of them; one created there gets exactly
# these (and the relation between the two).
BEAN_FIELDS = {
    "Bean": "title", "Status": "select", "Remaining g": "number",
    "Bag Size g": "number", "Inventory Tracking": "select", "Roaster": "rich_text",
    "Country": "rich_text", "Region": "rich_text", "Process": "select",
    "Roaster Notes": "rich_text", "Opened Date": "date",
}
BREW_FIELDS = {
    "Brew": "title", "Brewed At": "date", "Dose g": "number", "Brewer": "select",
    "Dripper": "select", "Bean": "relation", "Recipe": "rich_text",
    "Needs Review": "checkbox", "Outcome": "select", "Grind": "rich_text",
    "Ratio": "number", "Water g": "number", "Temperature C": "number",
    "Flow Rate": "number", "Total Time sec": "number",
}

# Notion's option names for the store-neutral values, both ways.
STATUS = {"unopened": "Unopened", "open": "Open", "finished": "Finished", "archived": "Archived"}
TRACKING = {True: "Tracked", False: "Untracked"}
OUTCOME = {"confirmed": "Confirmed", "presumed": "Presumed"}
# Cup labels from spec, onto the dripper options the database has used.
DRIPPER = {"xPod": "XPod", "Omni dripper": "Omni", "Other": "Other", "Tea": "Tea"}
# A brew with no brewer is written as Other, and Other reads back as none.
OTHER = "Other"

SETTINGS = {
    "grind": "Grind", "ratio": "Ratio", "temperature_c": "Temperature C",
    "flow_rate": "Flow Rate", "duration_s": "Total Time sec",
}


class NotionError(Exception):
    """Notion refused or could not be reached; its message names what."""

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class NotionClient:
    session: aiohttp.ClientSession
    token: str

    async def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        try:
            async with self.session.request(
                method, f"{API}{path}", headers=headers, json=body, timeout=TIMEOUT
            ) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    # Notion's message names the property or permission at
                    # fault, which is the whole diagnosis for most failures.
                    raise NotionError(resp.status, text[:300])
                return dict(await resp.json()) if text else {}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NotionError(None, str(err) or type(err).__name__) from err

    async def query(self, database_id: str, body: dict[str, Any], limit: int | None = None) -> list[dict]:
        """Every page the query matches, following Notion's cursor."""
        body = {**body, "page_size": min(limit or 100, 100)}
        pages: list[dict] = []
        while True:
            res = await self.call("POST", f"/databases/{database_id}/query", body)
            pages.extend(res.get("results", []))
            if limit is not None and len(pages) >= limit:
                return pages[:limit]
            if not res.get("has_more") or not res.get("next_cursor"):
                return pages
            body = {**body, "start_cursor": res["next_cursor"]}


# ── Reading and writing property values ─────────────────────────────────────


def _plain(prop: dict | None) -> str:
    parts = (prop or {}).get("title") or (prop or {}).get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts)


def _select(prop: dict | None) -> str | None:
    return ((prop or {}).get("select") or {}).get("name")


def _number(prop: dict | None) -> float | None:
    value = (prop or {}).get("number")
    return float(value) if isinstance(value, (int, float)) else None


def _date(prop: dict | None) -> str:
    return (((prop or {}).get("date")) or {}).get("start") or ""


def _text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value}}]} if value else {"rich_text": []}


def _choice(value: str | None) -> dict:
    return {"select": {"name": value} if value else None}


def bean_from_page(page: dict) -> Bean:
    props = page.get("properties") or {}
    status = {v: k for k, v in STATUS.items()}.get(_select(props.get("Status")) or "", "unopened")
    return Bean(
        id=str(page.get("id", "")),
        name=_plain(props.get("Bean")),
        status=status,
        remaining_g=_number(props.get("Remaining g")),
        bag_size_g=_number(props.get("Bag Size g")),
        # Absent means untracked: a balance nobody established is not
        # counted down from a default.
        tracked=_select(props.get("Inventory Tracking")) == TRACKING[True],
        roaster=_plain(props.get("Roaster")),
        country=_plain(props.get("Country")),
        region=_plain(props.get("Region")),
        process=_select(props.get("Process")) or "",
        roaster_notes=_plain(props.get("Roaster Notes")),
        opened_on=_date(props.get("Opened Date")),
    )


def bean_properties(values: dict[str, Any]) -> dict[str, Any]:
    """The Notion properties for the bag fields in `values`."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        if key == "name":
            out["Bean"] = {"title": [{"text": {"content": value}}]}
        elif key == "status":
            out["Status"] = _choice(STATUS[value])
        elif key == "tracked":
            out["Inventory Tracking"] = _choice(TRACKING[bool(value)])
        elif key in ("remaining_g", "bag_size_g"):
            out["Remaining g" if key == "remaining_g" else "Bag Size g"] = {"number": value}
        elif key == "process":
            out["Process"] = _choice(value or None)
        elif key == "opened_on":
            out["Opened Date"] = {"date": {"start": value} if value else None}
        else:
            label = {"roaster": "Roaster", "country": "Country", "region": "Region",
                     "roaster_notes": "Roaster Notes"}[key]
            out[label] = _text(value or "")
    return out


def brew_from_page(page: dict) -> Brew:
    props = page.get("properties") or {}
    brewer = _select(props.get("Brewer"))
    dripper = _select(props.get("Dripper"))
    relation = (props.get("Bean") or {}).get("relation") or []
    settings = {key: _number(props.get(name)) for key, name in SETTINGS.items() if key != "grind"}
    grind = _plain(props.get("Grind"))
    if grind:
        settings["grind"] = grind
    return Brew(
        id=str(page.get("id", "")),
        brewed_at=_date(props.get("Brewed At")),
        recorded_at=str(page.get("created_time") or ""),
        dose_g=_number(props.get("Dose g")),
        brewer=None if brewer in (None, OTHER) else brewer,
        bean_id=str(relation[0]["id"]) if relation else None,
        water_ml=_number(props.get("Water g")),
        dripper={v: k for k, v in DRIPPER.items()}.get(dripper or "", dripper),
        recipe=_plain(props.get("Recipe")) or None,
        outcome={v: k for k, v in OUTCOME.items()}.get(_select(props.get("Outcome")) or ""),
        settings={k: v for k, v in settings.items() if v is not None},
        # Notion keeps that a brew needs review, not why.
        review=Review("needs_review") if (props.get("Needs Review") or {}).get("checkbox") else None,
    )


def brew_properties(brew: Brew) -> dict[str, Any]:
    props: dict[str, Any] = {
        # The recipe, else the brewer: something a person can tell rows by.
        "Brew": {"title": [{"text": {"content": brew.recipe or brew.brewer or ""}}]},
        "Brewed At": {"date": {"start": brew.brewed_at}},
        "Dose g": {"number": brew.dose_g},
        "Brewer": _choice(brew.brewer or OTHER),
    }
    if brew.bean_id:
        props["Bean"] = {"relation": [{"id": brew.bean_id}]}
    if brew.recipe:
        props["Recipe"] = _text(brew.recipe)
    if brew.dripper:
        props["Dripper"] = _choice(DRIPPER.get(brew.dripper, OTHER))
    if brew.outcome in OUTCOME:
        props["Outcome"] = _choice(OUTCOME[brew.outcome])
    if brew.review is not None:
        # Only when there is something to say, so the column filters well.
        props["Needs Review"] = {"checkbox": True}
    if brew.water_ml is not None:
        props["Water g"] = {"number": brew.water_ml}
    for key, name in SETTINGS.items():
        value = brew.settings.get(key)
        if value is None:
            continue
        props[name] = _text(str(value)) if key == "grind" else {"number": float(value)}
    return props


# ── Finding or creating the two databases ───────────────────────────────────


@dataclass(frozen=True)
class Databases:
    beans: str
    brews: str


class SetupProblem(Exception):
    """Why the page cannot hold Coffee Lab, as a form error and its details."""

    def __init__(self, error: str, detail: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.detail = detail


def page_id_from(text: str) -> str:
    """A page id from an id or a Notion URL, dashes or not."""
    tail = text.strip().rstrip("/").split("/")[-1].split("?")[0].split("#")[0]
    hexes = "".join(c for c in tail[-36:] if c in "0123456789abcdefABCDEF")
    return hexes[-32:].lower() if len(hexes) >= 32 else ""


def _missing(schema: dict[str, Any], wanted: dict[str, str]) -> list[str]:
    """Fields absent, or of the wrong type, as `Name (type)`."""
    return [
        f"{name} ({kind})" for name, kind in wanted.items()
        if (schema.get(name) or {}).get("type") != kind
    ]


async def _children(client: NotionClient, page_id: str) -> list[dict]:
    blocks: list[dict] = []
    path = f"/blocks/{page_id}/children?page_size=100"
    while True:
        res = await client.call("GET", path)
        blocks.extend(res.get("results", []))
        if not res.get("has_more"):
            return blocks
        path = f"/blocks/{page_id}/children?page_size=100&start_cursor={res['next_cursor']}"


def _schema(fields: dict[str, str], relation_to: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, kind in fields.items():
        if kind == "relation":
            out[name] = {"relation": {"database_id": relation_to, "single_property": {}}}
        elif kind == "select":
            options = {
                "Status": list(STATUS.values()), "Inventory Tracking": list(TRACKING.values()),
                "Outcome": list(OUTCOME.values()), "Dripper": list(DRIPPER.values()),
                "Brewer": [OTHER],
            }.get(name, [])
            out[name] = {"select": {"options": [{"name": o} for o in options]}}
        else:
            out[name] = {kind: {}}
    return out


async def async_find_or_create(client: NotionClient, page_id: str) -> Databases:
    """The page's Coffee Beans and Brews, created if the page has neither.

    Both present: used, once every field is checked. One present without the
    other, or a title held by two databases: refused, never guessed.
    """
    try:
        blocks = await _children(client, page_id)
    except NotionError as err:
        if err.status == 401:
            raise SetupProblem("notion_auth") from err
        if err.status in (403, 404):
            raise SetupProblem("notion_page") from err
        raise SetupProblem("notion_unreachable", str(err)) from err
    found: dict[str, list[str]] = {BEANS_TITLE: [], BREWS_TITLE: []}
    for block in blocks:
        title = (block.get("child_database") or {}).get("title")
        if block.get("type") == "child_database" and title in found:
            found[title].append(block["id"])
    if any(len(ids) > 1 for ids in found.values()):
        raise SetupProblem("notion_duplicate", ", ".join(t for t, ids in found.items() if len(ids) > 1))
    beans, brews = found[BEANS_TITLE], found[BREWS_TITLE]
    if bool(beans) != bool(brews):
        raise SetupProblem("notion_half", BEANS_TITLE if not beans else BREWS_TITLE)

    if not beans:
        parent = {"type": "page_id", "page_id": page_id}
        beans_db = await client.call("POST", "/databases", {
            "parent": parent, "title": [{"text": {"content": BEANS_TITLE}}],
            "properties": _schema(BEAN_FIELDS),
        })
        brews_db = await client.call("POST", "/databases", {
            "parent": parent, "title": [{"text": {"content": BREWS_TITLE}}],
            "properties": _schema(BREW_FIELDS, relation_to=beans_db["id"]),
        })
        return Databases(beans_db["id"], brews_db["id"])

    problems = []
    for db_id, wanted, title in ((beans[0], BEAN_FIELDS, BEANS_TITLE), (brews[0], BREW_FIELDS, BREWS_TITLE)):
        schema = (await client.call("GET", f"/databases/{db_id}")).get("properties") or {}
        if missing := _missing(schema, wanted):
            problems.append(f"{title}: {', '.join(missing)}")
    if problems:
        raise SetupProblem("notion_fields", "; ".join(problems))
    return Databases(beans[0], brews[0])


# ── The store ────────────────────────────────────────────────────────────────


class NotionStore(CoffeeLabStore):
    """Coffee Lab in two Notion databases."""

    def __init__(self, client: NotionClient, databases: Databases) -> None:
        self._client = client
        self._db = databases
        # A select option the database lacks is added before it is written:
        # Notion refuses a whole page sent an option it does not have.
        self._options: dict[tuple[str, str], set[str]] = {}
        self._schema_lock = asyncio.Lock()

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            return await self._client.call(method, path, body)
        except NotionError as err:
            raise fail("notion_failed", error=str(err)) from err

    async def _ensure_options(self, database_id: str, props: dict[str, Any]) -> None:
        wanted = {
            name: value["select"]["name"] for name, value in props.items()
            if isinstance(value, dict) and (value.get("select") or {}).get("name")
        }
        if not wanted:
            return
        async with self._schema_lock:
            if not all((database_id, n) in self._options for n in wanted):
                schema = (await self._call("GET", f"/databases/{database_id}")).get("properties") or {}
                for name in wanted:
                    options = ((schema.get(name) or {}).get("select") or {}).get("options") or []
                    self._options[(database_id, name)] = {o["name"] for o in options}
            missing = {n: v for n, v in wanted.items() if v not in self._options[(database_id, n)]}
            if not missing:
                return
            await self._call("PATCH", f"/databases/{database_id}", {"properties": {
                name: {"select": {"options": [
                    *({"name": o} for o in sorted(self._options[(database_id, name)])),
                    {"name": value},
                ]}} for name, value in missing.items()
            }})
            for name, value in missing.items():
                self._options[(database_id, name)].add(value)

    async def async_list_beans(self, *, selectable_only: bool = True) -> list[Bean]:
        body: dict[str, Any] = {}
        if selectable_only:
            body["filter"] = {"or": [
                {"property": "Status", "select": {"equals": STATUS[s]}} for s in SELECTABLE
            ]}
        try:
            pages = await self._client.query(self._db.beans, body)
        except NotionError as err:
            raise fail("notion_failed", error=str(err)) from err
        return [bean_from_page(p) for p in pages]

    async def async_get_bean(self, bean_id: str) -> Bean:
        try:
            page = await self._client.call("GET", f"/pages/{bean_id}")
        except NotionError as err:
            if err.status in (400, 404):
                raise UnknownBean(bean_id) from None
            raise fail("notion_failed", error=str(err)) from err
        parent = (page.get("parent") or {}).get("database_id", "").replace("-", "")
        if parent != self._db.beans.replace("-", "") or page.get("archived"):
            raise UnknownBean(bean_id)
        return bean_from_page(page)

    async def async_add_bean(self, **values: Any) -> Bean:
        _check_changes(values)
        props = bean_properties({"status": "unopened", "tracked": False, **values})
        await self._ensure_options(self._db.beans, props)
        page = await self._call("POST", "/pages", {
            "parent": {"database_id": self._db.beans}, "properties": props,
        })
        return bean_from_page(page)

    async def async_update_bean(self, bean_id: str, **changes: Any) -> Bean:
        _check_changes(changes)
        await self.async_get_bean(bean_id)
        props = bean_properties(changes)
        await self._ensure_options(self._db.beans, props)
        page = await self._call("PATCH", f"/pages/{bean_id}", {"properties": props})
        return bean_from_page(page)

    async def async_list_brews(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[Brew]:
        body: dict[str, Any] = {"sorts": [{"property": "Brewed At", "direction": "descending"}]}
        if since is not None:
            # A day early: a brew near midnight in UTC can be the next local
            # day. A row with no Brewed At is found by when it was recorded.
            day = (since - timedelta(days=1)).date().isoformat()
            body["filter"] = {"or": [
                {"property": "Brewed At", "date": {"on_or_after": day}},
                {"and": [
                    {"property": "Brewed At", "date": {"is_empty": True}},
                    {"timestamp": "created_time", "created_time": {"on_or_after": day}},
                ]},
            ]}
        try:
            pages = await self._client.query(self._db.brews, body, limit)
        except NotionError as err:
            raise fail("notion_failed", error=str(err)) from err
        brews = [brew_from_page(p) for p in pages]
        if since is None:
            return brews
        # The query reached a day early; the answer is exactly from `since`.
        return [
            b for b in brews
            if (m := moment(b.brewed_at or b.recorded_at, since.tzinfo)) is not None and m >= since
        ]

    async def async_create_brew(self, brew: Brew) -> Brew:
        props = brew_properties(brew)
        await self._ensure_options(self._db.brews, props)
        page = await self._call("POST", "/pages", {
            "parent": {"database_id": self._db.brews}, "properties": props,
        })
        return replace(brew, id=str(page.get("id", "")), recorded_at=str(page.get("created_time") or brew.recorded_at))
