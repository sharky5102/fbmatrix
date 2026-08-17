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
import fbo
import geometry.simple
from headless import HeadlessDisplay
from kms import KMSDisplay


def signal_handler(sig, frame):
    sys.exit(0)


global_init = False
global_display_backend = None
global_backend = None


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

        if self.use_window_manager:
            glut.glutPostRedisplay()

    def swap_buffers(self):
        if self.use_window_manager:
            glut.glutSwapBuffers()
        else:
            self.display_backend.present()

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

        if not global_init:
            if self.backend == 'glut':
                self.init_glut()
            elif self.backend == 'headless':
                global_display_backend = HeadlessDisplay()
            else:
                global_display_backend = KMSDisplay()
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

        if self.displaytype == 'ws2811':
            if self.layout is None:
                raise RuntimeError('WS2811 display requires a layout argument')
            self.signalgenerator = displays.ws2811.signalgenerator(
                self.layout, supersample=self.supersample)
            self.signalgenerator.setTexture(self.mainfbo.getTexture())
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
                supersample=self.supersample)
            self.tree.setTexture(self.mainfbo.getTexture())

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
