import glob
import atexit
import os

# This must precede the first OpenGL import in the process.
os.environ['PYOPENGL_PLATFORM'] = 'egl'

import select
import sys
import time
from contextlib import contextmanager

import OpenGL.GL as gl

from ffi_backend import (
    DRM_CLIENT_CAP_ATOMIC,
    DRM_CLIENT_CAP_UNIVERSAL_PLANES,
    DRM_FORMAT_MOD_INVALID,
    DRM_MODE_ATOMIC_ALLOW_MODESET,
    DRM_MODE_ATOMIC_NONBLOCK,
    DRM_MODE_CONNECTOR_DPI,
    DRM_MODE_FB_MODIFIERS,
    DRM_MODE_FLAG_PHSYNC,
    DRM_MODE_FLAG_PVSYNC,
    DRM_MODE_OBJECT_CONNECTOR,
    DRM_MODE_OBJECT_CRTC,
    DRM_MODE_OBJECT_PLANE,
    DRM_MODE_PAGE_FLIP_EVENT,
    DRM_MODE_TYPE_USERDEF,
    DRM_PLANE_TYPE_PRIMARY,
    EGL_ALPHA_SIZE,
    EGL_BLUE_SIZE,
    EGL_DEPTH_SIZE,
    EGL_GREEN_SIZE,
    EGL_HEIGHT,
    EGL_NATIVE_VISUAL_ID,
    EGL_NONE,
    EGL_OPENGL_API,
    EGL_OPENGL_BIT,
    EGL_PLATFORM_GBM_KHR,
    EGL_RED_SIZE,
    EGL_RENDERABLE_TYPE,
    EGL_SURFACE_TYPE,
    EGL_WIDTH,
    EGL_WINDOW_BIT,
    GBM_BO_USE_RENDERING,
    GBM_BO_USE_SCANOUT,
    GBM_FORMAT_XRGB8888,
    drm,
    egl,
    ffi,
    gbm,
)


class _DRMDevice:
    """Python ownership scopes for libdrm objects allocated from one fd."""

    def __init__(self, fd):
        self.fd = fd

    @staticmethod
    @contextmanager
    def _owned(acquire, release, error):
        pointer = acquire()
        if pointer == ffi.NULL:
            raise RuntimeError(error)
        try:
            yield pointer
        finally:
            release(pointer)

    def resources(self):
        return self._owned(
            lambda: drm.drmModeGetResources(self.fd),
            drm.drmModeFreeResources,
            "Failed to retrieve DRM resources")

    def connector(self, connector_id):
        return self._owned(
            lambda: drm.drmModeGetConnector(self.fd, connector_id),
            drm.drmModeFreeConnector,
            "Failed to retrieve DRM connector %d" % connector_id)

    def encoder(self, encoder_id):
        return self._owned(
            lambda: drm.drmModeGetEncoder(self.fd, encoder_id),
            drm.drmModeFreeEncoder,
            "Failed to retrieve DRM encoder %d" % encoder_id)

    def plane_resources(self):
        return self._owned(
            lambda: drm.drmModeGetPlaneResources(self.fd),
            drm.drmModeFreePlaneResources,
            "Unable to retrieve DRM planes")

    def plane(self, plane_id):
        return self._owned(
            lambda: drm.drmModeGetPlane(self.fd, plane_id),
            drm.drmModeFreePlane,
            "Failed to retrieve DRM plane %d" % plane_id)

    def object_properties(self, object_id, object_type):
        return self._owned(
            lambda: drm.drmModeObjectGetProperties(
                self.fd, object_id, object_type),
            drm.drmModeFreeObjectProperties,
            "Unable to read KMS properties for object %d" % object_id)

    def property(self, property_id):
        return self._owned(
            lambda: drm.drmModeGetProperty(self.fd, property_id),
            drm.drmModeFreeProperty,
            "Failed to retrieve DRM property %d" % property_id)

    def atomic_request(self):
        return self._owned(
            drm.drmModeAtomicAlloc,
            drm.drmModeAtomicFree,
            "Unable to allocate atomic KMS request")


