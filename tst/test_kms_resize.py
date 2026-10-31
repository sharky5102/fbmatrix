"""KMS lifecycle tests without requiring a DRM device."""
import sys
from unittest import mock

import pytest

if sys.platform == 'win32':
    pytest.skip('KMS is Linux-only', allow_module_level=True)

import kms
from kms import KMSDisplay, ffi


@pytest.fixture
def display():
    with mock.patch.multiple(kms, drm=mock.DEFAULT, gbm=mock.DEFAULT,
                             egl=mock.DEFAULT, gl=mock.DEFAULT) as api:
        d = object.__new__(KMSDisplay)
        d.closed = False
        d.fd = 10
        d.width, d.height = 840, 2
        d.mode = d._create_mode(840, 2, 27000, 1, 1, 48)
        d.mode_blob_id = 20
        d.gbm_device = ffi.cast('struct gbm_device *', 1)
        d.gbm_surface = ffi.cast('struct gbm_surface *', 2)
        d.egl_display = ffi.cast('EGLDisplay', 3)
        d.egl_surface = ffi.cast('EGLSurface', 4)
        d.egl_context = ffi.cast('EGLContext', 5)
        d.egl_config = ffi.cast('EGLConfig', 6)
        d.current_bo = ffi.cast('struct gbm_bo *', 7)
        d.framebuffers = {7: 30}
        d.format = kms.GBM_FORMAT_XRGB8888
        d.timing_frames = 3
        d.egl_swap_time = 1
        d.kms_commit_time = 2
        api['gl'].glGetIntegerv.return_value = 77
        api['gbm'].gbm_surface_create.return_value = ffi.cast('struct gbm_surface *', 8)
        api['gbm'].gbm_surface_lock_front_buffer.return_value = ffi.cast('struct gbm_bo *', 9)
        api['egl'].eglCreatePlatformWindowSurface.return_value = ffi.cast('EGLSurface', 10)

        def create_blob(fd, mode, size, result):
            result[0] = 21
            return 0
        api['drm'].drmModeCreatePropertyBlob.side_effect = create_blob
        d._validate_surface_size = mock.Mock()
        d._modeset = mock.Mock()
        d._atomic_present = mock.Mock()

        def framebuffer(bo):
            d.framebuffers[int(ffi.cast('size_t', bo))] = 31
            return 31
        d._framebuffer_for_bo = mock.Mock(side_effect=framebuffer)
        yield d, api


def test_resize_preserves_context_and_releases_old_scanout_after_commit(display):
    d, api = display
    events = []
    old_gbm, old_egl, old_bo = d.gbm_surface, d.egl_surface, d.current_bo
    context = d.egl_context
    d._modeset.side_effect = lambda fb: events.append('modeset')
    api['gbm'].gbm_surface_release_buffer.side_effect = lambda *args: events.append('release')
    d.set_mode(840, 5, 27000, 1, 1, 48)
    assert events == ['modeset', 'release']
    assert (d.width, d.height, d.mode.vdisplay) == (840, 5, 5)
    assert d.egl_context == context
    assert d.current_bo == ffi.cast('struct gbm_bo *', 9)
    assert d.framebuffers == {9: 31}
    assert d.mode_blob_id == 21
    d._modeset.assert_called_once_with(31)
    d._atomic_present.assert_not_called()
    api['gbm'].gbm_surface_release_buffer.assert_called_once_with(old_gbm, old_bo)
    api['gbm'].gbm_surface_destroy.assert_called_once_with(old_gbm)
    api['egl'].eglDestroySurface.assert_called_once_with(d.egl_display, old_egl)
    api['drm'].drmModeRmFB.assert_called_once_with(10, 30)
    api['drm'].drmModeDestroyPropertyBlob.assert_called_once_with(10, 20)
    api['egl'].eglDestroyContext.assert_not_called()
    api['egl'].eglTerminate.assert_not_called()
    api['drm'].drmDropMaster.assert_not_called()
    assert (d.timing_frames, d.egl_swap_time, d.kms_commit_time) == (0, 0, 0)
    assert api['gl'].glBindFramebuffer.call_args == mock.call(kms.gl.GL_FRAMEBUFFER, 77)
    api['gl'].glPopAttrib.assert_called_once()


def test_unchanged_mode_does_not_allocate_or_commit(display):
    d, api = display
    d.set_mode(840, 2, 27000, 1, 1, 48)
    api['gbm'].gbm_surface_create.assert_not_called()
    api['drm'].drmModeCreatePropertyBlob.assert_not_called()
    d._modeset.assert_not_called()


