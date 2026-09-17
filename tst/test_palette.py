import json
import queue
import threading
from http.client import HTTPConnection
from unittest import mock

import pytest

import fbmserve


@pytest.fixture
def api(tmp_path):
    state = fbmserve.AppState('solid', state_file=tmp_path / 'state.json')
    commands = queue.Queue()
    server = fbmserve.create_server('127.0.0.1', 0, 'web', 'effects', state, commands)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=5)

    def request(method, payload=None):
        connection.request(method, '/api/state',
                           body=None if payload is None else json.dumps(payload),
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    yield request, state, commands
    connection.close()
    server.shutdown()
    server.server_close()
    thread.join()


def test_palette_api_partial_update_and_persistence(api):
    request, state, commands = api
    status, before = request('GET')
    assert status == 200
    assert 'hue' not in before
    status, after = request('POST', {
        'color2': [0.125, 0.5, 0], 'color3': [0, 0, 0], 'speed': 1.75})
    assert status == 200
    assert after['color1'] == before['color1']
    assert after['color2'] == [0.125, 0.5, 0]
    assert after['color3'] == [0, 0, 0]
    assert after['speed'] == 1.75
    assert commands.get_nowait()['values'] == {
        'color2': [0.125, 0.5, 0], 'color3': [0, 0, 0], 'speed': 1.75}
    saved = fbmserve.load_state_file(state.state_file, {'solid'}, {'default'})
    assert saved['color2'] == after['color2']
    assert saved['color3'] == after['color3']
    assert saved['speed'] == 1.75


@pytest.mark.parametrize('value', [None, '#ff0000', [], [1, 0], [1, 0, 0, 0],
                                  [True, 0, 0], ['1', 0, 0], [-0.1, 0, 0],
                                  [1.1, 0, 0], [float('nan'), 0, 0],
                                  [float('inf'), 0, 0], [{}, 0, 0]])
def test_invalid_color_update_is_atomic(api, value):
    request, state, commands = api
    before = state.snapshot()
    status, body = request('POST', {'color1': [0, 0, 0], 'color2': value})
    assert status == 400
    assert 'error' in body
    assert state.snapshot() == before
    assert commands.empty()


def test_hue_api_is_explicitly_rejected(api):
    request, _, _ = api
    assert request('POST', {'hue': 0.5})[0] == 400


@pytest.mark.parametrize(('value', 'expected'), [(-1, 0), (0, 0), (2.5, 2.5), (5, 4)])
def test_speed_api_clamps_to_supported_range(api, value, expected):
    request, _, _ = api
    status, state = request('POST', {'speed': value})
    assert status == 200
    assert state['speed'] == expected


@pytest.mark.parametrize('value', [None, True, 'fast', float('nan'), float('inf')])
def test_invalid_speed_is_rejected(api, value):
    request, state, commands = api
    before = state.snapshot()
    status, _ = request('POST', {'speed': value})
    assert status == 400
    assert state.snapshot() == before
    assert commands.empty()


def test_snapshot_colors_cannot_mutate_state():
    color = [0.2, 0.4, 0.6]
    state = fbmserve.AppState('solid', color1=color)
    color[0] = 1
    snapshot = state.snapshot()
    snapshot['color1'][1] = 1
    assert state.snapshot()['color1'] == [0.2, 0.4, 0.6]


def test_autoplay_preserves_palette():
    state = fbmserve.AppState('solid', autoplay=True,
                             autoplay_effects=['solid', 'plasma'],
                             color1=[0.2, 0.5, 0.8], color2=[0, 0, 0])
    renderer = fbmserve.InputRenderer(
        'effects', [{'id': 'solid'}, {'id': 'plasma'}], 32, 32, state, queue.Queue())
    before = state.snapshot()
    renderer.next_autoplay = 0
    renderer.apply_autoplay()
    after = state.snapshot()
    assert after['effect'] == 'plasma'
    for key in ('color1', 'color2', 'color3'):
        assert after[key] == before[key]


def test_renderer_passes_palette_and_separate_brightness():
    state = fbmserve.AppState('solid', color1=[0.2, 0.4, 0.6], brightness=0.3)
    matrix = mock.Mock()
    renderer = fbmserve.InputRenderer('effects', [], 32, 32, state, queue.Queue(),
                                     matrix=matrix)
    renderer.current_effect = 'solid'
    renderer.current_led_effect = 'default'
    renderer.quad = mock.Mock()
    renderer.render()
    snapshot = state.snapshot()
    renderer.quad.set_params.assert_called_once_with(
        mock.ANY, snapshot['color1'], snapshot['color2'], snapshot['color3'])
    matrix.ledbuffer.set_params.assert_called_once_with(mock.ANY, 0.3)


def test_speed_integrates_without_phase_jumps_and_zero_freezes():
    state = fbmserve.AppState('solid', speed=0.5)
    renderer = fbmserve.InputRenderer('effects', [], 32, 32, state, queue.Queue())
    renderer.current_effect = 'solid'
    renderer.quad = mock.Mock()
    renderer.last_effect_tick = 10

    with mock.patch.object(fbmserve.time, 'monotonic', return_value=12):
        renderer.render()
    assert renderer.quad.set_params.call_args.args[0] == 1

    state.update(speed=2)
    with mock.patch.object(fbmserve.time, 'monotonic', return_value=13):
        renderer.render()
    assert renderer.quad.set_params.call_args.args[0] == 3

    state.update(speed=0)
    with mock.patch.object(fbmserve.time, 'monotonic', return_value=20):
        renderer.render()
    assert renderer.quad.set_params.call_args.args[0] == 3


def test_color_cli_parsing():
    assert fbmserve.parse_color('0,0.25,1') == [0, 0.25, 1]
