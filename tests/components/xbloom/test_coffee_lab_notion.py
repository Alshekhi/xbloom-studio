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
              "process": "Washed", "varietal": "SL28, SL34", "roast": "Light Roast",
              "roaster_notes": "berry", "opened_on": "2026-09-20",
              "roast_date": "2026-09-12", "producer": "Gatomboya Cooperative", "altitude_m": 1800.0,
              "altitude_max_m": 2000.0, "product_url": "https://shop.example/p/1"}
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


async def test_the_origin_columns_a_database_lacks_are_added_before_writing():
    notion = FakeNotion({
        ("GET", "/databases/b"): {"properties": {
            "Status": {"type": "select", "select": {"options": [{"name": "Unopened"}]}},
            "Inventory Tracking": {"type": "select", "select": {"options": [{"name": "Untracked"}]}},
        }},
        ("POST", "/pages"): lambda body: {"id": "new", "properties": body["properties"]},
    })
    store = NotionStore(notion, Databases("b", "r"))
    await store.async_add_bean(name="Kenya", status="unopened", roast_date="2026-09-12",
                               producer="Gatomboya Cooperative", altitude_m=1800.0,
                               altitude_max_m=2000.0)
    added = {}
    for call in notion.calls:
        if call[0] == "PATCH":
            added.update(call[2]["properties"])
    assert added["Roast Date"] == {"date": {}}
    assert added["Producer"] == {"rich_text": {}}
    assert added["Altitude m"] == {"number": {}}
    assert added["Altitude Max m"] == {"number": {}}


async def test_each_variety_is_an_option_of_the_variety_column_added_before_writing():
    notion = FakeNotion({
        ("GET", "/databases/b"): {"properties": {
            "Variety": {"type": "multi_select", "multi_select": {"options": [{"name": "SL28"}]}},
            "Status": {"type": "select", "select": {"options": [{"name": "Unopened"}]}},
            "Inventory Tracking": {"type": "select", "select": {"options": [{"name": "Untracked"}]}},
        }},
        ("POST", "/pages"): lambda body: {"id": "new", "properties": body["properties"]},
    })
    store = NotionStore(notion, Databases("b", "r"))
    await store.async_add_bean(name="Kenya", status="unopened", varietal="SL28, SL34")
    patch_call = [c for c in notion.calls if c[0] == "PATCH"][0]
    assert patch_call[2]["properties"] == {
        "Variety": {"multi_select": {"options": [{"name": "SL28"}, {"name": "SL34"}]}},
    }
    post = [c for c in notion.calls if c[0] == "POST"][0]
    assert post[2]["properties"]["Variety"] == {"multi_select": [{"name": "SL28"}, {"name": "SL34"}]}


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
    dated = notion.calls[0][2]["filter"]["or"][0]["and"]
    assert {"property": "Brewed At", "date": {"on_or_after": "2026-09-23"}} in dated


async def test_brews_of_one_bag_are_asked_of_notion_by_their_bag():
    notion = FakeNotion({("POST", "/databases/r/query"): {"results": []}})
    store = NotionStore(notion, Databases("b", "r"))
    await store.async_list_brews(bean_id="bag-1")
    assert notion.calls[0][2]["filter"] == {"property": "Bean", "relation": {"contains": "bag-1"}}
    await store.async_list_brews(bean_id="bag-1", since=datetime(2026, 9, 24, tzinfo=timezone.utc))
    dated = notion.calls[1][2]["filter"]["or"][0]["and"]
    assert {"property": "Bean", "relation": {"contains": "bag-1"}} in dated
    assert {"property": "Brewed At", "date": {"on_or_after": "2026-09-23"}} in dated


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



# ── Rating a brew: only a row of this Brews database is written ──────────────

BREWS_DB = "11111111222233334444555555555555"
ROW = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _rating_store(page):
    from custom_components.xbloom.coffee_lab.notion import Databases, NotionStore

    notion = FakeNotion({
        ("GET", f"/pages/{ROW}"): page,
        ("GET", f"/databases/{BREWS_DB}"): {"properties": {"Rating": {"type": "number"}}},
        ("PATCH", f"/pages/{ROW}"): {"id": ROW, "properties": {"Rating": {"number": 3}}},
    })
    return notion, NotionStore(notion, Databases("b", BREWS_DB))


@pytest.mark.parametrize("bad_id", ["", "../databases/x", "beans", ROW + "/archive"])
async def test_a_brew_id_that_is_not_a_page_id_is_never_sent(bad_id):
    from custom_components.xbloom.coffee_lab.store import UnknownBrew

    notion, store = _rating_store({})
    with pytest.raises(UnknownBrew):
        await store.async_rate_brew(bad_id, rating=3)
    assert notion.calls == []


