from cffi import FFI

ffi = FFI()
ffi.cdef("""
    // DRM Definitions
    typedef struct _drmModeModeInfo {
        unsigned int clock;
        unsigned short hdisplay, hsync_start, hsync_end, htotal, hskew;
        unsigned short vdisplay, vsync_start, vsync_end, vtotal, vscan;
        unsigned int vrefresh;
        unsigned int flags;
        unsigned int type;
        char name[32];
    } drmModeModeInfo;

    typedef struct _drmModeConnector {
        unsigned int connector_id;
        unsigned int encoder_id;
        unsigned int connector_type;
        unsigned int connector_type_id;
        unsigned int connection;
        unsigned int mmWidth, mmHeight;
        unsigned int subpixel;
        int count_modes;
        drmModeModeInfo *modes;
        int count_props;
        unsigned int *props;
        unsigned long long *prop_values;
        int count_encoders;
        unsigned int *encoders;
    } drmModeConnector;

    typedef struct _drmModeEncoder {
        unsigned int encoder_id;
        unsigned int encoder_type;
        unsigned int crtc_id;
        unsigned int possible_crtcs;
        unsigned int possible_clones;
    } drmModeEncoder;

    typedef struct _drmModeRes {
        int count_fbs;
        unsigned int *fbs;
        int count_crtcs;
        unsigned int *crtcs;
        int count_connectors;
        unsigned int *connectors;
        int count_encoders;
        unsigned int *encoders;
        int min_width, max_width;
        int min_height, max_height;
    } drmModeRes;

    typedef struct _drmModePlaneRes {
        unsigned int count_planes;
        unsigned int *planes;
    } drmModePlaneRes;

    typedef struct _drmModePlane {
        unsigned int count_formats;
        unsigned int *formats;
        unsigned int plane_id;
        unsigned int crtc_id;
        unsigned int fb_id;
        unsigned int crtc_x, crtc_y;
        unsigned int x, y;
        unsigned int possible_crtcs;
        unsigned int gamma_size;
    } drmModePlane;

    typedef struct _drmModeObjectProperties {
        unsigned int count_props;
        unsigned int *props;
        unsigned long long *prop_values;
    } drmModeObjectProperties;

    typedef struct _drmModePropertyRes {
        unsigned int prop_id;
        unsigned int flags;
        char name[32];
        int count_values;
        unsigned long long *values;
        int count_enums;
        void *enums;
        int count_blobs;
        unsigned int *blob_ids;
    } drmModePropertyRes;

    typedef struct _drmModeAtomicReq drmModeAtomicReq;

    drmModeRes* drmModeGetResources(int fd);
    int drmSetMaster(int fd);
    int drmDropMaster(int fd);
    drmModeConnector* drmModeGetConnector(int fd, unsigned int connectorId);
    void drmModeFreeConnector(drmModeConnector *ptr);
    drmModeEncoder* drmModeGetEncoder(int fd, unsigned int encoder_id);
    void drmModeFreeEncoder(drmModeEncoder *ptr);
    void drmModeFreeResources(drmModeRes *ptr);
    int drmSetClientCap(int fd, unsigned long long capability, unsigned long long value);
    drmModePlaneRes* drmModeGetPlaneResources(int fd);
    void drmModeFreePlaneResources(drmModePlaneRes *ptr);
    drmModePlane* drmModeGetPlane(int fd, unsigned int plane_id);
    void drmModeFreePlane(drmModePlane *ptr);
    drmModeObjectProperties* drmModeObjectGetProperties(int fd, unsigned int object_id, unsigned int object_type);
    void drmModeFreeObjectProperties(drmModeObjectProperties *ptr);
    drmModePropertyRes* drmModeGetProperty(int fd, unsigned int property_id);
    void drmModeFreeProperty(drmModePropertyRes *ptr);
    int drmModeCreatePropertyBlob(int fd, const void *data, size_t length, unsigned int *id);
    int drmModeDestroyPropertyBlob(int fd, unsigned int id);
    drmModeAtomicReq* drmModeAtomicAlloc(void);
    void drmModeAtomicFree(drmModeAtomicReq *req);
    int drmModeAtomicAddProperty(drmModeAtomicReq *req, unsigned int object_id, unsigned int property_id, unsigned long long value);
    int drmModeAtomicCommit(int fd, drmModeAtomicReq *req, unsigned int flags, void *user_data);
    int drmModeAddFB2(int fd, unsigned int width, unsigned int height, unsigned int pixel_format,
                      const unsigned int bo_handles[4], const unsigned int pitches[4],
                      const unsigned int offsets[4], unsigned int *buf_id, unsigned int flags);
    int drmModeAddFB2WithModifiers(int fd, unsigned int width, unsigned int height,
                      unsigned int pixel_format, const unsigned int bo_handles[4],
                      const unsigned int pitches[4], const unsigned int offsets[4],
                      const unsigned long long modifier[4], unsigned int *buf_id,
                      unsigned int flags);
    int drmModeRmFB(int fd, unsigned int bufferId);

    // GBM
    typedef unsigned int uint32_t;
    typedef int EGLBoolean;

    // --- GBM Types & Opaque Structs ---
    struct gbm_device;
    struct gbm_surface;
    struct gbm_bo;

    struct gbm_device* gbm_create_device(int fd);
    void gbm_device_destroy(struct gbm_device *gbm);
    struct gbm_surface *gbm_surface_create(
        struct gbm_device *gbm, 
        uint32_t width, 
        uint32_t height, 
        uint32_t format, 
        uint32_t flags
    );
    void gbm_surface_destroy(struct gbm_surface *surface);
    struct gbm_bo *gbm_surface_lock_front_buffer(struct gbm_surface *surface);
    void gbm_surface_release_buffer(struct gbm_surface *surface, struct gbm_bo *bo);
    int gbm_bo_get_plane_count(struct gbm_bo *bo);
    unsigned long long gbm_bo_get_handle_for_plane(struct gbm_bo *bo, int plane);
    uint32_t gbm_bo_get_stride_for_plane(struct gbm_bo *bo, int plane);
    uint32_t gbm_bo_get_offset(struct gbm_bo *bo, int plane);
    unsigned long long gbm_bo_get_modifier(struct gbm_bo *bo);
    
    // EGL
    // --- EGL Types ---
    typedef void *EGLDisplay;
    typedef void *EGLConfig;
    typedef void *EGLSurface;
    typedef void *EGLContext;
    
    EGLDisplay eglGetPlatformDisplay(unsigned int platform, void * native_display, const int * attrib_list);

    int eglInitialize(EGLDisplay dpy, int *major, int *minor);
    EGLSurface eglCreatePlatformWindowSurface(
        EGLDisplay dpy, 
        EGLConfig config, 
        void *native_window, 
        const int32_t *attrib_list
    );
    EGLSurface eglCreatePbufferSurface(
        EGLDisplay dpy,
        EGLConfig config,
        const int *attrib_list
    );

    EGLBoolean eglMakeCurrent(
        EGLDisplay dpy, 
        EGLSurface draw, 
        EGLSurface read, 
        EGLContext ctx
    );    
    EGLBoolean eglDestroyContext(EGLDisplay dpy, EGLContext ctx);
    EGLBoolean eglDestroySurface(EGLDisplay dpy, EGLSurface surface);
    EGLBoolean eglTerminate(EGLDisplay dpy);
    
    /* Additional EGL functions */
    int eglBindAPI(unsigned int api);
    int eglChooseConfig(EGLDisplay dpy, const int *attrib_list, EGLConfig *configs, int config_size, int *num_config);
    int eglGetConfigAttrib(EGLDisplay dpy, EGLConfig config, int attribute, int *value);
    EGLContext eglCreateContext(EGLDisplay dpy, EGLConfig config, EGLContext share_context, const int *attrib_list);
    EGLBoolean eglSwapBuffers(EGLDisplay dpy, EGLSurface surface);
    EGLBoolean eglSwapInterval(EGLDisplay dpy, int interval);
    EGLBoolean eglQuerySurface(EGLDisplay dpy, EGLSurface surface, int attribute, int *value);
    int eglGetError(void);
""")

