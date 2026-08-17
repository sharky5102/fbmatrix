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

    typedef struct _drmEventContext {
        int version;
        void (*vblank_handler)(int, unsigned int, unsigned int, unsigned int, void *);
        void (*page_flip_handler)(int, unsigned int, unsigned int, unsigned int, void *);
    } drmEventContext;

    drmModeRes* drmModeGetResources(int fd);
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
    int drmModeRmFB(int fd, unsigned int buffer_id);
    int drmHandleEvent(int fd, drmEventContext *evctx);
    
    // GBM
    typedef unsigned int uint32_t;
    typedef int int32_t;
    typedef intptr_t EGLNativeWindowType;
    typedef int EGLBoolean;

    // --- GBM Types & Opaque Structs ---
    struct gbm_device;
    struct gbm_surface;
    struct gbm_bo;
    union gbm_bo_handle {
        void *ptr;
        int32_t s32;
        uint32_t u32;
        unsigned long long u64;
    };
    
    struct gbm_device* gbm_create_device(int fd);
    void gbm_device_destroy(struct gbm_device *gbm);
    const char *gbm_device_get_backend_name(struct gbm_device *gbm);
    int gbm_device_is_format_supported(struct gbm_device *gbm, uint32_t format, uint32_t usage);
    struct gbm_bo *gbm_bo_create(struct gbm_device *gbm, uint32_t width,
                                 uint32_t height, uint32_t format,
                                 uint32_t flags);
    void gbm_bo_destroy(struct gbm_bo *bo);
    struct gbm_surface *gbm_surface_create(
        struct gbm_device *gbm, 
        uint32_t width, 
        uint32_t height, 
        uint32_t format, 
        uint32_t flags
    );
    struct gbm_bo *gbm_surface_lock_front_buffer(struct gbm_surface *surface);
    void gbm_surface_release_buffer(struct gbm_surface *surface, struct gbm_bo *bo);
    unsigned long long gbm_bo_get_handle(struct gbm_bo *bo);
    uint32_t gbm_bo_get_stride(struct gbm_bo *bo);
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
    int eglTerminate(EGLDisplay dpy);
    
    // --- EGL Functions ---
    EGLSurface eglCreateWindowSurface(
        EGLDisplay dpy, 
        EGLConfig config, 
        EGLNativeWindowType win, 
        const int32_t *attrib_list
    );

    EGLSurface eglCreatePlatformWindowSurface(
        EGLDisplay dpy, 
        EGLConfig config, 
        void *native_window, 
        const int32_t *attrib_list
    );

    EGLBoolean eglMakeCurrent(
        EGLDisplay dpy, 
        EGLSurface draw, 
        EGLSurface read, 
        EGLContext ctx
    );    
    
    /* Additional EGL functions */
    int eglBindAPI(unsigned int api);
    int eglChooseConfig(EGLDisplay dpy, const int *attrib_list, EGLConfig *configs, int config_size, int *num_config);
    int eglGetConfigAttrib(EGLDisplay dpy, EGLConfig config, int attribute, int *value);
    EGLContext eglCreateContext(EGLDisplay dpy, EGLConfig config, EGLContext share_context, const int *attrib_list);
    EGLContext eglGetCurrentContext(void);
    EGLBoolean eglSwapBuffers(EGLDisplay dpy, EGLSurface surface);
    EGLBoolean eglQuerySurface(EGLDisplay dpy, EGLSurface surface, int attribute, int *value);
    int eglGetError(void);
    const char *eglQueryString(EGLDisplay dpy, int name);
""")

drm = ffi.dlopen("libdrm.so.2")
gbm = ffi.dlopen("libgbm.so.1")
egl = ffi.dlopen("libEGL.so.1")
