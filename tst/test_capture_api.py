import json
import queue
import threading
from http.client import HTTPConnection
from urllib.parse import parse_qs, urlparse

import pytest

import fbmserve


@pytest.fixture
def capture_api(tmp_path):
    state = fbmserve.AppState(
        'solid', input_mode='setup', state_file=tmp_path / 'state.json')
    server = fbmserve.create_server(
        '127.0.0.1', 0, 'web', 'effects', state, queue.Queue())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=5)

    def request(method, path, payload=None):
        body = None if payload is None else json.dumps(payload)
        headers = {} if body is None else {'Content-Type': 'application/json'}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        if response.getheader('Content-Type', '').startswith('application/json'):
            raw = json.loads(raw)
        return response.status, raw, response.getheader('Content-Type')

    request.server = server
    yield request, state
    connection.close()
    server.shutdown()
    server.server_close()
    thread.join()


def create_session(request, pixels=2):
    status, body, _ = request('POST', '/api/capture-sessions', {
        'pixels': pixels, 'origin': 'http://halo.local'})
    assert status == 200
    return body


def test_capture_session_returns_upload_deep_link_and_qr_url(capture_api):
    request, _ = capture_api
    session = create_session(request, pixels=250)

    assert session['upload_url'].startswith('http://halo.local/api/capture/')
    query = parse_qs(urlparse(session['deep_link']).query)
    assert query['pixels'] == ['250']
    assert query['target'] == [session['upload_url']]
    assert session['qr_url'] == '/api/capture-sessions/%s/qr.svg' % session['token']

    status, qr, content_type = request('GET', session['qr_url'])
    assert status == 200
    assert content_type == 'image/svg+xml'
    assert qr.startswith(b'<svg ')


@pytest.mark.parametrize('payload', [
    {'pixels': 0, 'origin': 'http://halo.local'},
    {'pixels': 28001, 'origin': 'http://halo.local'},
    {'pixels': True, 'origin': 'http://halo.local'},
    {'pixels': 2, 'origin': 'file:///tmp'},
    {'pixels': 2, 'origin': 'http://user@halo.local'},
    {'pixels': 2, 'origin': 'http://halo.local/path'},
])
def test_capture_session_rejects_invalid_parameters(capture_api, payload):
    request, _ = capture_api
    status, body, _ = request('POST', '/api/capture-sessions', payload)
    assert status == 400
    assert 'error' in body


def test_capture_session_only_available_in_setup(capture_api):
    request, state = capture_api
    state.update(input_mode='effect')

    status, body, _ = request('POST', '/api/capture-sessions', {
        'pixels': 2, 'origin': 'http://halo.local'})
    assert status == 409
    assert 'error' in body


def test_capture_upload_saves_layout_once_and_closes_session(capture_api):
    request, state = capture_api
    session = create_session(request)
    layout = [[[0, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 1]]]

    status, body, _ = request('POST', '/api/capture/%s' % session['token'], layout)
    assert status == 200
    assert body['success'] is True
    assert body['restart_required'] is True
    assert state.layout_snapshot() == [
        [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
         (1.0, 0.0, 0.0, 1.0, 0.0, 1.0)]]
    assert fbmserve.load_state_file(
        state.state_file, {'solid'}, {'default'})['layout'] == [
            [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
             (1.0, 0.0, 0.0, 1.0, 0.0, 1.0)]]

    status, body, _ = request('GET', '/api/capture-sessions/%s' % session['token'])
    assert status == 404
    status, body, _ = request('POST', '/api/capture/%s' % session['token'], layout)
    assert status == 404


def test_capture_upload_rejects_invalid_layout_without_changing_state(
        capture_api):
    request, state = capture_api
    original = [[[5, 5, 0, 1, 0, 0]]]
    state.update(layout=original)
    session = create_session(request)

    payload = [[[0, 0, 0]]]
    status, body, _ = request('POST', '/api/capture/%s' % session['token'], payload)
    assert status == 400
    assert 'error' in body
    assert state.layout_snapshot() == [
        [(5.0, 5.0, 0.0, 1.0, 0.0, 0.0)]]


def test_capture_upload_accepts_pixel_count_different_from_phone_selection(
        capture_api):
    request, state = capture_api
    session = create_session(request, pixels=250)
    layout = [[[0, 0, 0, 1, 0, 0]]]

    status, body, _ = request('POST', '/api/capture/%s' % session['token'], layout)

    assert status == 200
    assert body['success'] is True
    assert state.layout_snapshot() == [
        [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0)]]


def test_closing_or_leaving_setup_invalidates_capture_session(capture_api):
    request, _ = capture_api
    closed = create_session(request)
    status, body, _ = request(
        'DELETE', '/api/capture-sessions/%s' % closed['token'])
    assert status == 200
    assert body == {'closed': True}
    status, _, _ = request('GET', closed['qr_url'])
    assert status == 404

    leaving_setup = create_session(request)
    status, _, _ = request('POST', '/api/state', {'input_mode': 'effect'})
    assert status == 200
    status, _, _ = request('GET', '/api/capture-sessions/%s' % leaving_setup['token'])
    assert status == 404


@pytest.mark.parametrize('emulate', [False, True])
@pytest.mark.parametrize('path', ['/api/layout', 'capture'])
def test_layout_updates_are_queued_for_all_string_lengths(
        capture_api, emulate, path):
    from types import SimpleNamespace
    request, state = capture_api
    active = [[[0, 0, 0, 1, 0, 0]] * 2]
    matrix = SimpleNamespace(emulate=emulate, layout=active)
    matrix.can_set_layout = lambda layout: True
    request.server.matrix = matrix
    for length in (3, 3, 2):
        layout = [[[1, 2, 3, 1, 0, 0]] * length]
        url = path
        if path == 'capture':
            session = create_session(request)
            url = '/api/capture/' + session['token']
        status, body, _ = request('POST', url, layout)
        assert status == 200
        assert body['restart_required'] is False
        assert len(state.layout_snapshot()[0]) == length
        _, preview, _ = request('GET', '/api/layout')
        assert preview['restart_required'] is False
        command = request.server.commands.get_nowait()
        assert command['type'] == 'set_layout'
        assert len(command['layout'][0]) == length