class KMSDisplay:
    """Desktop OpenGL display backed by EGL, GBM, and atomic DRM/KMS."""

    name = 'kms'

    def __init__(self, width, height, clock, vfp=0, vsync=0, vbp=0,
                 device=None):
        self.closed = False
        self.fd = None
        self.master = False
        self.mode_blob_id = 0
        self.gbm_device = ffi.NULL
        self.gbm_surface = ffi.NULL
        self.egl_display = ffi.NULL
        self.egl_surface = ffi.NULL
        self.egl_context = ffi.NULL
        self.current_bo = ffi.NULL
        self.framebuffers = {}

        self.device, self.fd = self._open_dpi_device(device)
        self._drm = _DRMDevice(self.fd)
        if drm.drmSetMaster(self.fd) != 0:
            error = ffi.errno
            os.close(self.fd)
            raise RuntimeError(
                "Unable to become DRM master for %s (errno=%d: %s). "
                "Stop the compositor/display manager using this DRM card "
                "or run FBMatrix from a text console." %
                (self.device, error, os.strerror(error)))
        self.master = True
        self.format = GBM_FORMAT_XRGB8888
        self.timing_frames = 0
        self.egl_swap_time = 0.0
        self.kms_commit_time = 0.0
        self.mode = self._create_mode(
            width, height, clock, vfp, vsync, vbp)
        self.width = width
        self.height = height

        try:
            self._initialize_drm()
            print(self._device_description(), file=sys.stderr)
            self._initialize_egl()

            gl.glViewport(0, 0, self.width, self.height)

            # Establish the first GBM buffer and scanout target before
            # application rendering starts.
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            self.present()
        except BaseException:
            self.close()
            raise
        atexit.register(self.close)

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True

        if self.fd is not None and self.master:
            self._disable_scanout()

        if self.current_bo != ffi.NULL and self.gbm_surface != ffi.NULL:
            gbm.gbm_surface_release_buffer(
                self.gbm_surface, self.current_bo)
            self.current_bo = ffi.NULL

        if self.fd is not None:
            for fb_id in set(self.framebuffers.values()):
                drm.drmModeRmFB(self.fd, fb_id)
            self.framebuffers.clear()

        if self.egl_display != ffi.NULL:
            egl.eglMakeCurrent(
                self.egl_display, ffi.NULL, ffi.NULL, ffi.NULL)
            if self.egl_context != ffi.NULL:
                egl.eglDestroyContext(self.egl_display, self.egl_context)
                self.egl_context = ffi.NULL
            if self.egl_surface != ffi.NULL:
                egl.eglDestroySurface(self.egl_display, self.egl_surface)
                self.egl_surface = ffi.NULL
            egl.eglTerminate(self.egl_display)
            self.egl_display = ffi.NULL

        if self.gbm_surface != ffi.NULL:
            gbm.gbm_surface_destroy(self.gbm_surface)
            self.gbm_surface = ffi.NULL
        if self.gbm_device != ffi.NULL:
            gbm.gbm_device_destroy(self.gbm_device)
            self.gbm_device = ffi.NULL

        if self.fd is not None:
            if self.mode_blob_id:
                drm.drmModeDestroyPropertyBlob(
                    self.fd, self.mode_blob_id)
                self.mode_blob_id = 0
            if self.master:
                drm.drmDropMaster(self.fd)
                self.master = False
            os.close(self.fd)
            self.fd = None

    def _disable_scanout(self):
        required = (
            'plane_id', 'plane_properties', 'connector_id',
            'connector_properties', 'crtc_id', 'crtc_properties')
        if not all(hasattr(self, name) for name in required):
            return
        try:
            with self._drm.atomic_request() as request:
                self._add_property(
                    request, self.plane_id, self.plane_properties,
                    'FB_ID', 0)
                self._add_property(
                    request, self.plane_id, self.plane_properties,
                    'CRTC_ID', 0)
                self._add_property(
                    request, self.connector_id, self.connector_properties,
                    'CRTC_ID', 0)
                self._add_property(
                    request, self.crtc_id, self.crtc_properties,
                    'ACTIVE', 0)
                self._add_property(
                    request, self.crtc_id, self.crtc_properties,
                    'MODE_ID', 0)
                drm.drmModeAtomicCommit(
                    self.fd, request, DRM_MODE_ATOMIC_ALLOW_MODESET,
                    ffi.NULL)
        except Exception:
            # Continue releasing userspace resources even if the device has
            # already disappeared or rejects the final disable commit.
            pass

    @staticmethod
    def _card_devices():
        devices = [
            path for path in glob.glob('/dev/dri/card*')
            if os.path.basename(path)[4:].isdigit()
        ]
        return sorted(
            devices, key=lambda path: int(os.path.basename(path)[4:]))

    @classmethod
    def _open_dpi_device(cls, device=None):
        devices = [device] if device is not None else cls._card_devices()
        if not devices:
            raise RuntimeError("No DRM card devices were found in /dev/dri")

        errors = []
        for path in devices:
            try:
                fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            except OSError as error:
                errors.append('%s: %s' % (path, error.strerror))
                continue
            keep_open = False
            try:
                keep_open = cls._device_has_dpi(fd)
                if keep_open:
                    return path, fd
            except RuntimeError as error:
                errors.append('%s: %s' % (path, error))
            finally:
                if not keep_open:
                    os.close(fd)

        message = "DPI output was not detected on: %s" % ', '.join(devices)
        if errors:
            message += " (%s)" % '; '.join(errors)
        raise RuntimeError(message)

    @staticmethod
    def _device_has_dpi(fd):
        device = _DRMDevice(fd)
        with device.resources() as resources:
            for i in range(resources.count_connectors):
                with device.connector(
                        resources.connectors[i]) as connector:
                    if connector.connector_type == DRM_MODE_CONNECTOR_DPI:
                        return True
            return False

    def _initialize_drm(self):
        with self._drm.resources() as resources:
            for i in range(resources.count_connectors):
                with self._drm.connector(
                        resources.connectors[i]) as connector:
                    if connector.connector_type != DRM_MODE_CONNECTOR_DPI:
                        continue
                    self._initialize_connector(connector, resources)
                    return
            raise RuntimeError("DPI output was not detected")

    def _initialize_connector(self, connector, resources):
        self.connector_id = connector.connector_id
        self.connector_name = 'DPI-%d' % connector.connector_type_id
        self.crtc_id, crtc_index = self._find_crtc(connector, resources)

        self._enable_atomic_capabilities()
        self.connector_properties = self._properties(
            self.connector_id, DRM_MODE_OBJECT_CONNECTOR)
        self.crtc_properties = self._properties(
            self.crtc_id, DRM_MODE_OBJECT_CRTC)
        self._require_properties(
            self.connector_properties, ["CRTC_ID"], "connector")
        self._require_properties(
            self.crtc_properties, ["MODE_ID", "ACTIVE"], "CRTC")

        self.plane_id, self.plane_properties = self._find_primary_plane(
            crtc_index)

        blob_id = ffi.new("unsigned int *")
        if drm.drmModeCreatePropertyBlob(
                self.fd, self.mode, ffi.sizeof("drmModeModeInfo"),
                blob_id) != 0:
            raise RuntimeError("Unable to create DRM mode property blob")
        self.mode_blob_id = blob_id[0]

    def _device_description(self):
        return 'FBMatrix: DRM card %s (%s), output %s (connector %d)' % (
            os.path.basename(self.device), self.device,
            self.connector_name, self.connector_id)

    @staticmethod
    def _create_mode(width, height, clock, vfp=0, vsync=0, vbp=0):
        mode = ffi.new("drmModeModeInfo *")
        mode.clock = clock
        mode.hdisplay = width
        mode.hsync_start = width
        mode.hsync_end = width
        mode.htotal = width
        mode.vdisplay = height
        mode.vsync_start = height + vfp
        mode.vsync_end = mode.vsync_start + vsync
        mode.vtotal = mode.vsync_end + vbp
        mode.vrefresh = round(clock * 1000 / (width * mode.vtotal))
        mode.flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC
        mode.type = DRM_MODE_TYPE_USERDEF
        name = ('%dx%d' % (width, height)).encode()
        ffi.memmove(mode.name, name, min(len(name), 31))
        return mode

    def _find_crtc(self, connector, resources):
        encoder_ids = []
        if connector.encoder_id:
            encoder_ids.append(connector.encoder_id)
        encoder_ids.extend(
            connector.encoders[i] for i in range(connector.count_encoders)
            if connector.encoders[i] not in encoder_ids)

        for encoder_id in encoder_ids:
            with self._drm.encoder(encoder_id) as encoder:
                if encoder.crtc_id:
                    for i in range(resources.count_crtcs):
                        if resources.crtcs[i] == encoder.crtc_id:
                            return encoder.crtc_id, i
                for i in range(resources.count_crtcs):
                    if encoder.possible_crtcs & (1 << i):
                        return resources.crtcs[i], i
        raise RuntimeError("No CRTC is compatible with the DPI connector")

    def _enable_atomic_capabilities(self):
        if drm.drmSetClientCap(
                self.fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) != 0:
            raise RuntimeError("DRM universal planes are not supported")
        if drm.drmSetClientCap(self.fd, DRM_CLIENT_CAP_ATOMIC, 1) != 0:
            raise RuntimeError("DRM atomic modesetting is not supported")

    def _find_primary_plane(self, crtc_index):
        required = [
            "FB_ID", "CRTC_ID", "SRC_X", "SRC_Y", "SRC_W", "SRC_H",
            "CRTC_X", "CRTC_Y", "CRTC_W", "CRTC_H",
        ]
        with self._drm.plane_resources() as plane_resources:
            for i in range(plane_resources.count_planes):
                with self._drm.plane(
                        plane_resources.planes[i]) as plane:
                    if not (plane.possible_crtcs & (1 << crtc_index)):
                        continue
                    properties = self._properties(
                        plane.plane_id, DRM_MODE_OBJECT_PLANE)
                    plane_type = properties.get(
                        "type", properties.get("TYPE", (0, 0)))[1]
                    if plane_type == DRM_PLANE_TYPE_PRIMARY:
                        self._require_properties(
                            properties, required, "primary plane")
                        return plane.plane_id, properties
        raise RuntimeError("No primary plane is compatible with the DPI CRTC")

    def _properties(self, object_id, object_type):
        result = {}
        with self._drm.object_properties(
                object_id, object_type) as properties:
            for i in range(properties.count_props):
                with self._drm.property(properties.props[i]) as prop:
                    result[ffi.string(prop.name).decode()] = (
                        prop.prop_id, properties.prop_values[i])
        return result

    @staticmethod
    def _require_properties(properties, names, object_name):
        missing = [name for name in names if name not in properties]
        if missing:
            raise RuntimeError(
                "%s is missing atomic KMS properties: %s" %
                (object_name, ", ".join(missing)))

    def _initialize_egl(self):
        usage = GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING
        self.gbm_device = gbm.gbm_create_device(self.fd)
        if self.gbm_device == ffi.NULL:
            raise RuntimeError("Failed to create GBM device")

        self.gbm_surface = gbm.gbm_surface_create(
            self.gbm_device, self.width, self.height, self.format, usage)
        if self.gbm_surface == ffi.NULL:
            raise RuntimeError("Failed to create GBM surface")

        self.egl_display = egl.eglGetPlatformDisplay(
            EGL_PLATFORM_GBM_KHR, self.gbm_device, ffi.NULL)
        major = ffi.new("int *")
        minor = ffi.new("int *")
        if not egl.eglInitialize(self.egl_display, major, minor):
            self._raise_egl("Failed to initialize EGL")
        if not egl.eglBindAPI(EGL_OPENGL_API):
            self._raise_egl("Failed to bind desktop OpenGL")

        config = self._egl_config()
        self.egl_surface = egl.eglCreatePlatformWindowSurface(
            self.egl_display, config, self.gbm_surface, ffi.NULL)
        if self.egl_surface == ffi.NULL:
            self._raise_egl("Failed to create EGL window surface")

        context_attributes = ffi.new("int[]", [EGL_NONE])
        self.egl_context = egl.eglCreateContext(
            self.egl_display, config, ffi.NULL, context_attributes)
        if self.egl_context == ffi.NULL:
            self._raise_egl("Failed to create EGL context")
        if not egl.eglMakeCurrent(
                self.egl_display, self.egl_surface, self.egl_surface,
                self.egl_context):
            self._raise_egl("Failed to make EGL context current")
        # Atomic KMS presentation below is the frame-pacing point. Leaving
        # EGL's default swap interval enabled can wait for one refresh here
        # and then wait for a second refresh in drmModeAtomicCommit().
        if not egl.eglSwapInterval(self.egl_display, 0):
            self._raise_egl("Failed to disable EGL swap interval")

        self._validate_surface_size()

    def _egl_config(self):
        attributes = ffi.new("int[]", [
            EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
            EGL_RED_SIZE, 8,
            EGL_GREEN_SIZE, 8,
            EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 0,
            EGL_DEPTH_SIZE, 16,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_NONE,
        ])
        configs = ffi.new("EGLConfig[]", 32)
        count = ffi.new("int *")
        if not egl.eglChooseConfig(
                self.egl_display, attributes, configs, 32, count):
            self._raise_egl("Failed to choose EGL config")

        visual_id = ffi.new("int *")
        for i in range(count[0]):
            if (egl.eglGetConfigAttrib(
                    self.egl_display, configs[i], EGL_NATIVE_VISUAL_ID,
                    visual_id) and visual_id[0] == self.format):
                return configs[i]
        raise RuntimeError("No XRGB8888 EGL config is available")

    def _validate_surface_size(self):
        surface_width = ffi.new("int *")
        surface_height = ffi.new("int *")
        if not egl.eglQuerySurface(
                self.egl_display, self.egl_surface, EGL_WIDTH,
                surface_width):
            self._raise_egl("Unable to query EGL surface width")
        if not egl.eglQuerySurface(
                self.egl_display, self.egl_surface, EGL_HEIGHT,
                surface_height):
            self._raise_egl("Unable to query EGL surface height")
        if (surface_width[0], surface_height[0]) != (self.width, self.height):
            raise RuntimeError(
                "EGL surface is %dx%d; KMS mode is %dx%d" % (
                    surface_width[0], surface_height[0],
                    self.width, self.height))

    @staticmethod
    def _raise_egl(message):
        raise RuntimeError("%s (eglGetError=0x%X)" %
                           (message, egl.eglGetError()))

    def present(self):
        swap_started = time.monotonic()
        if not egl.eglSwapBuffers(self.egl_display, self.egl_surface):
            self._raise_egl("eglSwapBuffers failed")
        # eglSwapBuffers only submits work on Mesa. Finish it here so startup
        # diagnostics distinguish GPU execution from the KMS page-flip wait.
        gl.glFinish()
        swap_finished = time.monotonic()

        next_bo = gbm.gbm_surface_lock_front_buffer(self.gbm_surface)
        if next_bo == ffi.NULL:
            raise RuntimeError("Unable to lock GBM front buffer")
        next_fb = self._framebuffer_for_bo(next_bo)

        if self.current_bo == ffi.NULL:
            self._modeset(next_fb)
        else:
            commit_started = time.monotonic()
            self._atomic_present(next_fb)
            self.kms_commit_time += time.monotonic() - commit_started
            self.egl_swap_time += swap_finished - swap_started
            self.timing_frames += 1
            gbm.gbm_surface_release_buffer(
                self.gbm_surface, self.current_bo)
        self.current_bo = next_bo

    def consume_timings(self):
        if self.timing_frames == 0:
            return None
        timings = (
            1000 * self.egl_swap_time / self.timing_frames,
            1000 * self.kms_commit_time / self.timing_frames,
        )
        self.timing_frames = 0
        self.egl_swap_time = 0.0
        self.kms_commit_time = 0.0
        return timings

    def _framebuffer_for_bo(self, bo):
        key = int(ffi.cast("size_t", bo))
        if key in self.framebuffers:
            return self.framebuffers[key]

        handles = ffi.new("unsigned int[4]")
        pitches = ffi.new("unsigned int[4]")
        offsets = ffi.new("unsigned int[4]")
        modifiers = ffi.new("unsigned long long[4]")
        plane_count = gbm.gbm_bo_get_plane_count(bo)
        if not 1 <= plane_count <= 4:
            raise RuntimeError(
                "Unsupported GBM buffer plane count: %d" % plane_count)

        modifier = gbm.gbm_bo_get_modifier(bo)
        for i in range(plane_count):
            handles[i] = (
                gbm.gbm_bo_get_handle_for_plane(bo, i) & 0xFFFFFFFF)
            pitches[i] = gbm.gbm_bo_get_stride_for_plane(bo, i)
            offsets[i] = gbm.gbm_bo_get_offset(bo, i)
            modifiers[i] = modifier

        fb_id = ffi.new("unsigned int *")
        if modifier != DRM_FORMAT_MOD_INVALID:
            result = drm.drmModeAddFB2WithModifiers(
                self.fd, self.width, self.height, self.format,
                handles, pitches, offsets, modifiers, fb_id,
                DRM_MODE_FB_MODIFIERS)
        else:
            result = drm.drmModeAddFB2(
                self.fd, self.width, self.height, self.format,
                handles, pitches, offsets, fb_id, 0)
        if result != 0:
            raise RuntimeError(
                "Unable to create DRM framebuffer (errno=%d)" % ffi.errno)
        self.framebuffers[key] = fb_id[0]
        return fb_id[0]

    def _modeset(self, fb_id):
        with self._drm.atomic_request() as request:
            self._add_property(
                request, self.connector_id, self.connector_properties,
                "CRTC_ID", self.crtc_id)
            self._add_property(
                request, self.crtc_id, self.crtc_properties,
                "MODE_ID", self.mode_blob_id)
            self._add_property(
                request, self.crtc_id, self.crtc_properties, "ACTIVE", 1)
            self._add_plane_properties(request, fb_id)
            if drm.drmModeAtomicCommit(
                    self.fd, request, DRM_MODE_ATOMIC_ALLOW_MODESET,
                    ffi.NULL) != 0:
                error = ffi.errno
                raise RuntimeError(
                    "Initial atomic KMS modeset failed for "
                    "%dx%d (clock=%d kHz, h=%d/%d/%d/%d, "
                    "v=%d/%d/%d/%d, errno=%d: %s)" % (
                        self.mode.hdisplay, self.mode.vdisplay,
                        self.mode.clock,
                        self.mode.hdisplay, self.mode.hsync_start,
                        self.mode.hsync_end, self.mode.htotal,
                        self.mode.vdisplay, self.mode.vsync_start,
                        self.mode.vsync_end, self.mode.vtotal,
                        error, os.strerror(error)))

    def _atomic_present(self, fb_id):
        with self._drm.atomic_request() as request:
            self._add_property(
                request, self.plane_id, self.plane_properties,
                "FB_ID", fb_id)
            # Queue the flip asynchronously, then wait for its completion
            # event. The blocking atomic path on VC4 can wait for two refresh
            # periods; the event path completes on the next page flip.
            if drm.drmModeAtomicCommit(
                    self.fd, request,
                    DRM_MODE_ATOMIC_NONBLOCK | DRM_MODE_PAGE_FLIP_EVENT,
                    ffi.NULL) != 0:
                error = ffi.errno
                raise RuntimeError(
                    "Atomic KMS presentation failed (errno=%d: %s)" %
                    (error, os.strerror(error)))
            while True:
                try:
                    select.select([self.fd], [], [])
                    os.read(self.fd, 4096)
                    break
                except InterruptedError:
                    continue

    def _add_plane_properties(self, request, fb_id):
        values = {
            "FB_ID": fb_id,
            "CRTC_ID": self.crtc_id,
            "SRC_X": 0,
            "SRC_Y": 0,
            "SRC_W": self.width << 16,
            "SRC_H": self.height << 16,
            "CRTC_X": 0,
            "CRTC_Y": 0,
            "CRTC_W": self.width,
            "CRTC_H": self.height,
        }
        for name, value in values.items():
            self._add_property(
                request, self.plane_id, self.plane_properties, name, value)

    @staticmethod
    def _add_property(request, object_id, properties, name, value):
        if drm.drmModeAtomicAddProperty(
                request, object_id, properties[name][0], value) < 0:
            raise RuntimeError("Unable to add atomic property %s" % name)
