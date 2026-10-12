import os
import sys


# Collection imports fbmserve (and therefore OpenGL) before test_fbmatrix.
# Select EGL before any test module initializes PyOpenGL's global platform.
if sys.platform != 'win32':
    os.environ['PYOPENGL_PLATFORM'] = 'egl'
