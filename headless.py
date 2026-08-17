import OpenGL.GL as gl

from ffi_backend import (
    EGL_ALPHA_SIZE,
    EGL_BLUE_SIZE,
    EGL_DEPTH_SIZE,
    EGL_GREEN_SIZE,
    EGL_HEIGHT,
    EGL_NONE,
    EGL_OPENGL_API,
    EGL_OPENGL_BIT,
    EGL_PBUFFER_BIT,
    EGL_PLATFORM_SURFACELESS_MESA,
    EGL_RED_SIZE,
    EGL_RENDERABLE_TYPE,
    EGL_SURFACE_TYPE,
    EGL_WIDTH,
    egl,
    ffi,
)


class HeadlessDisplay:
    """Small surfaceless EGL context used by rendering tests."""

    width = 1
    height = 1

    def __init__(self):
        self.egl_display = egl.eglGetPlatformDisplay(
            EGL_PLATFORM_SURFACELESS_MESA, ffi.NULL, ffi.NULL)
        major = ffi.new("int *")
        minor = ffi.new("int *")
        if not egl.eglInitialize(self.egl_display, major, minor):
            self._raise_egl("Failed to initialize headless EGL")
        if not egl.eglBindAPI(EGL_OPENGL_API):
            self._raise_egl("Failed to bind desktop OpenGL")

        attributes = ffi.new("int[]", [
            EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
            EGL_RED_SIZE, 8,
            EGL_GREEN_SIZE, 8,
            EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 0,
            EGL_DEPTH_SIZE, 16,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_NONE,
        ])
        configs = ffi.new("EGLConfig[]", 1)
        count = ffi.new("int *")
        if (not egl.eglChooseConfig(
                self.egl_display, attributes, configs, 1, count) or
                count[0] == 0):
            self._raise_egl("No headless EGL config is available")

        surface_attributes = ffi.new("int[]", [
            EGL_WIDTH, self.width,
            EGL_HEIGHT, self.height,
            EGL_NONE,
        ])
        self.egl_surface = egl.eglCreatePbufferSurface(
            self.egl_display, configs[0], surface_attributes)
        if self.egl_surface == ffi.NULL:
            self._raise_egl("Failed to create headless EGL surface")

        context_attributes = ffi.new("int[]", [EGL_NONE])
        self.egl_context = egl.eglCreateContext(
            self.egl_display, configs[0], ffi.NULL, context_attributes)
        if self.egl_context == ffi.NULL:
            self._raise_egl("Failed to create headless EGL context")
        if not egl.eglMakeCurrent(
                self.egl_display, self.egl_surface, self.egl_surface,
                self.egl_context):
            self._raise_egl("Failed to make headless EGL context current")

    def present(self):
        gl.glFinish()

    @staticmethod
    def _raise_egl(message):
        raise RuntimeError("%s (eglGetError=0x%X)" %
                           (message, egl.eglGetError()))
