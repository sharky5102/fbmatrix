"""Small optional CFFI binding for the NDI receive and discovery APIs."""
import os
import threading
import time

from cffi import FFI


LIBRARY_ENV = 'FBMATRIX_NDI_LIBRARY'

_CDEF = r"""
typedef struct { const char *p_ndi_name; const char *p_url_address; } NDIlib_source_t;
typedef struct {
    _Bool show_local_sources;
    const char *p_groups;
    const char *p_extra_ips;
} NDIlib_find_create_t;
typedef struct {
    NDIlib_source_t source_to_connect_to;
    int color_format;
    int bandwidth;
    _Bool allow_video_fields;
    const char *p_ndi_recv_name;
} NDIlib_recv_create_v3_t;
typedef struct {
    int xres, yres;
    unsigned int FourCC;
    int frame_rate_N, frame_rate_D;
    float picture_aspect_ratio;
    int frame_format_type;
    long long timecode;
    unsigned char *p_data;
    int line_stride_in_bytes;
    const char *p_metadata;
    long long timestamp;
} NDIlib_video_frame_v2_t;
typedef struct {
    long long video_frames;
    long long audio_frames;
    long long metadata_frames;
} NDIlib_recv_performance_t;
typedef void *NDIlib_find_instance_t;
typedef void *NDIlib_recv_instance_t;

_Bool NDIlib_initialize(void);
void NDIlib_destroy(void);
NDIlib_find_instance_t NDIlib_find_create_v2(const NDIlib_find_create_t *);
void NDIlib_find_destroy(NDIlib_find_instance_t);
_Bool NDIlib_find_wait_for_sources(NDIlib_find_instance_t, unsigned int);
const NDIlib_source_t *NDIlib_find_get_current_sources(NDIlib_find_instance_t, unsigned int *);
NDIlib_recv_instance_t NDIlib_recv_create_v3(const NDIlib_recv_create_v3_t *);
void NDIlib_recv_destroy(NDIlib_recv_instance_t);
void NDIlib_recv_connect(NDIlib_recv_instance_t, const NDIlib_source_t *);
int NDIlib_recv_capture_v3(NDIlib_recv_instance_t, NDIlib_video_frame_v2_t *,
                          void *, void *, unsigned int);
void NDIlib_recv_free_video_v2(NDIlib_recv_instance_t, const NDIlib_video_frame_v2_t *);
void NDIlib_recv_get_performance(NDIlib_recv_instance_t,
                                 NDIlib_recv_performance_t *,
                                 NDIlib_recv_performance_t *);
"""

FRAME_VIDEO = 1
# NDIlib_recv_color_format_BGRX_BGRA is 0; UYVY_BGRA is 1.
COLOR_FORMAT_UYVY_BGRA = 1
BANDWIDTH_HIGHEST = 100
FOURCC_UYVY = 0x59565955


class NDIUnavailable(RuntimeError):
    pass


class Runtime:
    def __init__(self, library_path=None):
        path = library_path or os.environ.get(LIBRARY_ENV)
        if not path:
            raise NDIUnavailable('%s is not set' % LIBRARY_ENV)
        self.ffi = FFI()
        self.ffi.cdef(_CDEF)
        try:
            self.lib = self.ffi.dlopen(path)
        except OSError as e:
            raise NDIUnavailable('Unable to load NDI library %s: %s' % (path, e)) from e
        if not self.lib.NDIlib_initialize():
            raise NDIUnavailable('NDI runtime initialization failed')


