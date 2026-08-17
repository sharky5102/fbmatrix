import os
os.environ['PYOPENGL_PLATFORM'] = 'egl'
os.environ['EGL_PLATFORM'] = 'gbm'

import sys
import numpy as np
import OpenGL.GL as gl
import OpenGL.GLUT as glut
from ffi_backend import ffi, drm, gbm, egl
import time
import fbo
import signal

import displays.ws2811
import displays.hub75e
import geometry.simple
import assembly.tree

def signal_handler(sig, frame):
        sys.exit(0)

global_init = False

class renderer(object):
    def __init__(
        self,
        emulate=False,
        preview=False,
        raw=False,
        display='hub75e',
        rows=32,
        columns=32,
        source_rows=None,
        source_columns=None,
        supersample=3,
        order='line-first',
        interpolate=True,
        oe='normal',
        extract='bcm',
        layout=None,
    ):
        self.emulate = emulate
        self.preview = preview
        self.raw = raw
        self.displaytype = display
        self.rows = rows
        self.columns = columns
        self.source_rows = source_rows or rows
        self.source_columns = source_columns or columns
        self.supersample = supersample
        self.order = order
        self.interpolate = interpolate
        self.oe = oe
        self.extract = extract
        self.layout = layout
        self.starttime = time.time()
        self.use_window_manager = self.preview or self.emulate or self.raw

        self.init()
            
    def clear(self):   
        gl.glClearColor(0, 0, 0, 0)    
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)

    def display(self):
        with self.mainfbo:
            self.clear()
            self.render()

        self.first_frame_finish("main FBO render")

        if self.emulate:
            gl.glClearColor(0, 0, 0, 0)    
            gl.glClear(gl.GL_COLOR_BUFFER_BIT| gl.GL_DEPTH_BUFFER_BIT)
            
            gl.glViewport(0, 0, int(self.screenWidth/2), self.screenHeight)
            self.tree.render(time.time() - self.starttime)
            
            gl.glViewport(int(self.screenWidth/2), 0, int(self.screenWidth/2), self.screenHeight)
            self.texquad.render()
            
        else:
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            self.first_frame_finish("EGL surface clear")

            if self.preview:
                self.texquad.render()
            else:
                self.signalgenerator.render()

        self.first_frame_finish("output render")
                    
        self.swap_buffers()

        # GLUT is callback driven, so request the next frame explicitly.  The
        # EGL/GBM backend is driven by the loop in run().
        if self.use_window_manager:
            glut.glutPostRedisplay()

    def first_frame_finish(self, stage):
        if self.use_window_manager or self.scanout_frame != 0:
            return
        error = gl.glGetError()
        print("KMS first frame: %s submitted, glGetError=0x%X" % (stage, error),
              flush=True)
        gl.glFinish()
        error = gl.glGetError()
        print("KMS first frame: %s complete, glGetError=0x%X" % (stage, error),
              flush=True)

    def swap_buffers(self):
        if self.use_window_manager:
            glut.glutSwapBuffers()
            return

        if not egl.eglSwapBuffers(self.egl_display, self.egl_surface):
            err = egl.eglGetError()
            raise RuntimeError("eglSwapBuffers failed (eglGetError=0x%X)" % err)

        if self.scanout_frame == 0:
            print("KMS first frame: eglSwapBuffers complete", flush=True)

        next_bo = gbm.gbm_surface_lock_front_buffer(self.gbm_surface)
        if next_bo == ffi.NULL:
            raise RuntimeError("Unable to lock the GBM front buffer")

        self.scanout_frame += 1
        next_bo_address = int(ffi.cast("size_t", next_bo))
        current_bo_address = (int(ffi.cast("size_t", self.current_bo))
                              if self.current_bo != ffi.NULL else 0)
        next_fb = self.framebuffer_for_bo(next_bo)
        if self.current_bo == ffi.NULL:
            self.atomic_modeset(next_fb)
            if self.scanout_frame <= 10:
                print("KMS initial atomic modeset complete", flush=True)
        else:
            self.atomic_present(next_fb)
            gbm.gbm_surface_release_buffer(self.gbm_surface, self.current_bo)

        self.current_bo = next_bo

    def kms_properties(self, object_id, object_type):
        result = {}
        props = drm.drmModeObjectGetProperties(self.fd, object_id, object_type)
        if props == ffi.NULL:
            raise RuntimeError("Unable to read KMS properties for object %d" % object_id)
        try:
            for i in range(props.count_props):
                prop = drm.drmModeGetProperty(self.fd, props.props[i])
                if prop != ffi.NULL:
                    try:
                        result[ffi.string(prop.name).decode()] = (prop.prop_id, props.prop_values[i])
                    finally:
                        drm.drmModeFreeProperty(prop)
        finally:
            drm.drmModeFreeObjectProperties(props)
        return result

    @staticmethod
    def require_properties(properties, names, object_name):
        missing = [name for name in names if name not in properties]
        if missing:
            raise RuntimeError("%s is missing atomic KMS properties: %s" %
                               (object_name, ", ".join(missing)))

    def add_atomic_property(self, request, object_id, properties, name, value):
        if drm.drmModeAtomicAddProperty(request, object_id, properties[name][0], value) < 0:
            raise RuntimeError("Unable to add atomic KMS property %s" % name)

    def framebuffer_for_bo(self, bo):
        key = int(ffi.cast("size_t", bo))
        if key in self.framebuffers:
            return self.framebuffers[key]

        handles = ffi.new("unsigned int[4]")
        pitches = ffi.new("unsigned int[4]")
        offsets = ffi.new("unsigned int[4]")
        modifiers = ffi.new("unsigned long long[4]")
        plane_count = gbm.gbm_bo_get_plane_count(bo)
        if plane_count < 1 or plane_count > 4:
            raise RuntimeError("Unsupported GBM buffer plane count: %d" % plane_count)
        modifier = gbm.gbm_bo_get_modifier(bo)
        for i in range(plane_count):
            handles[i] = gbm.gbm_bo_get_handle_for_plane(bo, i) & 0xffffffff
            pitches[i] = gbm.gbm_bo_get_stride_for_plane(bo, i)
            offsets[i] = gbm.gbm_bo_get_offset(bo, i)
            modifiers[i] = modifier
        fb_id = ffi.new("unsigned int *")
        DRM_FORMAT_MOD_INVALID = 0xffffffffffffffff
        DRM_MODE_FB_MODIFIERS = 0x02
        if modifier != DRM_FORMAT_MOD_INVALID:
            result = drm.drmModeAddFB2WithModifiers(
                self.fd, self.screenWidth, self.screenHeight, self.gbm_format,
                handles, pitches, offsets, modifiers, fb_id, DRM_MODE_FB_MODIFIERS)
        else:
            result = drm.drmModeAddFB2(
                self.fd, self.screenWidth, self.screenHeight, self.gbm_format,
                handles, pitches, offsets, fb_id, 0)
        if result != 0:
            raise RuntimeError("Unable to create DRM framebuffer (errno=%d)" % ffi.errno)
        self.framebuffers[key] = fb_id[0]
        self.new_bo_count += 1
        if self.new_bo_count <= 10 or self.new_bo_count % 25 == 0:
            print(
                "KMS new BO #%d: address=0x%x fb=%d planes=%d "
                "handle=%d pitch=%d modifier=0x%x cached_fbs=%d" % (
                    self.new_bo_count, key, fb_id[0], plane_count,
                    handles[0], pitches[0], modifier, len(self.framebuffers),
                ),
                flush=True,
            )
        return fb_id[0]

    def atomic_modeset(self, fb_id):
        DRM_MODE_ATOMIC_ALLOW_MODESET = 0x0400
        request = drm.drmModeAtomicAlloc()
        if request == ffi.NULL:
            raise RuntimeError("Unable to allocate atomic KMS request")
        try:
            self.add_atomic_property(request, self.target_connector_id,
                                     self.connector_properties, "CRTC_ID", self.crtc_id)
            self.add_atomic_property(request, self.crtc_id,
                                     self.crtc_properties, "MODE_ID", self.mode_blob_id)
            self.add_atomic_property(request, self.crtc_id,
                                     self.crtc_properties, "ACTIVE", 1)
            self.add_plane_properties(request, fb_id)
            if drm.drmModeAtomicCommit(self.fd, request,
                                       DRM_MODE_ATOMIC_ALLOW_MODESET, ffi.NULL) != 0:
                raise RuntimeError("Initial atomic KMS modeset failed")
        finally:
            drm.drmModeAtomicFree(request)

    def add_plane_properties(self, request, fb_id):
        values = {
            "FB_ID": fb_id,
            "CRTC_ID": self.crtc_id,
            "SRC_X": 0,
            "SRC_Y": 0,
            "SRC_W": self.screenWidth << 16,
            "SRC_H": self.screenHeight << 16,
            "CRTC_X": 0,
            "CRTC_Y": 0,
            "CRTC_W": self.screenWidth,
            "CRTC_H": self.screenHeight,
        }
        for name, value in values.items():
            self.add_atomic_property(request, self.plane_id,
                                     self.plane_properties, name, value)

    def atomic_present(self, fb_id):
        request = drm.drmModeAtomicAlloc()
        if request == ffi.NULL:
            raise RuntimeError("Unable to allocate atomic KMS request")
        try:
            self.add_atomic_property(request, self.plane_id,
                                     self.plane_properties, "FB_ID", fb_id)
            # A commit without DRM_MODE_ATOMIC_NONBLOCK is synchronous.  When
            # this returns the new framebuffer is active and the previous GBM
            # buffer can safely be released.
            if drm.drmModeAtomicCommit(self.fd, request, 0, ffi.NULL) != 0:
                raise RuntimeError("Atomic KMS page flip failed")
        finally:
            drm.drmModeAtomicFree(request)
    
    def reshape(self,width,height):
        self.screenWidth = width
        self.screenHeight = height
        
        gl.glViewport(0, 0, width, height)

    def keyboard(self, key, x, y ):
        if key == b'\033':
            try:
                glut.glutLeaveMainLoop()
            except Exception:
                glut.glutDestroyWindow(glut.glutGetWindow())

    def init(self):
        # Initialize display
        global global_init
        if global_init:
            return
        global_init = True
            
        if self.use_window_manager:
            self.init_glut()
        else:
            self.init_egl()

        # Primary offscreen framebuffer
        self.mainfbo = fbo.FBO(
            self.source_columns,
            self.source_rows,
            mag_filter=gl.GL_NEAREST,
            min_filter=gl.GL_LINEAR_MIPMAP_LINEAR,
        )

        if self.displaytype == 'ws2811':
            if self.layout is None:
                raise RuntimeError('WS2811 display requires a layout argument')
            self.signalgenerator = displays.ws2811.signalgenerator(self.layout, supersample=self.supersample)
            self.signalgenerator.setTexture(self.mainfbo.getTexture())
        elif self.displaytype == 'hub75e':
            self.signalgenerator = displays.hub75e.signalgenerator(columns=self.columns, rows=self.rows, supersample=self.supersample, order=self.order, oe=self.oe, extract=self.extract)
            self.signalgenerator.setTexture(self.mainfbo.getTexture())

        # Emulation shader
        if self.emulate or self.preview:
            self.texquad = geometry.simple.texquad()
            self.texquad.setTexture(self.mainfbo.getTexture())

        # Tree emulator
        if self.emulate:
            if self.layout is None:
                raise RuntimeError('Emulation requires a layout argument')
            self.tree = assembly.tree.tree(self.layout, supersample=self.supersample)
            self.tree.setTexture(self.mainfbo.getTexture())
            
    def init_glut(self):
        glut.glutInit()
        glut.glutInitDisplayMode(glut.GLUT_DOUBLE | glut.GLUT_RGBA | glut.GLUT_DEPTH | glut.GLUT_ALPHA)
        glut.glutCreateWindow(b'fbmatrix')

        if self.preview or self.raw:
            glut.glutReshapeWindow(512, 512)
        elif self.emulate:
            glut.glutReshapeWindow(1024, 512)

        glut.glutReshapeFunc(lambda w,h: self.reshape(w,h))
        glut.glutDisplayFunc(lambda: self.display())
        glut.glutKeyboardFunc(lambda k,x,y: self.keyboard(k,x,y))

    def init_egl(self):
        self.fd = os.open("/dev/dri/card1", os.O_RDWR | os.O_CLOEXEC)

        # Get all video outputs connected to the card
        resources = drm.drmModeGetResources(self.fd)
        if resources == ffi.NULL:
            raise RuntimeError("Failed to retrieve DRM hardware resources.")

        self.target_connector_id = None
        self.target_mode = None

        # Loop through connectors to explicitly find HDMI-2
        for i in range(resources.count_connectors):
            conn_id = resources.connectors[i]
            conn = drm.drmModeGetConnector(self.fd, conn_id)
            if conn == ffi.NULL:
                continue

            print(conn.connector_type, conn.connection, conn.connector_id)

            if conn.connector_type == 17:
                print(f"Found DPI Connector ID: {conn.connector_id}")
                self.target_connector_id = conn.connector_id
                break

            drm.drmModeFreeConnector(conn)

        if not self.target_connector_id:
            raise RuntimeError("DPI output was not detected. Please configure DPI output according to README.md")

        connector = drm.drmModeGetConnector(self.fd, self.target_connector_id)
        if connector == ffi.NULL or connector.count_modes == 0:
            raise RuntimeError("Selected connector has no usable display modes")

        # Prefer the mode marked by KMS, otherwise use the connector's first mode.
        DRM_MODE_TYPE_PREFERRED = 1 << 3
        mode_index = 0
        for i in range(connector.count_modes):
            if connector.modes[i].type & DRM_MODE_TYPE_PREFERRED:
                mode_index = i
                break
        self.target_mode = ffi.new("drmModeModeInfo *")
        self.target_mode[0] = connector.modes[mode_index]
        print(
            "KMS selected mode: %s %dx%d clock=%d kHz refresh=%d" % (
                ffi.string(self.target_mode.name).decode(errors="replace"),
                self.target_mode.hdisplay,
                self.target_mode.vdisplay,
                self.target_mode.clock,
                self.target_mode.vrefresh,
            ),
            flush=True,
        )

        encoder = drm.drmModeGetEncoder(self.fd, connector.encoder_id)
        if encoder == ffi.NULL or encoder.crtc_id == 0:
            raise RuntimeError("DPI connector has no active CRTC")
        self.crtc_id = encoder.crtc_id
        drm.drmModeFreeEncoder(encoder)

        crtc_index = None
        for i in range(resources.count_crtcs):
            if resources.crtcs[i] == self.crtc_id:
                crtc_index = i
                break
        if crtc_index is None:
            raise RuntimeError("DPI connector CRTC is not present in DRM resources")

        DRM_CLIENT_CAP_UNIVERSAL_PLANES = 2
        DRM_CLIENT_CAP_ATOMIC = 3
        if drm.drmSetClientCap(self.fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1) != 0:
            raise RuntimeError("DRM universal planes are not supported")
        if drm.drmSetClientCap(self.fd, DRM_CLIENT_CAP_ATOMIC, 1) != 0:
            raise RuntimeError("DRM atomic modesetting is not supported")

        DRM_MODE_OBJECT_CRTC = 0xcccccccc
        DRM_MODE_OBJECT_CONNECTOR = 0xc0c0c0c0
        DRM_MODE_OBJECT_PLANE = 0xeeeeeeee
        self.connector_properties = self.kms_properties(
            self.target_connector_id, DRM_MODE_OBJECT_CONNECTOR)
        self.crtc_properties = self.kms_properties(self.crtc_id, DRM_MODE_OBJECT_CRTC)
        self.require_properties(self.connector_properties, ["CRTC_ID"], "connector")
        self.require_properties(self.crtc_properties, ["MODE_ID", "ACTIVE"], "CRTC")

        self.plane_id = None
        self.plane_properties = None
        plane_resources = drm.drmModeGetPlaneResources(self.fd)
        if plane_resources == ffi.NULL:
            raise RuntimeError("Unable to retrieve DRM planes")
        try:
            for i in range(plane_resources.count_planes):
                plane = drm.drmModeGetPlane(self.fd, plane_resources.planes[i])
                print("Got plane %d: id=%d, crtc_id=%d, possible_crtcs=0x%X" % (i, plane.plane_id, plane.crtc_id, plane.possible_crtcs))
                if plane == ffi.NULL:
                    continue
                try:
                    if not (plane.possible_crtcs & (1 << crtc_index)):
                        continue
                    properties = self.kms_properties(plane.plane_id, DRM_MODE_OBJECT_PLANE)
                    # The vc4 primary plane exposes TYPE=1.
                    if properties.get("type", properties.get("TYPE", (0, 0)))[1] == 1:
                        self.plane_id = plane.plane_id
                        self.plane_properties = properties
                        break
                finally:
                    drm.drmModeFreePlane(plane)
        finally:
            drm.drmModeFreePlaneResources(plane_resources)

        if self.plane_id is None:
            raise RuntimeError("No primary DRM plane is compatible with the DPI CRTC")
        required_plane_properties = [
            "FB_ID", "CRTC_ID", "SRC_X", "SRC_Y", "SRC_W", "SRC_H",
            "CRTC_X", "CRTC_Y", "CRTC_W", "CRTC_H",
        ]
        self.require_properties(self.plane_properties, required_plane_properties, "primary plane")

        blob_id = ffi.new("unsigned int *")
        if drm.drmModeCreatePropertyBlob(self.fd, self.target_mode,
                                         ffi.sizeof("drmModeModeInfo"), blob_id) != 0:
            raise RuntimeError("Unable to create DRM mode property blob")
        self.mode_blob_id = blob_id[0]

        drm.drmModeFreeConnector(connector)
        drm.drmModeFreeResources(resources)

        # ==============================================================================
        # 2. INITIALIZE PURE EGL VIA THE GBM PLATFORM BRIDGE
        # ==============================================================================
        gbm_dev = gbm.gbm_create_device(self.fd)
        if gbm_dev == ffi.NULL:
            raise RuntimeError("Failed to create GBM device")
        EGL_PLATFORM_GBM_KHR = 0x31D7

        egl_display = egl.eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm_dev, ffi.NULL)

        major,minor = ffi.new("int*"), ffi.new("int*")
        init_res = egl.eglInitialize(egl_display, major, minor)
        print("eglInitialize returned:", init_res, "major/minor:", major[0], minor[0])
        if not init_res:
            err = egl.eglGetError()
            print("eglInitialize failed, eglGetError=0x%X" % err)

        # Match the existing GLUT renderer, which relies on desktop OpenGL
        # compatibility features such as glPushAttrib and GL_QUADS.
        EGL_OPENGL_API = 0x30A2
        bind_res = egl.eglBindAPI(EGL_OPENGL_API)
        print("eglBindAPI(EGL_OPENGL_API) returned:", bind_res)
        if not bind_res:
            print("eglBindAPI failed, eglGetError=0x%X" % egl.eglGetError())

        GBM_FORMAT_XRGB8888 = 0x34325258
        self.gbm_format = GBM_FORMAT_XRGB8888
        GBM_BO_USE_SCANOUT   = 1 << 0
        GBM_BO_USE_RENDERING = 1 << 2
        gbm_usage = GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING
        backend_name = gbm.gbm_device_get_backend_name(gbm_dev)
        backend_name = (ffi.string(backend_name).decode(errors="replace")
                        if backend_name != ffi.NULL else "<unknown>")
        format_supported = gbm.gbm_device_is_format_supported(
            gbm_dev, GBM_FORMAT_XRGB8888, gbm_usage)
        print("GBM backend=%s XRGB8888 scanout+rendering=%s" % (
            backend_name, bool(format_supported)), flush=True)
        if not format_supported:
            raise RuntimeError(
                "GBM backend %s does not support XRGB8888 for scanout+rendering" %
                backend_name)

        GBM_BO_USE_LINEAR = 1 << 4
        probe_results = {}
        for usage_name, probe_usage in (
                ("scanout", GBM_BO_USE_SCANOUT),
                ("rendering", GBM_BO_USE_RENDERING),
                ("scanout+rendering", gbm_usage),
                ("scanout+rendering+linear", gbm_usage | GBM_BO_USE_LINEAR)):
            ffi.errno = 0
            probe_bo = gbm.gbm_bo_create(
                gbm_dev,
                self.target_mode.hdisplay,
                self.target_mode.vdisplay,
                GBM_FORMAT_XRGB8888,
                probe_usage,
            )
            if probe_bo == ffi.NULL:
                probe_results[usage_name] = False
                print("GBM BO probe %-26s failed errno=%d" %
                      (usage_name, ffi.errno), flush=True)
            else:
                probe_results[usage_name] = True
                print("GBM BO probe %-26s ok handle=%d pitch=%d modifier=0x%x" % (
                    usage_name,
                    gbm.gbm_bo_get_handle(probe_bo) & 0xffffffff,
                    gbm.gbm_bo_get_stride(probe_bo),
                    gbm.gbm_bo_get_modifier(probe_bo),
                ), flush=True)
                gbm.gbm_bo_destroy(probe_bo)

        if not probe_results["scanout+rendering"]:
            raise RuntimeError(
                "GBM could not allocate a %dx%d XRGB8888 scanout/rendering BO" %
                (self.target_mode.hdisplay, self.target_mode.vdisplay))

        gbm_surface = gbm.gbm_surface_create(
            gbm_dev,
            self.target_mode.hdisplay,
            self.target_mode.vdisplay,
            GBM_FORMAT_XRGB8888,
            gbm_usage
        )
        if gbm_surface == ffi.NULL:
            raise RuntimeError("Failed to create GBM surface")

        # Choose an EGL config compatible with this GBM native window.
        # The native renderable flag is important: without it, surface creation
        # often fails with EGL_BAD_MATCH on Raspberry Pi / Mesa.
        EGL_SURFACE_TYPE = 0x3033
        EGL_WINDOW_BIT = 0x0004
        EGL_RED_SIZE = 0x3024
        EGL_GREEN_SIZE = 0x3023
        EGL_BLUE_SIZE = 0x3022
        EGL_ALPHA_SIZE = 0x3021
        EGL_RENDERABLE_TYPE = 0x3040
        EGL_OPENGL_BIT = 0x0008
        EGL_NATIVE_RENDERABLE = 0x302D
        EGL_DEPTH_SIZE = 0x3025
        EGL_CONTEXT_CLIENT_VERSION = 0x3098
        EGL_NONE = 0x3038
        EGL_NATIVE_VISUAL_ID = 0x302E

        attribs = ffi.new("int[]", [
            EGL_SURFACE_TYPE, EGL_WINDOW_BIT,
            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
            EGL_ALPHA_SIZE, 0,
            EGL_DEPTH_SIZE, 16,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_NONE
        ])

        num_configs = ffi.new("int *")
        configs = ffi.new("EGLConfig[]", 32)
        choose_res = egl.eglChooseConfig(egl_display, attribs, configs, 32, num_configs)
        print("eglChooseConfig returned:", choose_res, "num_configs:", num_configs[0])

        egl_config = None
        for i in range(0, num_configs[0]):
            config = configs[i]
            value = ffi.new("int *")
            if egl.eglGetConfigAttrib(egl_display, config, EGL_NATIVE_VISUAL_ID, value):
                print("%x" % (value[0]))
                if value[0] == GBM_FORMAT_XRGB8888:
                    egl_config = config
                    break
            else:
                print("No visual id")

        if not choose_res or egl_config is None:
            err = egl.eglGetError()
            raise RuntimeError("No suitable EGL config found (eglGetError=0x%X)" % err)

        EGL_CONFIG_ID = 0x302A
        EGL_SURFACE_TYPE = 0x3033
        EGL_RENDERABLE_TYPE = 0x3040
        EGL_RED_SIZE = 0x3024
        EGL_GREEN_SIZE = 0x3023
        EGL_BLUE_SIZE = 0x3022
        EGL_DEPTH_SIZE = 0x3025
        EGL_NATIVE_RENDERABLE = 0x302D
        EGL_BUFFER_SIZE = 0x3020
        EGL_ALPHA_SIZE = 0x3021

        value = ffi.new("int *")
        for name in [EGL_NATIVE_VISUAL_ID, EGL_CONFIG_ID, EGL_SURFACE_TYPE, EGL_RENDERABLE_TYPE, EGL_RED_SIZE, EGL_GREEN_SIZE, EGL_BLUE_SIZE, EGL_ALPHA_SIZE, EGL_DEPTH_SIZE, EGL_BUFFER_SIZE, EGL_NATIVE_RENDERABLE]:
            if egl.eglGetConfigAttrib(egl_display, egl_config, name, value):
                print("EGL attr 0x%X = %x" % (name, value[0]))
            else:
                print("EGL attr 0x%X = <unavailable>" % name)

        # Create the native GBM window surface. This is the minimal step for a physical-output
        # DRM/GBM EGL path; we are intentionally not configuring a CRTC yet.
        egl_surface = egl.eglCreatePlatformWindowSurface(
            egl_display,
            egl_config,
            gbm_surface,
            ffi.NULL
        )
        if egl_surface == ffi.NULL:
            err = egl.eglGetError()
            raise RuntimeError("Failed to create EGL surface (eglGetError=0x%X)" % err)

        # EGL_CONTEXT_CLIENT_VERSION is ignored for desktop OpenGL. Keep an
        # empty attribute list and let Mesa create its supported GL context.
        ctx_attribs = ffi.new("int[]", [
            EGL_NONE
        ])
        egl_context = egl.eglCreateContext(egl_display, egl_config, ffi.NULL, ctx_attribs)
        if egl_context == ffi.NULL:
            err = egl.eglGetError()
            # Try to print EGL vendor/version/extensions to help debugging
            EGL_VENDOR = 0x3053
            EGL_VERSION = 0x3054
            EGL_EXTENSIONS = 0x3055
            vendor = ffi.string(egl.eglQueryString(egl_display, EGL_VENDOR)) if egl.eglQueryString(egl_display, EGL_VENDOR) != ffi.NULL else b""
            version = ffi.string(egl.eglQueryString(egl_display, EGL_VERSION)) if egl.eglQueryString(egl_display, EGL_VERSION) != ffi.NULL else b""
            exts = ffi.string(egl.eglQueryString(egl_display, EGL_EXTENSIONS)) if egl.eglQueryString(egl_display, EGL_EXTENSIONS) != ffi.NULL else b""
            print("eglCreateContext failed, eglGetError=0x%X" % err)
            print("EGL vendor:", vendor)
            print("EGL version:", version)
            print("EGL extensions:", exts)
            raise RuntimeError("Failed to create EGL context (eglGetError=0x%X)" % err)

        # store for later use
        self.egl_display = egl_display
        self.egl_surface = egl_surface
        self.egl_context = egl_context
        self.gbm_device = gbm_dev
        self.gbm_surface = gbm_surface
        self.current_bo = ffi.NULL
        self.framebuffers = {}
        self.scanout_frame = 0
        self.new_bo_count = 0
        # make context current (pass the real context, not NULL)
        if not egl.eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context):
            raise RuntimeError("Unable to make EGL current")

        print("egl.eglGetCurrentContext():", egl.eglGetCurrentContext())
        print(
            "GL vendor=%s renderer=%s version=%s" % tuple(
                value.decode(errors="replace") if value else "<unavailable>"
                for value in (
                    gl.glGetString(gl.GL_VENDOR),
                    gl.glGetString(gl.GL_RENDERER),
                    gl.glGetString(gl.GL_VERSION),
                )
            ),
            flush=True,
        )

        self.screenWidth = self.target_mode.hdisplay
        self.screenHeight = self.target_mode.vdisplay

        EGL_WIDTH = 0x3057
        EGL_HEIGHT = 0x3056
        surface_width = ffi.new("int *")
        surface_height = ffi.new("int *")
        if not egl.eglQuerySurface(egl_display, egl_surface, EGL_WIDTH, surface_width):
            raise RuntimeError("Unable to query EGL surface width")
        if not egl.eglQuerySurface(egl_display, egl_surface, EGL_HEIGHT, surface_height):
            raise RuntimeError("Unable to query EGL surface height")
        print("EGL surface size: %dx%d, GL draw buffer=0x%X" % (
            surface_width[0], surface_height[0], gl.glGetIntegerv(gl.GL_DRAW_BUFFER)),
            flush=True)
        if (surface_width[0] != self.screenWidth or
                surface_height[0] != self.screenHeight):
            raise RuntimeError(
                "EGL surface size %dx%d does not match KMS mode %dx%d" % (
                    surface_width[0], surface_height[0],
                    self.screenWidth, self.screenHeight))

        gl.glViewport(0, 0, self.screenWidth, self.screenHeight)

        # Mesa does not attach the first GBM back buffer to framebuffer 0
        # until the window surface has been swapped once.  Bootstrap a blank
        # scanout buffer here so subsequent GL jobs have a real color buffer
        # and valid drawable dimensions.
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        self.swap_buffers()
        print("KMS bootstrap modeset complete", flush=True)

        print("Config done")

    def run(self, render):
        self.render = render
        signal.signal(signal.SIGINT, signal_handler)

        if self.use_window_manager:
            glut.glutMainLoop()
        else:
            while True:
                self.display()
