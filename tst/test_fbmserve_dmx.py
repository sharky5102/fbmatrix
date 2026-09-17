import queue
from unittest import mock

import pytest

import fbmserve


EFFECTS = [{'id': 'first'}, {'id': 'middle'}, {'id': 'last'}]


def dmx_frame(*channels):
    return bytes([0, *channels])


def test_dmx_profile_mapping():
    frame = dmx_frame(
        255, 255, 128,
        255, 128, 0,
        0, 64, 255,
        1, 2, 3,
    )

    values = fbmserve.dmx_values(frame, 1, EFFECTS)

    assert values['brightness'] == 1
    assert values['effect'] == 'last'
    assert values['speed'] == pytest.approx(128 / 255 * 4)
    assert values['color1'] == pytest.approx([1, 128 / 255, 0])
    assert values['color2'] == pytest.approx([0, 64 / 255, 1])
    assert values['color3'] == pytest.approx([1 / 255, 2 / 255, 3 / 255])


def test_dmx_profile_uses_one_based_start_address():
    frame = dmx_frame(99, 99, *([0] * 12))
    values = fbmserve.dmx_values(frame, 3, EFFECTS)
    assert values['brightness'] == 0
    assert values['effect'] == 'first'


def test_dmx_profile_rejects_nonzero_start_code_and_short_frame():
    assert fbmserve.dmx_values(bytes([1] + [0] * 12), 1, EFFECTS) is None
    assert fbmserve.dmx_values(dmx_frame(*([0] * 11)), 1, EFFECTS) is None


def test_renderer_holds_dmx_override_then_returns_to_web_state():
    state = fbmserve.AppState('web', brightness=0.75)
    receiver = mock.Mock()
    receiver.read_dmx_frame.side_effect = [
        dmx_frame(0, 255, 0, *([0] * 9)),
        None,
        None,
    ]
    renderer = fbmserve.InputRenderer(
        'effects', EFFECTS, 32, 32, state, queue.Queue(),
        dmx_receiver=receiver, dmx_hold=30,
    )
    snapshot = state.snapshot()
    renderer.apply_dmx(snapshot, 10)
    assert snapshot['effect'] == 'last'
    assert snapshot['brightness'] == 0

    snapshot = state.snapshot()
    renderer.apply_dmx(snapshot, 40)
    assert snapshot['effect'] == 'last'

    snapshot = state.snapshot()
    renderer.apply_dmx(snapshot, 40.001)
    assert snapshot['effect'] == 'web'
    assert snapshot['brightness'] == 0.75


def test_dmx_does_not_override_ndi_input_mode_or_source():
    state = fbmserve.AppState(
        'web', input_mode='ndi', ndi_source='Configured source', brightness=0.75)
    receiver = mock.Mock()
    receiver.read_dmx_frame.return_value = dmx_frame(
        0, 255, 255, *([255] * 9))
    renderer = fbmserve.InputRenderer(
        'effects', EFFECTS, 32, 32, state, queue.Queue(),
        dmx_receiver=receiver,
    )

    snapshot = state.snapshot()
    renderer.apply_dmx(snapshot, 10)

    assert snapshot['input_mode'] == 'ndi'
    assert snapshot['ndi_source'] == 'Configured source'
    assert snapshot['brightness'] == 0