class Discovery:
    """Continuously refreshed snapshot of visible NDI source names."""
    def __init__(self, runtime, wait_ms=1000):
        self.runtime = runtime
        self.wait_ms = wait_ms
        self.lock = threading.Lock()
        self._sources = []
        self._stop = threading.Event()
        settings = runtime.ffi.new('NDIlib_find_create_t *')
        settings.show_local_sources = True
        self.finder = runtime.lib.NDIlib_find_create_v2(settings)
        if self.finder == runtime.ffi.NULL:
            raise RuntimeError('Unable to create NDI source finder')
        self.thread = threading.Thread(target=self._run, name='ndi-discovery', daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.is_set():
            self.runtime.lib.NDIlib_find_wait_for_sources(self.finder, self.wait_ms)
            count = self.runtime.ffi.new('unsigned int *')
            sources = self.runtime.lib.NDIlib_find_get_current_sources(self.finder, count)
            names = []
            for index in range(count[0]):
                name = sources[index].p_ndi_name
                if name != self.runtime.ffi.NULL:
                    names.append(self.runtime.ffi.string(name).decode('utf-8', 'replace'))
            with self.lock:
                self._sources = names

    def sources(self):
        with self.lock:
            return list(self._sources)

    def close(self):
        self._stop.set()
        self.thread.join(timeout=(self.wait_ms / 1000.0) + 0.5)
        self.runtime.lib.NDIlib_find_destroy(self.finder)


class Receiver:
    def __init__(self, runtime, source_name):
        self.runtime = runtime
        ffi = runtime.ffi
        self._name = ffi.new('char[]', source_name.encode('utf-8'))
        settings = ffi.new('NDIlib_recv_create_v3_t *')
        settings.source_to_connect_to.p_ndi_name = self._name
        settings.color_format = COLOR_FORMAT_UYVY_BGRA
        settings.bandwidth = BANDWIDTH_HIGHEST
        settings.allow_video_fields = False
        self.receiver = runtime.lib.NDIlib_recv_create_v3(settings)
        if self.receiver == ffi.NULL:
            raise RuntimeError('Unable to create NDI receiver for %s' % source_name)
        self.width = 0
        self.height = 0
        self.source_fps = 0.0
        self.receive_fps = 0.0
        self._sample_started = None
        self._sample_frames = 0

    def receive_video(self, upload, timeout_ms=2):
        """Capture one frame and call upload(data, width, height, stride)."""
        frame = self.runtime.ffi.new('NDIlib_video_frame_v2_t *')
        kind = self.runtime.lib.NDIlib_recv_capture_v3(
            self.receiver, frame, self.runtime.ffi.NULL, self.runtime.ffi.NULL, timeout_ms)
        if kind != FRAME_VIDEO:
            return False
        try:
            if frame.FourCC != FOURCC_UYVY:
                raise RuntimeError('Unsupported NDI video FourCC 0x%08x' % frame.FourCC)
            self.width = frame.xres
            self.height = frame.yres
            if frame.frame_rate_D:
                self.source_fps = frame.frame_rate_N / frame.frame_rate_D
            now = time.monotonic()
            if self._sample_started is None:
                self._sample_started = now
                self._sample_frames = 1
            else:
                self._sample_frames += 1
                elapsed = now - self._sample_started
                if elapsed >= 1.0:
                    self.receive_fps = self._sample_frames / elapsed
                    self._sample_started = now
                    self._sample_frames = 0
            size = frame.line_stride_in_bytes * frame.yres
            # Copy NDI-owned memory before returning the frame. Downstream
            # upload code receives a normal Python value and is independent
            # of both NDI and CFFI.
            data = bytes(self.runtime.ffi.buffer(frame.p_data, size))
            upload(data, frame.xres, frame.yres, frame.line_stride_in_bytes)
            return True
        finally:
            self.runtime.lib.NDIlib_recv_free_video_v2(self.receiver, frame)

    def stats(self):
        total = self.runtime.ffi.new('NDIlib_recv_performance_t *')
        dropped = self.runtime.ffi.new('NDIlib_recv_performance_t *')
        self.runtime.lib.NDIlib_recv_get_performance(self.receiver, total, dropped)
        return {
            'width': self.width,
            'height': self.height,
            'fps': self.receive_fps,
            'source_fps': self.source_fps,
            'frames': int(total.video_frames),
            'dropped': int(dropped.video_frames),
        }

    def close(self):
        if self.receiver != self.runtime.ffi.NULL:
            self.runtime.lib.NDIlib_recv_destroy(self.receiver)
            self.receiver = self.runtime.ffi.NULL
