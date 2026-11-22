"""Where each bag's story and the big story have reached, across brews."""
from __future__ import annotations

from custom_components.xbloom.stories.memory import StoryMemory


class _Store:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data


async def _memory(data=None):
    memory = StoryMemory(_Store(data))
    await memory.async_load()
    return memory


async def _brew(memory, bean="bag-1", **kw):
    args = {"told": [], "facts": [], "big_story_part_told": False, "country": None, "teaser": None}
    args.update(kw)
    await memory.async_record_brew(bean, **args)


async def test_a_new_bag_opens_the_next_big_story_chapter():
    memory = await _memory()
    assert memory.big_story_position("bag-1") == (0, 0)
    await _brew(memory, "bag-1", big_story_part_told=True)
    assert memory.big_story_position("bag-2") == (1, 0)


async def test_the_same_bag_again_keeps_the_chapter_and_advances_the_part():
    memory = await _memory()
    await _brew(memory, "bag-1", big_story_part_told=True)
    assert memory.big_story_position("bag-1") == (0, 1)


async def test_a_brew_without_a_bag_moves_no_chapter():
    memory = await _memory()
    await _brew(memory, None, big_story_part_told=True)
    assert memory.big_story_position(None) == (0, 1)


async def test_told_parts_are_remembered_per_bag():
    memory = await _memory()
    await _brew(memory, "bag-1", told=["bag.intro.0"])
    assert memory.bag("bag-1") == {"chapter": 1, "told": ["bag.intro.0"]}
    assert memory.bag("bag-2") == {"chapter": 0, "told": []}


async def test_facts_seen_and_the_teaser_and_brews_are_kept():
    memory = await _memory()
    teaser = {"kind": "fact", "key": "water", "text": "Next: water."}
    await _brew(memory, "bag-1", facts=["water.plain"], teaser=teaser)
    assert memory.facts_seen == {"water.plain"} and memory.teaser == teaser and memory.brews == 1


async def test_a_country_brewed_is_marked_tasted():
    memory = await _memory()
    await _brew(memory, "bag-1", country="Ethiopia")
    await _brew(memory, "bag-2", country="ethiopia")
    assert memory.big_story()["tasted"] == ["Ethiopia"]


async def test_memory_survives_a_reload():
    store = _Store()
    memory = StoryMemory(store)
    await memory.async_load()
    await _brew(memory, "bag-1", told=["bag.intro.0"], country="Kenya")
    again = StoryMemory(store)
    await again.async_load()
    assert again.bag("bag-1")["told"] == ["bag.intro.0"] and again.big_story()["tasted"] == ["Kenya"]


async def test_a_forgotten_bag_starts_its_story_again():
    memory = await _memory()
    await _brew(memory, "bag-1", told=["bag.intro.0"])
    await memory.async_forget_bag("bag-1")
    assert memory.bag("bag-1") == {"chapter": 0, "told": []}
