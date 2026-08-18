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