async def test_a_page_outside_the_brews_database_is_not_written():
    from custom_components.xbloom.coffee_lab.store import UnknownBrew

    notion, store = _rating_store({"id": ROW, "parent": {"database_id": "a-bag-database"}})
    with pytest.raises(UnknownBrew):
        await store.async_rate_brew(ROW, rating=3)
    assert not any(method == "PATCH" for method, _, _ in notion.calls)


async def test_a_row_of_the_brews_database_is_rated():
    notion, store = _rating_store({"id": ROW, "parent": {"database_id": "11111111-2222-3333-4444-555555555555"}})
    brew = await store.async_rate_brew(ROW, rating=3)
    assert brew.rating == 3
    assert ("PATCH", f"/pages/{ROW}", {"properties": {"Rating": {"number": 3}}}) in notion.calls


def test_a_comma_never_reaches_a_single_choice_column():
    props = bean_properties({"process": "Natural, Anaerobic", "roast": "light,"})
    assert props["Process"] == {"select": {"name": "Natural / Anaerobic"}}
    assert props["Roast"] == {"select": {"name": "light"}}


async def test_a_column_of_another_type_is_refused_never_changed():
    notion = FakeNotion({
        ("GET", "/databases/b"): {"properties": {
            "Roast": {"type": "rich_text", "rich_text": {}},
            "Status": {"type": "select", "select": {"options": [{"name": "Unopened"}]}},
            "Inventory Tracking": {"type": "select", "select": {"options": [{"name": "Untracked"}]}},
        }},
    })
    store = NotionStore(notion, Databases("b", "r"))
    with pytest.raises(HomeAssistantError) as caught:
        await store.async_add_bean(name="Kenya", status="unopened", roast="Light Roast")
    assert caught.value.translation_key == "notion_column_type"
    assert not [c for c in notion.calls if c[0] in ("PATCH", "POST")], "nothing written"


def test_a_cleared_shop_page_is_written_as_empty():
    assert bean_properties({"product_url": ""}) == {"Product URL": {"url": None}}



def _depth(node) -> int:
    """How deeply compound filters nest: Notion refuses more than two levels."""
    if isinstance(node, dict) and ("and" in node or "or" in node):
        return 1 + max((_depth(c) for c in node.get("and", node.get("or"))), default=0)
    return 0


async def test_every_brew_filter_stays_within_notions_two_levels():
    notion = FakeNotion({("POST", "/databases/r/query"): {"results": []}})
    store = NotionStore(notion, Databases("b", "r"))
    since, until = datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    for kw in ({"since": since}, {"until": until}, {"since": since, "until": until},
               {"since": since, "until": until, "bean_id": "bag-1"}, {"bean_id": "bag-1", "since": since}):
        await store.async_list_brews(**kw)
        assert _depth(notion.calls[-1][2]["filter"]) <= 2, kw


async def test_brews_in_a_window_are_exact_and_the_limit_counts_only_them():
    pages = [{"id": i, "properties": {"Brewed At": {"date": {"start": d}}}}
             for i, d in (("late", "2026-10-01T05:00:00Z"), ("b", "2026-09-30T10:00:00Z"),
                          ("c", "2026-09-20T10:00:00Z"), ("early", "2026-08-31T22:00:00Z"))]
    notion = FakeNotion({("POST", "/databases/r/query"): {"results": pages}})
    brews = await NotionStore(notion, Databases("b", "r")).async_list_brews(
        since=datetime(2026, 9, 1, tzinfo=timezone.utc), until=datetime(2026, 10, 1, tzinfo=timezone.utc), limit=1)
    assert [b.id for b in brews] == ["b"]


async def test_a_window_ending_now_still_asks_notion_for_the_limit():
    from datetime import timedelta
    asked = []

    class Counting(FakeNotion):
        async def query(self, database_id, body, limit=None):
            asked.append(limit)
            return await super().query(database_id, body, limit)

    store = NotionStore(Counting({("POST", "/databases/r/query"): {"results": []}}), Databases("b", "r"))
    now = datetime.now(timezone.utc)
    await store.async_list_brews(since=now - timedelta(days=30), until=now + timedelta(minutes=1), limit=50)
    await store.async_list_brews(since=now - timedelta(days=60), until=now - timedelta(days=30), limit=50)
    assert asked == [50, None]
