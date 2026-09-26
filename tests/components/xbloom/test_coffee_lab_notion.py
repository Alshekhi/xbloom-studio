"""Coffee Lab in Notion, against a fake Notion that records every call."""
from datetime import datetime, timezone

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.xbloom.coffee_lab.models import Brew, Review
from custom_components.xbloom.coffee_lab.notion import (
    BEAN_FIELDS, BREW_FIELDS, Databases, NotionError, NotionStore, SetupProblem,
    async_find_or_create, bean_from_page, bean_properties, brew_from_page,
    brew_properties, page_id_from,
)
from custom_components.xbloom.coffee_lab.store import UnknownBean

PAGE = "0" * 32


class FakeNotion:
    """Answers the calls the store makes; `routes` maps (method, path) to a reply."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls: list[tuple] = []

    async def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        reply = self.routes.get((method, path.split("?")[0]))
        if isinstance(reply, Exception):
            raise reply
        return reply(body) if callable(reply) else (reply or {})

    async def query(self, database_id, body, limit=None):
        reply = await self.call("POST", f"/databases/{database_id}/query", body)
        results = reply.get("results", [])
        return results[:limit] if limit else results


def _schema(fields):
    return {"properties": {name: {"type": kind, "select": {"options": []}} for name, kind in fields.items()}}


def _child(title, block_id):
    return {"type": "child_database", "id": block_id, "child_database": {"title": title}}


# ── Setting up the page ──────────────────────────────────────────────────────


async def test_an_empty_page_gets_both_databases_related():
    created = iter([{"id": "beans-db"}, {"id": "brews-db"}])
    notion = FakeNotion({
        ("GET", f"/blocks/{PAGE}/children"): {"results": []},
        ("POST", "/databases"): lambda body: next(created),
    })
    assert await async_find_or_create(notion, PAGE) == Databases("beans-db", "brews-db")
    beans_body, brews_body = [c[2] for c in notion.calls if c[:2] == ("POST", "/databases")]
    assert set(beans_body["properties"]) == set(BEAN_FIELDS)
    assert brews_body["properties"]["Bean"]["relation"]["database_id"] == "beans-db"


async def test_an_existing_pair_is_used_once_every_field_is_there():
    notion = FakeNotion({
        ("GET", f"/blocks/{PAGE}/children"): {"results": [_child("Coffee Beans", "b"), _child("Brews", "r")]},
        ("GET", "/databases/b"): _schema({**BEAN_FIELDS, "Rating": "number"}),
        ("GET", "/databases/r"): _schema(BREW_FIELDS),
    })
    assert await async_find_or_create(notion, PAGE) == Databases("b", "r")
    assert not [c for c in notion.calls if c[0] in ("POST", "PATCH")], "nothing written"


async def test_a_missing_or_mistyped_field_is_named():
    beans = {**BEAN_FIELDS, "Remaining g": "rich_text"}
    beans.pop("Opened Date")
    notion = FakeNotion({
        ("GET", f"/blocks/{PAGE}/children"): {"results": [_child("Coffee Beans", "b"), _child("Brews", "r")]},
        ("GET", "/databases/b"): _schema(beans),
        ("GET", "/databases/r"): _schema(BREW_FIELDS),
    })
    with pytest.raises(SetupProblem) as caught:
        await async_find_or_create(notion, PAGE)
    assert caught.value.error == "notion_fields"
    assert "Remaining g (number)" in caught.value.detail and "Opened Date (date)" in caught.value.detail


@pytest.mark.parametrize("blocks, error", [
    ([_child("Coffee Beans", "b"), _child("Coffee Beans", "c"), _child("Brews", "r")], "notion_duplicate"),
    ([_child("Coffee Beans", "b")], "notion_half"),
])
async def test_an_ambiguous_page_is_refused_never_guessed(blocks, error):
    notion = FakeNotion({("GET", f"/blocks/{PAGE}/children"): {"results": blocks}})
    with pytest.raises(SetupProblem) as caught:
        await async_find_or_create(notion, PAGE)
    assert caught.value.error == error


@pytest.mark.parametrize("status, error", [(401, "notion_auth"), (404, "notion_page"), (500, "notion_unreachable")])
async def test_access_problems_say_which(status, error):
    notion = FakeNotion({("GET", f"/blocks/{PAGE}/children"): NotionError(status, "nope")})
    with pytest.raises(SetupProblem) as caught:
        await async_find_or_create(notion, PAGE)
    assert caught.value.error == error


@pytest.mark.parametrize("text", [
    "https://www.notion.so/Coffee-Lab-0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    "https://app.notion.com/p/0f1e2d3c4b5a69788796a5b4c3d2e1f0?pvs=204",
    "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
])
def test_a_page_is_found_from_a_link_or_an_id(text):
    assert page_id_from(text) == "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def test_something_that_is_not_a_page_is_not_guessed():
    assert page_id_from("my coffee page") == ""


# ── Mapping ──────────────────────────────────────────────────────────────────


def _page_from(props, page_id="p1", **extra):
    """What Notion returns for properties we sent, near enough to read back."""
    out = {}
    for name, value in props.items():
        if "title" in value or "rich_text" in value:
            key = "title" if "title" in value else "rich_text"
            out[name] = {key: [{"plain_text": v["text"]["content"]} for v in value[key]]}
        else:
            out[name] = value
    return {"id": page_id, "properties": out, **extra}


def test_a_bag_round_trips():
    values = {"name": "Kenya", "status": "open", "tracked": True, "remaining_g": 180.0,
              "bag_size_g": 250.0, "roaster": "R", "country": "Kenya", "region": "Nyeri",
              "process": "Washed", "roaster_notes": "berry", "opened_on": "2026-09-20"}
    bean = bean_from_page(_page_from(bean_properties(values)))
    assert {k: getattr(bean, k) for k in values} == values


def test_a_bag_with_no_tracking_set_is_untracked():
    assert bean_from_page({"id": "p", "properties": {}}).tracked is False


def test_a_brew_round_trips_in_the_database_s_vocabulary():
    brew = Brew(id="", brewed_at="2026-09-26T07:00:00+00:00", recorded_at="", dose_g=18.0,
                brewer=None, bean_id="bag-1", water_ml=288.0, dripper="xPod", recipe="K",
                outcome="presumed", settings={"grind": 55, "ratio": 16.0}, review=Review("no_bag"))
    props = brew_properties(brew)
    assert props["Brewer"]["select"]["name"] == "Other"
    assert props["Dripper"]["select"]["name"] == "XPod"
    assert props["Outcome"]["select"]["name"] == "Presumed"
    assert props["Needs Review"]["checkbox"] is True
    back = brew_from_page(_page_from(props, created_time="2026-09-26T07:01:00Z"))
    assert (back.brewer, back.dripper, back.outcome, back.bean_id) == (None, "xPod", "presumed", "bag-1")
    assert back.settings == {"grind": "55", "ratio": 16.0} and back.review is not None


# ── The store ────────────────────────────────────────────────────────────────


async def test_a_select_option_the_database_lacks_is_added_before_writing():
    notion = FakeNotion({
        ("GET", "/databases/b"): {"properties": {"Process": {"type": "select", "select": {"options": [{"name": "Washed"}]}},
                                                 "Status": {"type": "select", "select": {"options": [{"name": "Unopened"}]}},
                                                 "Inventory Tracking": {"type": "select", "select": {"options": [{"name": "Untracked"}]}}}},
        ("POST", "/pages"): lambda body: {"id": "new", "properties": {}},
    })
    store = NotionStore(notion, Databases("b", "r"))
    await store.async_add_bean(name="Kenya", process="Carbonic")
    patch_call = [c for c in notion.calls if c[0] == "PATCH"][0]
    options = patch_call[2]["properties"]["Process"]["select"]["options"]
    assert {"name": "Carbonic"} in options and {"name": "Washed"} in options
    methods = [c[0] for c in notion.calls]
    assert methods.index("PATCH") < methods.index("POST"), "the option exists before the page"


async def test_a_page_from_another_database_is_not_a_bag():
    notion = FakeNotion({("GET", "/pages/x"): {"id": "x", "parent": {"database_id": "elsewhere"}, "properties": {}}})
    with pytest.raises(UnknownBean):
        await NotionStore(notion, Databases("b", "r")).async_get_bean("x")


async def test_notion_failing_is_a_translated_error():
    notion = FakeNotion({("POST", "/databases/r/query"): NotionError(502, "bad gateway")})
    with pytest.raises(HomeAssistantError) as caught:
        await NotionStore(notion, Databases("b", "r")).async_list_brews()
    assert caught.value.translation_key == "notion_failed"


async def test_brews_since_a_moment_are_exact_though_the_query_reaches_back_a_day():
    pages = [
        {"id": "a", "properties": {"Brewed At": {"date": {"start": "2026-09-25T10:00:00Z"}}}},
        {"id": "b", "properties": {"Brewed At": {"date": {"start": "2026-09-23T22:00:00Z"}}}},
    ]
    notion = FakeNotion({("POST", "/databases/r/query"): {"results": pages}})
    since = datetime(2026, 9, 24, tzinfo=timezone.utc)
    brews = await NotionStore(notion, Databases("b", "r")).async_list_brews(since=since)
    assert [b.id for b in brews] == ["a"]
    body = notion.calls[0][2]
    assert body["filter"]["or"][0]["date"]["on_or_after"] == "2026-09-23"


def test_why_a_brew_needs_review_and_its_run_id_reach_notion():
    brew = Brew(id="", brewed_at="2026-09-26T07:00:00Z", recorded_at="", dose_g=18.0,
                run_id="run-9", review=Review("more_than_left", {"grams": 18.0}))
    back = brew_from_page(_page_from(brew_properties(brew)))
    assert back.review.reason == "more_than_left" and back.run_id == "run-9"


def test_a_finished_bag_keeps_the_day():
    bean = bean_from_page(_page_from(bean_properties({"name": "K", "finished_on": "2026-09-26"})))
    assert bean.finished_on == "2026-09-26"


async def test_a_run_is_looked_up_by_its_id():
    notion = FakeNotion({("POST", "/databases/r/query"): {"results": [{"id": "x"}]}})
    assert await NotionStore(notion, Databases("b", "r")).async_has_run("run-9")
    body = notion.calls[0][2]
    assert body["filter"] == {"property": "Run ID", "rich_text": {"equals": "run-9"}}


async def test_databases_inside_a_column_are_found_but_not_those_in_sub_pages():
    column = {"type": "column_list", "id": "cols", "has_children": True}
    sub_page = {"type": "child_page", "id": "sub", "has_children": True}
    notion = FakeNotion({
        ("GET", f"/blocks/{PAGE}/children"): {"results": [column, sub_page]},
        ("GET", "/blocks/cols/children"): {"results": [{"type": "column", "id": "c1", "has_children": True}]},
        ("GET", "/blocks/c1/children"): {"results": [_child("Coffee Beans", "b"), _child("Brews", "r")]},
        ("GET", "/databases/b"): _schema(BEAN_FIELDS),
        ("GET", "/databases/r"): _schema(BREW_FIELDS),
    })
    assert await async_find_or_create(notion, PAGE) == Databases("b", "r")
    assert not [c for c in notion.calls if c[1].startswith("/blocks/sub")]

