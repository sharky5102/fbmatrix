import os

os.environ['PYOPENGL_PLATFORM'] = 'egl'

import signal
import sys
import time

import OpenGL.GL as gl
import OpenGL.GLUT as glut

import assembly.tree
import displays.hub75e
import displays.ws2811
import displays.ws2811_ledbuffer
import fbo
import geometry.simple
import ledlayout
from headless import HeadlessDisplay
from kms import KMSDisplay


def signal_handler(sig, frame):
    sys.exit(0)


global_init = False
global_display_backend = None
global_backend = None


def output_mode(displaytype, layout=None):
    if displaytype == 'ws2811':
        if layout is None:
            raise RuntimeError('WS2811 display requires a layout argument')
        strings = ledlayout.require_xyzc_string_layout(
            layout,
            displays.ws2811.MAX_LEDS_PER_STRING,
            displays.ws2811.MAX_STRINGS)
        height = max((len(string) for string in strings), default=0)
        if height == 0:
            raise RuntimeError('WS2811 layout must contain at least one LED')
        return 840, height, 27000, 1, 1, 48
    return 4096, 194, 50000, 0, 0, 0


def output_stats(displaytype, mode, layout=None):
    width, height, clock, vfp, vsync, vbp = mode
    fps = clock * 1000 / (width * (height + vfp + vsync + vbp))
    if displaytype == 'ws2811':
        strings = ledlayout.require_xyzc_string_layout(
            layout,
            displays.ws2811.MAX_LEDS_PER_STRING,
            displays.ws2811.MAX_STRINGS)
        active = sum(
            source_mode != -1
            for string in strings
            for _x, _y, _z, source_mode in string)
        inactive = sum(len(string) for string in strings) - active
        return (
            'FBMatrix: %d strings, %d active LEDs, %d inactive LEDs, '
            '%dx%d, %.2f FPS' %
            (len(strings), active, inactive, width, height, fps))
    return 'FBMatrix: HUB75, %dx%d, %.2f FPS' % (width, height, fps)


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
        backend=None,
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
        self.fps_started = time.monotonic()
        self.fps_frames = 0
        if backend is None:
            backend = ('glut' if self.preview or self.emulate or self.raw
                       else 'kms')
        if backend not in ('kms', 'glut', 'headless'):
            raise ValueError("backend must be 'kms', 'glut', or 'headless'")
        self.backend = backend
        self.use_window_manager = backend == 'glut'
        self.display_backend = None

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

        if self.displaytype == 'ws2811':
            with self.ledfbo:
                self.clear()
                self.ledbuffer.render()

        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

        if self.emulate:
            gl.glViewport(0, 0, int(self.screenWidth / 2), self.screenHeight)
            self.tree.render(time.time() - self.starttime)

            gl.glViewport(
                int(self.screenWidth / 2), 0,
                int(self.screenWidth / 2), self.screenHeight)
            self.texquad.render()
        elif self.preview:
            self.texquad.render()
        else:
            self.signalgenerator.render()

        self.swap_buffers()
        self.report_fps()

        if self.use_window_manager:
            glut.glutPostRedisplay()

    def swap_buffers(self):
        if self.use_window_manager:
            glut.glutSwapBuffers()
        else:
            self.display_backend.present()

    def report_fps(self):
        self.fps_frames += 1
        now = time.monotonic()
        elapsed = now - self.fps_started
        if elapsed < 1.0:
            return

        message = 'FBMatrix: %.1f measured FPS' % (
            self.fps_frames / elapsed)
        if (self.display_backend is not None and
                hasattr(self.display_backend, 'consume_timings')):
            timings = self.display_backend.consume_timings()
            if timings is not None:
                message += ', GPU %.1f ms, KMS (wait for vsync) %.1f ms' % timings
        if sys.stderr.isatty():
            print('\r' + message, end='', file=sys.stderr, flush=True)
        else:
            print(message, file=sys.stderr, flush=True)
        self.fps_started = now
        self.fps_frames = 0

    def reshape(self, width, height):
        self.screenWidth = width
        self.screenHeight = height
        gl.glViewport(0, 0, width, height)

    def keyboard(self, key, x, y):
        if key == b'\033':
            try:
                glut.glutLeaveMainLoop()
            except Exception:
                glut.glutDestroyWindow(glut.glutGetWindow())

    def init(self):
        global global_init, global_display_backend, global_backend

        kms_args = output_mode(self.displaytype, self.layout)

        if not global_init:
            if self.backend == 'glut':
                self.init_glut()
            elif self.backend == 'headless':
                global_display_backend = HeadlessDisplay()
            else:
                print(output_stats(
                    self.displaytype, kms_args, self.layout), file=sys.stderr)
                global_display_backend = KMSDisplay(*kms_args)
            global_backend = self.backend
            global_init = True

        if self.backend != global_backend:
            raise RuntimeError(
                'Cannot mix %s and %s display backends in one process' %
                (global_backend, self.backend))

        if self.backend != 'glut':
            self.display_backend = global_display_backend
            self.screenWidth = self.display_backend.width
            self.screenHeight = self.display_backend.height

        self.mainfbo = fbo.FBO(
            self.source_columns,
            self.source_rows,
            mag_filter=gl.GL_NEAREST,
            min_filter=gl.GL_LINEAR_MIPMAP_LINEAR,
        )
        print('FBMatrix: source framebuffer %dx%d' % (
            self.source_columns, self.source_rows), file=sys.stderr)

        if self.displaytype == 'ws2811':
            if self.layout is None:
                raise RuntimeError('WS2811 display requires a layout argument')
            self.ledbuffer = displays.ws2811_ledbuffer.ledbuffer(
                self.layout, supersample=self.supersample)
            self.ledbuffer.setTexture(self.mainfbo.getTexture())
            self.ledfbo = fbo.FBO(
                self.ledbuffer.width,
                self.ledbuffer.height,
                mag_filter=gl.GL_NEAREST,
                min_filter=gl.GL_NEAREST,
            )
            self.signalgenerator = displays.ws2811.signalgenerator(
                self.layout, supersample=self.supersample)
            self.signalgenerator.setTexture(self.ledfbo.getTexture())
        elif self.displaytype == 'hub75e':
            self.signalgenerator = displays.hub75e.signalgenerator(
                columns=self.columns,
                rows=self.rows,
                supersample=self.supersample,
                order=self.order,
                oe=self.oe,
                extract=self.extract,
            )
            self.signalgenerator.setTexture(self.mainfbo.getTexture())

        if self.emulate or self.preview:
            self.texquad = geometry.simple.texquad()
            self.texquad.setTexture(self.mainfbo.getTexture())

        if self.emulate:
            if self.layout is None:
                raise RuntimeError('Emulation requires a layout argument')
            self.tree = assembly.tree.tree(
                displays.ws2811.flatten_layout(self.layout),
                supersample=self.supersample,
                emitter_shape=(self.ledbuffer.width, self.ledbuffer.height),
                string_lengths=[len(string)
                                for string in self.ledbuffer.strings])
            self.tree.setTexture(self.ledfbo.getTexture())

    def init_glut(self):
        glut.glutInit()
        glut.glutInitDisplayMode(
            glut.GLUT_DOUBLE | glut.GLUT_RGBA |
            glut.GLUT_DEPTH | glut.GLUT_ALPHA)
        glut.glutCreateWindow(b'fbmatrix')

        if self.preview or self.raw:
            glut.glutReshapeWindow(512, 512)
        elif self.emulate:
            glut.glutReshapeWindow(1024, 512)

        glut.glutReshapeFunc(lambda w, h: self.reshape(w, h))
        glut.glutDisplayFunc(lambda: self.display())
        glut.glutKeyboardFunc(lambda k, x, y: self.keyboard(k, x, y))

    def run(self, render):
        self.render = render
        signal.signal(signal.SIGINT, signal_handler)

        if self.use_window_manager:
            glut.glutMainLoop()
        else:
            while True:
                self.display()
