import dataclasses
import json
import queue
from unittest import mock

import pytest

import fbmserve
import ndi


def test_uyvy_bgra_color_format_enum_value():
    # NDI enum value zero is BGRX/BGRA, not UYVY/BGRA.
    assert ndi.COLOR_FORMAT_UYVY_BGRA == 1


def test_runtime_requires_explicit_library(monkeypatch):
    monkeypatch.delenv(ndi.LIBRARY_ENV, raising=False)
    with pytest.raises(ndi.NDIUnavailable, match=ndi.LIBRARY_ENV):
        ndi.Runtime()


def test_runtime_reports_load_failure(monkeypatch):
    monkeypatch.setenv(ndi.LIBRARY_ENV, '/missing/libndi.so')
    with pytest.raises(ndi.NDIUnavailable, match='Unable to load'):
        ndi.Runtime()


def test_state_preserves_selected_ndi_source():
    state = fbmserve.AppState('solid', input_mode='ndi', ndi_source='PC (OBS)')
    assert state.snapshot()['ndi_source'] == 'PC (OBS)'


def test_state_preserves_supersample():
    state = fbmserve.AppState('solid', supersample=4.5)
    assert state.snapshot()['supersample'] == 4.5


def test_state_file_persists_user_settings(tmp_path):
    filename = tmp_path / 'state.json'
    state = fbmserve.AppState('solid', state_file=filename)
    state.update(input_mode='ndi', ndi_source='PC (OBS)', brightness=0.4)

    saved = fbmserve.load_state_file(filename, {'solid'}, {'default'})
    assert saved['input_mode'] == 'ndi'
    assert saved['ndi_source'] == 'PC (OBS)'
    assert saved['brightness'] == 0.4
    assert 'error' not in json.loads(filename.read_text())
    assert 'ndi_status' not in json.loads(filename.read_text())


def test_app_state_round_trips_every_persisted_field(tmp_path):
    first_filename = tmp_path / 'first.json'
    first = fbmserve.AppState(
        'plasma', hue=0.25, brightness=0.4, autoplay=True,
        autoplay_interval=17.5, autoplay_effects=['solid', 'plasma'],
        input_mode='ndi', ndi_source='Studio (Camera)',
        led_effect='sparkle', supersample=6.5, state_file=first_filename)
    first.update(error='temporary', ndi_status={'frames': 12})

    saved = fbmserve.load_state_file(
        first_filename, {'solid', 'plasma'}, {'default', 'sparkle'})
    second_filename = tmp_path / 'second.json'
    second = fbmserve.AppState(**saved, state_file=second_filename)

    assert json.loads(second_filename.read_text()) == json.loads(
        first_filename.read_text())
    assert {key: second.snapshot()[key] for key in second.persisted_keys()} == saved
    assert second.snapshot()['error'] is None
    assert second.snapshot()['ndi_status'] == {}


def test_every_app_state_field_has_a_serialization_policy(tmp_path):
    transient = {
        item.name for item in dataclasses.fields(fbmserve.AppState)
        if not item.metadata.get('persist', True)
    }
    assert transient == {'error', 'ndi_status', 'state_file', 'lock'}

    filename = tmp_path / 'state.json'
    state = fbmserve.AppState('solid', state_file=filename)
    assert set(json.loads(filename.read_text())) == set(state.persisted_keys())


def test_corrupt_state_file_is_ignored(tmp_path):
    filename = tmp_path / 'state.json'
    filename.write_text('{not json')
    assert fbmserve.load_state_file(filename, {'solid'}, {'default'}) is None


def test_unavailable_saved_ndi_source_is_retried():
    runtime = mock.Mock()
    state = fbmserve.AppState('solid', input_mode='ndi', ndi_source='Offline')
    renderer = fbmserve.InputRenderer('', [], 16, 16, state, queue.Queue(), runtime)

    with mock.patch.object(fbmserve.ndi, 'Receiver', side_effect=RuntimeError('offline')) as receiver:
        renderer.render()
        renderer.render()

    assert receiver.call_count == 2


def test_renderer_reports_optional_runtime_missing():
    state = fbmserve.AppState('solid', input_mode='ndi', ndi_source='PC (OBS)')
    renderer = fbmserve.InputRenderer('', [], 16, 16, state, queue.Queue())
    renderer.render()
    assert ndi.LIBRARY_ENV in state.snapshot()['error']


def test_switching_back_to_effect_clears_ndi_error():
    state = fbmserve.AppState('solid', input_mode='ndi', ndi_source='PC (OBS)')
    commands = queue.Queue()
    renderer = fbmserve.InputRenderer('', [], 16, 16, state, commands)
    state.update(error='NDI unavailable')
    commands.put({'type': 'set_state', 'values': {'input_mode': 'effect'}})
    renderer.apply_commands()
    assert state.snapshot()['error'] is None


def test_receiver_frees_frame_after_upload():
    ffi = ndi.FFI()
    ffi.cdef(ndi._CDEF)
    pixels = ffi.new('unsigned char[]', bytes([128, 16, 128, 235]))

    class Lib:
        def NDIlib_recv_create_v3(self, settings):
            return ffi.cast('void *', 1)

        def NDIlib_recv_capture_v3(self, receiver, frame, audio, metadata, timeout):
            frame.xres = 2
            frame.yres = 1
            frame.FourCC = ndi.FOURCC_UYVY
            frame.line_stride_in_bytes = 4
            frame.p_data = pixels
            return ndi.FRAME_VIDEO

        NDIlib_recv_free_video_v2 = mock.Mock()
        NDIlib_recv_destroy = mock.Mock()

        def NDIlib_recv_get_performance(self, receiver, total, dropped):
            total.video_frames = 12
            dropped.video_frames = 2

    runtime = mock.Mock(ffi=ffi, lib=Lib())
    receiver = ndi.Receiver(runtime, 'PC (Test Pattern)')
    upload = mock.Mock()
    assert receiver.receive_video(upload, timeout_ms=3)
    assert bytes(upload.call_args.args[0]) == bytes(pixels)[:4]
    upload.assert_called_once_with(mock.ANY, 2, 1, 4)
    runtime.lib.NDIlib_recv_free_video_v2.assert_called_once()
    assert receiver.stats()['frames'] == 12
    assert receiver.stats()['dropped'] == 2
