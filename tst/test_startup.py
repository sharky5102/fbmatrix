"""Exercise startup before another test can initialize PyOpenGL's platform."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('flag', [None, '--emulate', '--preview', '--raw'])
def test_server_selects_platform_before_effect_discovery(flag):
    script = r'''
import os
import sys

import fbmserve

assert 'OpenGL.platform' not in sys.modules
discover = fbmserve.get_shader_effect

def checked_shader_effect():
    # Both backends configure the environment before importing OpenGL.
    windowed = sys.platform == 'win32' or any(
        flag in sys.argv for flag in ('--emulate', '--preview', '--raw'))
    if windowed:
        assert 'glut' in sys.modules
        assert 'PYOPENGL_PLATFORM' not in os.environ
    else:
        assert 'kms' in sys.modules
        assert os.environ['PYOPENGL_PLATFORM'] == 'egl'
    module = discover()
    from OpenGL import platform
    assert (type(platform.PLATFORM).__name__ == 'EGLPlatform') == (not windowed)
    return module

class StartupComplete(Exception):
    pass

def stop_before_context(*args, **kwargs):
    # Discovery and state loading must still succeed before context creation.
    raise StartupComplete

fbmserve.get_shader_effect = checked_shader_effect
fbmserve.common.renderer_from_args = stop_before_context
sys.argv += ['--state-file', os.devnull]
try:
    fbmserve.main()
except StartupComplete:
    pass
else:
    raise AssertionError('Startup did not reach renderer creation')
'''
    env = os.environ.copy()
    # Simulate an inherited, incorrect setting: the selected backend must win.
    env['PYOPENGL_PLATFORM'] = 'egl' if flag or sys.platform == 'win32' else 'glx'
    env.pop('XDG_SESSION_TYPE', None)
    env.pop('WAYLAND_DISPLAY', None)
    result = subprocess.run(
        [sys.executable, '-c', script] + ([flag] if flag else []),
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
