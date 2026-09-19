"""xbloom.brew_standalone pours what the brewer entities say.

It read `number.brew_volume` and four more ids that no entity has ever had —
the entities are named `number.xbloom_studio_…` — so every pour fell back to
120 ml, 3.0 ml/s and 93 °C, whatever the sliders held.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from xbloom import ble

from .test_brew_completion_contract import _Entry, _make_hass, _setup_and_get_handlers


class _Recorder:
    sent: list[tuple[str, bytes]] = []

    def __init__(self, device_or_name, *, on_event=None, **_kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def send_command(self, name, frame, **_kw):
        _Recorder.sent.append((name, frame))
        return True


def _with_brewer_states(hass, states: dict[str, str]):
    fallback = hass.states.get

    def _get(entity_id):
        if entity_id in states:
            state = MagicMock()
            state.state = states[entity_id]
            return state
        return fallback(entity_id)

    hass.states.get = _get
    return hass


async def _pour(states: dict[str, str]):
    _Recorder.sent = []
    hass, entry = _with_brewer_states(_make_hass(), states), _Entry()
    with patch("custom_components.xbloom._resolve_ble_device",
               AsyncMock(return_value=MagicMock(address="AA:BB:CC:DD:EE:FF"))), \
         patch("xbloom.ble.XBloomBleClient", _Recorder):
        handlers = await _setup_and_get_handlers(hass, entry)
        await handlers["brew_standalone"](MagicMock(data={}))
    return _Recorder.sent


_BREWER = {
    "number.xbloom_studio_brew_volume": "30.0",
    "number.xbloom_studio_brew_flow_rate": "3.5",
    "number.xbloom_studio_brew_temperature": "88.0",
    "select.xbloom_studio_brew_pattern": "centered",
    "select.xbloom_studio_water_source": "tap",
}


async def test_the_pour_carries_the_brewer_settings():
    sent = await _pour(_BREWER)
    assert sent == [(
        "brew_standalone",
        ble.build_brewer_standalone_frame(3.5, 30.0, 88.0, 1, 0),
    )]


async def test_the_temperature_ends_are_sent_as_the_machine_reads_them():
    # The slider is the display scale (39 = RT … 96 = BP); the frame takes wire °C.
    sent = await _pour({**_BREWER, "number.xbloom_studio_brew_temperature": "96.0"})
    assert sent[0][1] == ble.build_brewer_standalone_frame(3.5, 30.0, 98.0, 1, 0)


async def test_a_volume_the_machine_cannot_stop_at_is_not_sent():
    sent = await _pour({**_BREWER, "number.xbloom_studio_brew_volume": "0.0"})
    assert sent == []
