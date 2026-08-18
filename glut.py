import os


# PyOpenGL selects its platform on first import. GLUT needs the native window
# platform (WGL on Windows, normally GLX on Linux), not EGL.
os.environ.pop('PYOPENGL_PLATFORM', None)


class GLUTDisplay:
    name = 'glut'