@pytest.mark.parametrize('stage', [
    'blob', 'gbm', 'egl', 'make_current', 'size', 'swap_interval', 'swap', 'lock', 'fb', 'modeset',
])
def test_failed_resize_restores_previous_mode_and_keeps_old_resources(display, stage):
    d, api = display
    old = (d.width, d.height, d.mode, d.mode_blob_id, d.gbm_surface,
           d.egl_surface, d.current_bo, d.framebuffers)
    if stage == 'blob':
        api['drm'].drmModeCreatePropertyBlob.side_effect = None
        api['drm'].drmModeCreatePropertyBlob.return_value = -1
    elif stage == 'gbm':
        api['gbm'].gbm_surface_create.return_value = ffi.NULL
    elif stage == 'egl':
        api['egl'].eglCreatePlatformWindowSurface.return_value = ffi.NULL
    elif stage == 'make_current':
        api['egl'].eglMakeCurrent.return_value = False
    elif stage == 'size':
        d._validate_surface_size.side_effect = RuntimeError('size')
    elif stage == 'swap_interval':
        api['egl'].eglSwapInterval.return_value = False
    elif stage == 'swap':
        api['egl'].eglSwapBuffers.return_value = False
    elif stage == 'lock':
        api['gbm'].gbm_surface_lock_front_buffer.return_value = ffi.NULL
    elif stage == 'fb':
        d._framebuffer_for_bo.side_effect = RuntimeError('fb')
    else:
        d._modeset.side_effect = RuntimeError('modeset')
    api['egl'].eglGetError.return_value = 0x3000
    with pytest.raises(RuntimeError):
        d.set_mode(840, 5, 27000, 1, 1, 48)
    assert (d.width, d.height, d.mode, d.mode_blob_id, d.gbm_surface,
            d.egl_surface, d.current_bo, d.framebuffers) == old
    assert mock.call(old[4], old[6]) not in api['gbm'].gbm_surface_release_buffer.call_args_list
    assert mock.call(old[4]) not in api['gbm'].gbm_surface_destroy.call_args_list
    assert mock.call(d.egl_display, old[5]) not in api['egl'].eglDestroySurface.call_args_list
    assert mock.call(10, 20) not in api['drm'].drmModeDestroyPropertyBlob.call_args_list
    assert mock.call(10, 30) not in api['drm'].drmModeRmFB.call_args_list
    if stage in ('fb', 'modeset'):
        api['gbm'].gbm_surface_release_buffer.assert_called_once_with(
            ffi.cast('struct gbm_surface *', 8), ffi.cast('struct gbm_bo *', 9))
    if stage == 'modeset':
        api['drm'].drmModeRmFB.assert_called_once_with(10, 31)
    api['gl'].glPopAttrib.assert_called_once()
    # A failed attempt must not prevent a subsequent valid mode change.
    def retry_blob(fd, mode, size, ptr):
        ptr[0] = 22
        return 0
    api['drm'].drmModeCreatePropertyBlob.side_effect = retry_blob
    api['gbm'].gbm_surface_create.return_value = ffi.cast('struct gbm_surface *', 8)
    api['egl'].eglCreatePlatformWindowSurface.return_value = ffi.cast('EGLSurface', 10)
    api['egl'].eglMakeCurrent.return_value = True
    api['egl'].eglSwapInterval.return_value = True
    api['egl'].eglSwapBuffers.return_value = True
    api['gbm'].gbm_surface_lock_front_buffer.return_value = ffi.cast('struct gbm_bo *', 9)
    d._validate_surface_size.side_effect = None
    d._modeset.side_effect = None
    d._framebuffer_for_bo.side_effect = lambda bo: 32
    d.set_mode(840, 1, 27000, 1, 1, 48)
    assert (d.width, d.height) == (840, 1)


def test_unrecoverable_surface_loss_propagates_out_of_command_error_handling(display):
    d, api = display
    d._modeset.side_effect = RuntimeError('mode rejected')
    api['egl'].eglMakeCurrent.side_effect = [True, False]
    with pytest.raises(kms.KMSContextError, match='restore previous'):
        d.set_mode(840, 5, 27000, 1, 1, 48)
    # This is deliberately not a recoverable layout command RuntimeError.
    assert not issubclass(kms.KMSContextError, RuntimeError)
    api['egl'].eglDestroySurface.assert_not_called()