drm = ffi.dlopen("libdrm.so.2")
gbm = ffi.dlopen("libgbm.so.1")
egl = ffi.dlopen("libEGL.so.1")

# DRM connector, object, client-capability, and atomic flags.
DRM_MODE_CONNECTOR_DPI = 17
DRM_MODE_FLAG_PHSYNC = 1 << 0
DRM_MODE_FLAG_PVSYNC = 1 << 2
DRM_MODE_TYPE_PREFERRED = 1 << 3
DRM_MODE_TYPE_USERDEF = 1 << 5
DRM_CLIENT_CAP_UNIVERSAL_PLANES = 2
DRM_CLIENT_CAP_ATOMIC = 3
DRM_MODE_OBJECT_CRTC = 0xCCCCCCCC
DRM_MODE_OBJECT_CONNECTOR = 0xC0C0C0C0
DRM_MODE_OBJECT_PLANE = 0xEEEEEEEE
DRM_MODE_PAGE_FLIP_EVENT = 0x01
DRM_MODE_ATOMIC_NONBLOCK = 0x0200
DRM_MODE_ATOMIC_ALLOW_MODESET = 0x0400
DRM_MODE_FB_MODIFIERS = 0x02
DRM_PLANE_TYPE_PRIMARY = 1

# GBM formats and usage flags.
GBM_FORMAT_XRGB8888 = 0x34325258
GBM_BO_USE_SCANOUT = 1 << 0
GBM_BO_USE_RENDERING = 1 << 2
DRM_FORMAT_MOD_INVALID = 0xFFFFFFFFFFFFFFFF

# EGL platform, API, config, and surface constants.
EGL_PLATFORM_GBM_KHR = 0x31D7
EGL_PLATFORM_SURFACELESS_MESA = 0x31DD
EGL_OPENGL_API = 0x30A2
EGL_NONE = 0x3038
EGL_ALPHA_SIZE = 0x3021
EGL_BLUE_SIZE = 0x3022
EGL_GREEN_SIZE = 0x3023
EGL_RED_SIZE = 0x3024
EGL_DEPTH_SIZE = 0x3025
EGL_NATIVE_VISUAL_ID = 0x302E
EGL_SURFACE_TYPE = 0x3033
EGL_WINDOW_BIT = 0x0004
EGL_PBUFFER_BIT = 0x0001
EGL_RENDERABLE_TYPE = 0x3040
EGL_OPENGL_BIT = 0x0008
EGL_HEIGHT = 0x3056
EGL_WIDTH = 0x3057
