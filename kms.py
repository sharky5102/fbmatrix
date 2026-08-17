import os

import OpenGL.GL as gl

from ffi_backend import (
    DRM_CLIENT_CAP_ATOMIC,
    DRM_CLIENT_CAP_UNIVERSAL_PLANES,
    DRM_FORMAT_MOD_INVALID,
    DRM_MODE_ATOMIC_ALLOW_MODESET,
    DRM_MODE_CONNECTOR_DPI,
    DRM_MODE_FB_MODIFIERS,
    DRM_MODE_OBJECT_CONNECTOR,
    DRM_MODE_OBJECT_CRTC,
    DRM_MODE_OBJECT_PLANE,
    DRM_MODE_TYPE_PREFERRED,
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


class KMSDisplay:
    """Desktop OpenGL display backed by EGL, GBM, and atomic DRM/KMS."""

    def __init__(self, device="/dev/dri/card1"):
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        self.format = GBM_FORMAT_XRGB8888
        self.current_bo = ffi.NULL
        self.framebuffers = {}

        self._initialize_drm()
        self._initialize_egl()

        gl.glViewport(0, 0, self.width, self.height)

        # Establish the first GBM buffer and scanout target before application
        # rendering starts. Mesa attaches framebuffer 0 lazily on first swap.
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        self.present()

    def _initialize_drm(self):
        resources = drm.drmModeGetResources(self.fd)
        if resources == ffi.NULL:
            raise RuntimeError("Failed to retrieve DRM resources")

        connector = ffi.NULL
        try:
            for i in range(resources.count_connectors):
                candidate = drm.drmModeGetConnector(
                    self.fd, resources.connectors[i])
                if candidate == ffi.NULL:
                    continue
                if candidate.connector_type == DRM_MODE_CONNECTOR_DPI:
                    connector = candidate
                    break
                drm.drmModeFreeConnector(candidate)

            if connector == ffi.NULL:
                raise RuntimeError("DPI output was not detected")
            if connector.count_modes == 0:
                raise RuntimeError("DPI connector has no usable display modes")

            self.connector_id = connector.connector_id
            self.mode = self._preferred_mode(connector)
            self.width = self.mode.hdisplay
            self.height = self.mode.vdisplay

            encoder = drm.drmModeGetEncoder(self.fd, connector.encoder_id)
            if encoder == ffi.NULL or encoder.crtc_id == 0:
                raise RuntimeError("DPI connector has no active CRTC")
            try:
                self.crtc_id = encoder.crtc_id
            finally:
                drm.drmModeFreeEncoder(encoder)

            crtc_index = next(
                (i for i in range(resources.count_crtcs)
                 if resources.crtcs[i] == self.crtc_id),
                None,
            )
            if crtc_index is None:
                raise RuntimeError("DPI CRTC is absent from DRM resources")

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
        finally:
            if connector != ffi.NULL:
                drm.drmModeFreeConnector(connector)
            drm.drmModeFreeResources(resources)

    @staticmethod
    def _preferred_mode(connector):
        mode_index = 0
        for i in range(connector.count_modes):
            if connector.modes[i].type & DRM_MODE_TYPE_PREFERRED:
                mode_index = i
                break
        mode = ffi.new("drmModeModeInfo *")
        mode[0] = connector.modes[mode_index]
        return mode

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
        plane_resources = drm.drmModeGetPlaneResources(self.fd)
        if plane_resources == ffi.NULL:
            raise RuntimeError("Unable to retrieve DRM planes")
        try:
            for i in range(plane_resources.count_planes):
                plane = drm.drmModeGetPlane(
                    self.fd, plane_resources.planes[i])
                if plane == ffi.NULL:
                    continue
                try:
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
                finally:
                    drm.drmModeFreePlane(plane)
        finally:
            drm.drmModeFreePlaneResources(plane_resources)
        raise RuntimeError("No primary plane is compatible with the DPI CRTC")

    def _properties(self, object_id, object_type):
        result = {}
        properties = drm.drmModeObjectGetProperties(
            self.fd, object_id, object_type)
        if properties == ffi.NULL:
            raise RuntimeError(
                "Unable to read KMS properties for object %d" % object_id)
        try:
            for i in range(properties.count_props):
                prop = drm.drmModeGetProperty(self.fd, properties.props[i])
                if prop == ffi.NULL:
                    continue
                try:
                    result[ffi.string(prop.name).decode()] = (
                        prop.prop_id, properties.prop_values[i])
                finally:
                    drm.drmModeFreeProperty(prop)
        finally:
            drm.drmModeFreeObjectProperties(properties)
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
        if not egl.eglSwapBuffers(self.egl_display, self.egl_surface):
            self._raise_egl("eglSwapBuffers failed")

        next_bo = gbm.gbm_surface_lock_front_buffer(self.gbm_surface)
        if next_bo == ffi.NULL:
            raise RuntimeError("Unable to lock GBM front buffer")
        next_fb = self._framebuffer_for_bo(next_bo)

        if self.current_bo == ffi.NULL:
            self._modeset(next_fb)
        else:
            self._atomic_present(next_fb)
            gbm.gbm_surface_release_buffer(
                self.gbm_surface, self.current_bo)
        self.current_bo = next_bo

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
        request = self._atomic_request()
        try:
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
                raise RuntimeError("Initial atomic KMS modeset failed")
        finally:
            drm.drmModeAtomicFree(request)

    def _atomic_present(self, fb_id):
        request = self._atomic_request()
        try:
            self._add_property(
                request, self.plane_id, self.plane_properties,
                "FB_ID", fb_id)
            # Blocking commit: when it returns, the previous BO is no longer
            # scanned out and can safely be released.
            if drm.drmModeAtomicCommit(
                    self.fd, request, 0, ffi.NULL) != 0:
                raise RuntimeError("Atomic KMS presentation failed")
        finally:
            drm.drmModeAtomicFree(request)

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
    def _atomic_request():
        request = drm.drmModeAtomicAlloc()
        if request == ffi.NULL:
            raise RuntimeError("Unable to allocate atomic KMS request")
        return request

    @staticmethod
    def _add_property(request, object_id, properties, name, value):
        if drm.drmModeAtomicAddProperty(
                request, object_id, properties[name][0], value) < 0:
            raise RuntimeError("Unable to add atomic property %s" % name)
