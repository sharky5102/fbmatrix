import sys
import os
IS_WINDOWS = sys.platform == 'win32'

# Import the backend before OpenGL: each backend selects the appropriate
# PyOpenGL platform before PyOpenGL performs its process-global initialization.
if IS_WINDOWS:
    from glut import GLUTDisplay
else:
    from headless import HeadlessDisplay

import json
import math
import numpy as np
import OpenGL.GL as gl
import OpenGL.GLUT as glut
import time
import fbo
import signal
import subprocess
import tempfile
from unittest import mock

import common
import displays.ws2811
import displays.hub75e
import geometry.simple
import assembly.tree
import fbmatrix
import led_effect
import ledlayout
if IS_WINDOWS:
    # Names used by decorators in the skipped Linux-only test class must still
    # exist while unittest collects the module.
    class KMSDisplay:
        _device_has_dpi = None
        _card_devices = None
else:
    from kms import KMSDisplay, _DRMDevice
    from ffi_backend import (
        DRM_MODE_FLAG_PHSYNC,
        DRM_MODE_FLAG_PVSYNC,
        DRM_MODE_TYPE_USERDEF,
        ffi,
    )

import unittest
from OpenGL.GL.EXT.framebuffer_object import *

test_backend = GLUTDisplay() if IS_WINDOWS else HeadlessDisplay()

def hub75_decompose(data):
    pixels = np.frombuffer(data, dtype=[('r', 'B'), ('g', 'B'), ('b', 'B'), ('a', 'B')])
    
    channels = {
        'D': ('r', 0),
        'LAT': ('r', 1),
        'A': ('r', 2),
        'B2': ('r', 3),
        'E': ('r', 4),
        'B': ('r', 6),
        'C': ('r', 7),
        'R2': ('g', 0),
        'G1': ('g', 1),
        'G2': ('g', 4),
        'CLK': ('g', 5),
        'OE': ('b', 0),
        'R1': ('b', 1),
        'B1': ('b', 2)
    }
    
    output = {}

    for name, source in channels.items():
        channel = np.bitwise_and(pixels[source[0]], 1 << source[1])
        channel = np.where(channel > 0, np.ubyte(ord('1')), np.ubyte(ord('_')))
        
        output[name] = channel.tobytes().decode('utf-8')
            
    return output

def scanlines(data, stride):
    if len(data) % stride != 0:
        raise RuntimeError('Data len %d not divisible by stride %d' % (len(data), stride))
        
    end = len(data)
    for i in range(0, int(len(data)/stride)):
        yield data[end-(i+1)*stride:end-i*stride]

def parseFrameData(data, width):
    for scanline in scanlines(data, width * 4):
        yield hub75_decompose(scanline)

def hub75ToText(data, width):
    n = 0;
    for decomposed in parseFrameData(data, width):
        yield 'Scanline %d' % n
        for chan in [ 'A', 'B', 'C', 'D', 'E', 'OE', 'LAT', 'CLK', 'R1', 'G1', 'B1', 'R2', 'G2', 'B2' ]:
            yield('%05s %s' % (chan, decomposed[chan]))
        n+=1

def render_solid(color):
    gl.glClearColor(color[0], color[1], color[2], 1)
    gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

class TestHub75(unittest.TestCase):
    height = 194
    width = 4096
    maxDiff = None
    
    def setup(self):
        pass

    def testPatternWhite(self):
        gl.glClearColor(1,1,1,1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def writeFrameData(self, filename, data):
        with open(filename, 'wt') as f:
            for line in hub75ToText(data, self.width):
                f.write(line + '\n')
                
    def assertFrameData(self, filename, data):
        self.writeFrameData(filename + '.new', data)
            
        with open(filename, 'rt') as f:
            for expected, actual in zip(f.readlines(), hub75ToText(data, self.width)):
                self.assertEqual(expected.rstrip(), actual)
        
    def testSimple16Scan(self):
        self.renderer = fbmatrix.renderer(backend=test_backend)
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: self.testPatternWhite()
            self.renderer.display()       

            data = gl.glReadPixels(0, 0, 4096, 194, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None);

        self.assertFrameData('tst/data/hub75_32x32_white.txt', data)

    def testFieldFirstOrder(self):
        self.renderer = fbmatrix.renderer(
            order='field-first', backend=test_backend)
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: self.testPatternWhite()
            self.renderer.display()       

            data = gl.glReadPixels(0, 0, 4096, 194, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None);

        self.assertFrameData('tst/data/hub75_fieldfirst_32x32_white.txt', data)

    def testSourceFramebufferSize(self):
        self.renderer = fbmatrix.renderer(
            source_columns=64, source_rows=48, backend=test_backend)

        self.assertEqual(64, self.renderer.mainfbo.width)
        self.assertEqual(48, self.renderer.mainfbo.height)

    def testSourceFramebufferUsesMipmaps(self):
        self.renderer = fbmatrix.renderer(
            source_columns=64, source_rows=64, backend=test_backend)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.renderer.mainfbo.getTexture())

        self.assertEqual(
            gl.GL_LINEAR_MIPMAP_LINEAR,
            gl.glGetTexParameteriv(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER),
        )

class TestWS2811(unittest.TestCase):
    height = 500
    width = 840
    layout = [[[0.0, 0.0, 0.0, 0]] * 500 for _ in range(14)]

    def readFrameData(self, color, layout=None):
        self.renderer = fbmatrix.renderer(
            display='ws2811', layout=layout or self.layout,
            backend=test_backend)
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: render_solid(color)
            self.renderer.display()

            return gl.glReadPixels(0, self.height-2, self.width, 2, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

    def writeFrameData(self, filename, data):
        with open(filename, 'wt') as f:
            for line in hub75ToText(data, self.width):
                f.write(line + '\n')

    def assertFrameData(self, filename, data):
        self.writeFrameData(filename + '.new', data)

        with open(filename, 'rt') as f:
            self.assertEqual([line.rstrip() for line in f], list(hub75ToText(data, self.width)))

    def testRedFrameData(self):
        data = self.readFrameData((1, 0, 0))
        self.assertFrameData('tst/data/ws2811_red.txt', data)

    def testMultipleUniverses(self):
        layout = [string.copy() for string in self.layout]
        layout[0][0] = [0.0, 0.0, 0.0, 1] # red override
        layout[1][0] = [0.0, 0.0, 0.0, 2] # green override
        layout[2][0] = [0.0, 0.0, 0.0, 3] # blue override
        layout[0][1] = [0.0, 0.0, 0.0, 2] # green override
        layout[1][1] = [0.0, 0.0, 0.0, 3] # blue override
        layout[2][1] = [0.0, 0.0, 0.0, 1] # red override

        data = self.readFrameData((1, 1, 0), layout=layout)
        self.assertFrameData('tst/data/ws2811_multiple_universes.txt', data)

    def testInactiveSourceModeRendersBlack(self):
        layout = [string.copy() for string in self.layout]
        layout[0][0] = [0.0, 0.0, 0.0, -1]
        layout[1][0] = [0.0, 0.0, 0.0, -1]
        layout[2][0] = [0.0, 0.0, 0.0, -1]

        data = self.readFrameData((1, 1, 1), layout=layout)
        first_pixel = next(parseFrameData(data, self.width))

        self.assertTrue(first_pixel['R1'].startswith('1111111____________________________'))
        self.assertTrue(first_pixel['G1'].startswith('1111111____________________________'))
        self.assertTrue(first_pixel['B1'].startswith('1111111____________________________'))

    def testEmulationAcceptsLayout(self):
        fbmatrix.renderer(
            display='ws2811', layout=self.layout, emulate=True,
            backend=test_backend)

    def testEmitterBufferPreservesStringRowsAndLedColumns(self):
        layout = [
            [[0, 0, 0, 0], [1, 0, 0, 0]],
            [[0, 1, 0, 0]],
        ]
        renderer = fbmatrix.renderer(
            display='ws2811', layout=layout, backend=test_backend)
        self.assertEqual((2, 2),
                         (renderer.ledfbo.width, renderer.ledfbo.height))

        renderer.ledbuffer.set_effect_source("""
            void mainLed(out vec4 ledColor, in vec3 ledPosition,
                         in float ledIndex, in int stringIndex,
                         in int sourceMode) {
                ledColor = vec4(ledIndex, float(stringIndex), 0.0, 1.0);
            }
        """)
        screen = fbo.FBO(self.width, 2)
        with screen:
            renderer.render = lambda: render_solid((0, 0, 0))
            renderer.display()
        with renderer.ledfbo:
            data = gl.glReadPixels(
                0, 0, 2, 2, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        pixels = np.frombuffer(data, dtype=np.uint8).reshape((2, 2, 4))
        self.assertEqual((0, 0), tuple(pixels[0, 0, :2]))
        self.assertEqual((255, 0), tuple(pixels[0, 1, :2]))
        self.assertEqual((0, 255), tuple(pixels[1, 0, :2]))
        self.assertEqual((0, 0, 0), tuple(pixels[1, 1, :3]))

    def testEmitterBufferAppliesBrightnessToFramebufferInput(self):
        layout = [[[0, 0, 0, 0]]]
        renderer = fbmatrix.renderer(
            display='ws2811', layout=layout, backend=test_backend)

        with renderer.mainfbo:
            render_solid((0.8, 0.4, 0.2))
        renderer.ledbuffer.set_params(0.0, 0.0, 0.5)

        with renderer.ledfbo:
            renderer.clear()
            renderer.ledbuffer.render()
            data = gl.glReadPixels(
                0, 0, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

        pixel = np.frombuffer(data, dtype=np.uint8).reshape((1, 1, 4))[0, 0]
        np.testing.assert_allclose(pixel[:3], (102, 51, 26), atol=1)

    def testEmitterEffectsCompileAndRenderForTwoDimensionalLayout(self):
        layout = [
            [[0, 0, 0, 0], [1, 0, 0, 0], [2, 0, 0, 0]],
            [[0, 1, 0, 0], [1, 1, 0, 0]],
        ]
        renderer = fbmatrix.renderer(
            display='ws2811', layout=layout,
            backend=test_backend)

        with renderer.mainfbo:
            render_solid((0.25, 0.5, 0.75))

        for effect in led_effect.discover_effects('led_effects'):
            renderer.ledbuffer.set_effect_source(
                led_effect.load_effect_source('led_effects', effect['id']))
            renderer.ledbuffer.set_params(1.25, 0.3, 0.8)

            while gl.glGetError() != gl.GL_NO_ERROR:
                pass
            with renderer.ledfbo:
                renderer.clear()
                renderer.ledbuffer.render()
                data = gl.glReadPixels(
                    0, 0, 3, 2, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

            self.assertEqual(
                gl.GL_NO_ERROR, gl.glGetError(),
                'GL error while rendering emitter effect %s' % effect['id'])
            self.assertEqual(
                3 * 2 * 4, len(data),
                'Unexpected output size for emitter effect %s' % effect['id'])

    def testOutputHeightUsesLongestString(self):
        layout = [
            [[0, 0, 0, 0]] * 73,
            [[0, 0, 0, 0]] * 200,
            [[0, 0, 0, 0]] * 12,
        ]
        self.assertEqual((840, 200, 27000, 1, 1, 48),
                         fbmatrix.output_mode('ws2811', layout))

    @unittest.skipIf(IS_WINDOWS, 'KMS is only available on Linux')
    def testManualKmsModeUsesOutputHeight(self):
        mode = KMSDisplay._create_mode(840, 200, 27000, 1, 1, 48)
        self.assertEqual((840, 840, 840, 840),
                         (mode.hdisplay, mode.hsync_start,
                          mode.hsync_end, mode.htotal))
        self.assertEqual((200, 201, 202, 250),
                         (mode.vdisplay, mode.vsync_start,
                          mode.vsync_end, mode.vtotal))
        self.assertEqual(DRM_MODE_TYPE_USERDEF, mode.type)
        self.assertEqual(
            DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC, mode.flags)


@unittest.skipIf(IS_WINDOWS, 'KMS is only available on Linux')
class TestKMSOutputModes(unittest.TestCase):
    @mock.patch('kms.os.close')
    @mock.patch('kms.egl')
    @mock.patch('kms.gbm')
    @mock.patch('kms.drm')
    def testKmsCloseReleasesResourcesOnce(
            self, drm_api, gbm_api, egl_api, close_fd):
        display = object.__new__(KMSDisplay)
        display.closed = False
        display.fd = 10
        display.master = True
        display.mode_blob_id = 7
        display.current_bo = ffi.cast('struct gbm_bo *', 1)
        display.gbm_surface = ffi.cast('struct gbm_surface *', 2)
        display.gbm_device = ffi.cast('struct gbm_device *', 3)
        display.egl_display = ffi.cast('EGLDisplay', 4)
        display.egl_surface = ffi.cast('EGLSurface', 5)
        display.egl_context = ffi.cast('EGLContext', 6)
        display.framebuffers = {1: 20, 2: 21}
        display._disable_scanout = mock.Mock()

        display.close()
        display.close()

        display._disable_scanout.assert_called_once_with()
        gbm_api.gbm_surface_release_buffer.assert_called_once()
        self.assertCountEqual(
            [mock.call(10, 20), mock.call(10, 21)],
            drm_api.drmModeRmFB.call_args_list)
        egl_api.eglDestroyContext.assert_called_once()
        egl_api.eglDestroySurface.assert_called_once()
        egl_api.eglTerminate.assert_called_once()
        gbm_api.gbm_surface_destroy.assert_called_once()
        gbm_api.gbm_device_destroy.assert_called_once()
        drm_api.drmModeDestroyPropertyBlob.assert_called_once_with(10, 7)
        drm_api.drmDropMaster.assert_called_once_with(10)
        close_fd.assert_called_once_with(10)

    def testDrmOwnershipScopeAlwaysReleasesPointer(self):
        pointer = ffi.new('int *')
        release = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, 'test failure'):
            with _DRMDevice._owned(
                    lambda: pointer, release, 'not allocated') as owned:
                self.assertEqual(pointer, owned)
                raise RuntimeError('test failure')

        release.assert_called_once_with(pointer)

    def testDrmDeviceDescription(self):
        display = object.__new__(KMSDisplay)
        display.device = '/dev/dri/card2'
        display.connector_name = 'DPI-1'
        display.connector_id = 49
        self.assertEqual(
            'FBMatrix: DRM card card2 (/dev/dri/card2), '
            'output DPI-1 (connector 49)',
            display._device_description())

    @mock.patch('kms.glob.glob')
    def testDrmCardsAreNaturallySorted(self, glob_cards):
        glob_cards.return_value = [
            '/dev/dri/card10', '/dev/dri/card2',
            '/dev/dri/card0', '/dev/dri/card0-HDMI-A-1',
        ]
        self.assertEqual(
            ['/dev/dri/card0', '/dev/dri/card2', '/dev/dri/card10'],
            KMSDisplay._card_devices())

    @mock.patch.object(KMSDisplay, '_device_has_dpi',
                       side_effect=[False, True])
    @mock.patch('kms.os.close')
    @mock.patch('kms.os.open', side_effect=[10, 11])
    @mock.patch.object(KMSDisplay, '_card_devices', return_value=[
        '/dev/dri/card0', '/dev/dri/card1'])
    def testSelectsCardContainingDpi(self, _cards, open_device, close_device,
                                     has_dpi):
        self.assertEqual(
            ('/dev/dri/card1', 11), KMSDisplay._open_dpi_device())
        self.assertEqual(
            [mock.call('/dev/dri/card0', os.O_RDWR | os.O_CLOEXEC),
             mock.call('/dev/dri/card1', os.O_RDWR | os.O_CLOEXEC)],
            open_device.call_args_list)
        close_device.assert_called_once_with(10)
        self.assertEqual([mock.call(10), mock.call(11)],
                         has_dpi.call_args_list)

    def testHub75UsesFixedOutputMode(self):
        self.assertEqual((4096, 194, 50000, 0, 0, 0),
                         fbmatrix.output_mode('hub75e'))

        mode = KMSDisplay._create_mode(*fbmatrix.output_mode('hub75e'))
        self.assertEqual((4096, 194), (mode.hdisplay, mode.vdisplay))

    def testWs2811StartupStats(self):
        layout = [
            [[0, 0, 0, 0], [0, 0, 0, -1]],
            [],
            [[0, 0, 0, 2]],
        ]
        mode = fbmatrix.output_mode('ws2811', layout)
        self.assertEqual(
            'FBMatrix: 3 strings, 2 active LEDs, 1 inactive LEDs, '
            '840x2, 618.13 FPS',
            fbmatrix.output_stats('ws2811', mode, layout))

    def testHub75StartupStats(self):
        mode = fbmatrix.output_mode('hub75e')
        self.assertEqual(
            'FBMatrix: HUB75, 4096x194, 62.92 FPS',
            fbmatrix.output_stats('hub75e', mode))


class TestLayout(unittest.TestCase):
    def testActiveBoundsExcludeInactivePadding(self):
        layout = [[
            (-1, -0.5, 0, 0),
            (1, 0.5, 0, 0),
            (10, 10, 0, -1),
        ]]
        self.assertEqual((-1.0, 1.0, -0.5, 0.5),
                         ledlayout.active_xy_bounds(layout))

    def testPhysicalCoordinatesNormalizeToTextureCoordinates(self):
        bounds = (-1.0, 1.0, -0.5, 0.5)
        self.assertEqual((0.0, 0.0),
                         ledlayout.normalized_xy(-1, 0.5, bounds))
        self.assertEqual((1.0, 1.0),
                         ledlayout.normalized_xy(1, -0.5, bounds))

    def testLayoutSourceSizeUsesActiveAspect(self):
        layout = [[
            (-1.0, -0.8, 0, 0), (-0.9, -0.8, 0, 0),
            (-0.8, -0.8, 0, 0), (1.0, 0.8, 0, -1),
        ], [
            (-1.0, 0.8, 0, 0), (-0.9, 0.8, 0, 0),
            (-0.8, 0.8, 0, 0), (1.0, -0.8, 0, 0),
        ]]
        self.assertEqual((84, 68), common.layout_source_size(layout, 4))

    def testTypicalActiveSpacingIgnoresInactiveBreaks(self):
        layout = [[
            (0, 0, 0, 0), (0.1, 0, 0, 0),
            (20, 20, 0, -1),
            (1, 1, 0, 0), (1.1, 1, 0, 0),
        ]]
        self.assertAlmostEqual(0.1, ledlayout.typical_active_spacing(layout))

    def testStringLayoutRejectsStringsOver2000Leds(self):
        with self.assertRaisesRegex(RuntimeError, 'string 0 contains 2001 LEDs'):
            ledlayout.require_xyzc_string_layout(
                [[[0.0, 0.0, 0.0, 0]] * 2001])

    def testStringLayoutPreservesStringBoundaries(self):
        self.assertEqual(
            ledlayout.require_xyzc_string_layout([
                [[0, 0, 0, 0]],
                [[1, 1, 0, -1], [2, 2, 0, 0]],
            ]),
            [
                [(0.0, 0.0, 0.0, 0)],
                [(1.0, 1.0, 0.0, -1), (2.0, 2.0, 0.0, 0)],
            ],
        )

    def testStringLayoutAllowsEmptyStringsForPinSelection(self):
        self.assertEqual(
            ledlayout.require_xyzc_string_layout([
                [],
                [[1, 1, 0, 0]],
            ]),
            [[], [(1.0, 1.0, 0.0, 0)]],
        )

    def testLayoutRequiresColorMarker(self):
        with self.assertRaisesRegex(RuntimeError, r'\[x, y, z, c\]'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0]])

    def testLayoutSourceModeMustBeInteger(self):
        with self.assertRaisesRegex(RuntimeError, 'integer'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0, 1.5]])

    def testLayoutSourceModeMustBeKnown(self):
        with self.assertRaisesRegex(RuntimeError, '-1, 0, 1, 2, 3 or 4'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0, 5]])

    def testLayoutAcceptsInactiveSourceMode(self):
        self.assertEqual(
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0, -1]]),
            [(0.0, 0.0, 0.0, -1)],
        )

    def testLoadLayoutClearsColorSourceModesByDefault(self):
        with tempfile.NamedTemporaryFile('wt', suffix='.json', delete=False) as f:
            f.write('[[[0, 0, 0, 2]]]')
            filename = f.name

        try:
            self.assertEqual(common.load_layout(filename), [[(0.0, 0.0, 0.0, 0)]])
        finally:
            os.unlink(filename)

    def testLoadLayoutPreservesInactiveSourceModeByDefault(self):
        with tempfile.NamedTemporaryFile('wt', suffix='.json', delete=False) as f:
            f.write('[[[0, 0, 0, -1]]]')
            filename = f.name

        try:
            self.assertEqual(common.load_layout(filename), [[(0.0, 0.0, 0.0, -1)]])
        finally:
            os.unlink(filename)

    def testLoadLayoutCanPreserveSourceModes(self):
        with tempfile.NamedTemporaryFile('wt', suffix='.json', delete=False) as f:
            f.write('[[[0, 0, 0, 2]]]')
            filename = f.name

        try:
            self.assertEqual(common.load_layout(filename, preserve_source_modes=True), [[(0.0, 0.0, 0.0, 2)]])
        finally:
            os.unlink(filename)


class TestGenerateLayout(unittest.TestCase):
    def runGenerator(self, *args):
        script = os.path.abspath('generate-layout.py')
        return subprocess.run(
            [sys.executable, script] + list(args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def assertLayoutStats(self, result, layout_type, total, active=None, inactive=None, sections=None, section_leds=250):
        self.assertIn('Layout type: %s' % layout_type, result.stderr)
        self.assertIn('Total LEDs: %d' % total, result.stderr)

        if active is not None:
            self.assertIn('Active LEDs: %d' % active, result.stderr)
        if inactive is not None:
            self.assertIn('Inactive LEDs: %d' % inactive, result.stderr)
        if sections is not None:
            self.assertIn('Sections: %d' % sections, result.stderr)
            self.assertIn('Section slots: %d' % section_leds, result.stderr)
            self.assertIn('Max used LEDs per section:', result.stderr)
            self.assertIn('Max active LEDs per section:', result.stderr)
            self.assertIn('Max inactive LEDs per section:', result.stderr)

    def testSquareLayoutRequiresExplicitType(self):
        result = self.runGenerator('square', '--columns', '2', '--rows', '2')

        self.assertLayoutStats(result, 'square', 4, active=4, inactive=0)
        self.assertNotIn('Sections:', result.stderr)
        self.assertEqual([[
            [-0.5, -0.5, 0, 1],
            [0.5, -0.5, 0, 1],
            [0.5, 0.5, 0, 2],
            [-0.5, 0.5, 0, 2],
        ]], json.loads(result.stdout))

    def testSquareLayoutUsesConfiguredStringLength(self):
        result = self.runGenerator(
            'square', '--columns', '25', '--rows', '18',
            '--string-leds', '200')

        self.assertEqual(0, result.returncode)
        strings = json.loads(result.stdout)
        self.assertEqual([200, 200, 50], list(map(len, strings)))

    def testStringLengthMustBePositive(self):
        result = self.runGenerator(
            'square', '--columns', '2', '--rows', '2',
            '--string-leds', '0')

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            '--string-leds must be greater than zero', result.stderr)

    def testRadialStringLengthMustContainWholeSections(self):
        result = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--section-leds', '200',
            '--string-leds', '300',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            '--string-leds must be a multiple of --section-leds',
            result.stderr)

    def testRadialStringsDoNotSplitSections(self):
        result = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--section-leds', '200',
            '--string-leds', '200',
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual([200] * 8,
                         list(map(len, json.loads(result.stdout))))

    def testRadialLayoutGeneratesFixedSectionsWithInactiveHopsAndPadding(self):
        result = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--source-modes', 'framebuffer',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'radial', len(layout), sections=8)
        self.assertIn(
            'Perimeter crossings top: 0.128, 1.129, 1.938, 2.655, 3.345, 4.062, 4.871, 5.872',
            result.stderr,
        )
        self.assertIn(
            'Perimeter crossings left: 1.038, 1.896, 2.590, 3.205, 3.795, 4.410, 5.104, 5.962',
            result.stderr,
        )
        self.assertIn('Radial section top-left/0: 4 spokes', result.stderr)
        self.assertIn('Radial section top-left/1: 4 spokes', result.stderr)

        self.assertEqual(8 * 250, len(layout))
        self.assertTrue(all(len(lamp) == 4 for lamp in layout))
        self.assertTrue(all(-1.0 <= lamp[0] <= 1.0 for lamp in layout))
        self.assertTrue(all(-1.0 <= lamp[1] <= 1.0 for lamp in layout))
        self.assertTrue(any(lamp[3] == -1 for lamp in layout))
        self.assertTrue(any(lamp[3] == 0 for lamp in layout))

        non_padding_points = [lamp for lamp in layout if lamp[:3] != [0.0, 0.0, 0]]
        self.assertLessEqual(max(abs(lamp[0]) for lamp in non_padding_points), 6.0 / 7.0 + 1e-6)
        self.assertAlmostEqual(1.0, max(abs(lamp[1]) for lamp in non_padding_points), places=6)

        active_points = {(round(lamp[0], 6), round(lamp[1], 6)) for lamp in layout if lamp[3] == 0}
        for x, y in active_points:
            self.assertIn((round(-x, 6), y), active_points)
            self.assertIn((x, round(-y, 6)), active_points)

    def testRadialLayoutColorsSpokesInsteadOfSections(self):
        result = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        first_section = layout[:250]
        active_runs = []
        current_mode = None

        for lamp in first_section:
            mode = lamp[3]
            if mode in (1, 2, 3):
                if mode != current_mode:
                    active_runs.append(mode)
                    current_mode = mode
            else:
                current_mode = None

        self.assertEqual([3, 1, 2, 3], active_runs)

    def testRadialLayoutRequiresSpokesDivisibleByEight(self):
        result = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '52',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn('divisible by 8', result.stderr)

    def testRadialLayoutSplitsQuartersIntoHubToHubSections(self):
        result = self.runGenerator(
            'radial',
            '--width', '7',
            '--height', '6',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '48',
            '--max-spoke-length', '3.2',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'radial', len(layout), sections=8)
        self.assertEqual(8 * 250, len(layout))

        hub_radius = 0.2 / (7.0 / 2.0)
        for section_index in range(0, 8):
            section = layout[section_index * 250:(section_index + 1) * 250]
            used = [lamp for lamp in section if lamp[3] != -1 or lamp[:3] != [0.0, 0.0, 0]]
            self.assertAlmostEqual(hub_radius, math.hypot(used[0][0], used[0][1]), places=6)
            self.assertAlmostEqual(hub_radius, math.hypot(used[-1][0], used[-1][1]), places=6)

    def testRadialLayoutCanSplitQuarterIntoUnevenHubToHubSections(self):
        result = self.runGenerator(
            'radial',
            '--width', '7',
            '--height', '6',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '56',
            '--max-spoke-length', '3.2',
            '--section-leds', '280',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'radial', len(layout), sections=8, section_leds=280)
        self.assertIn('Radial section top-left/0: 6 spokes', result.stderr)
        self.assertIn('Radial section top-left/1: 8 spokes', result.stderr)
        self.assertEqual(8 * 280, len(layout))

    def testDualRadialLayoutGeneratesFixedSectionsWithCenterRuns(self):
        result = self.runGenerator(
            'dual-radial',
            '--width', '4',
            '--height', '5',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--center-spacing', '1.6',
            '--max-spoke-length', '2.2',
            '--source-modes', 'framebuffer',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'dual-radial', len(layout), sections=8)
        self.assertIn(
            'Perimeter crossings top: 0.442, 0.954, 1.372, 1.791, 2.209, 2.628, 3.046, 3.558',
            result.stderr,
        )
        self.assertIn(
            'Perimeter crossings right: 0.255, 1.038, 1.515, 1.859, 2.136, 2.382, 2.618, 2.864, 3.141, 3.485, 3.962, 4.745',
            result.stderr,
        )

        self.assertEqual(8 * 250, len(layout))
        self.assertTrue(all(len(lamp) == 4 for lamp in layout))
        self.assertTrue(all(-1.0 <= lamp[0] <= 1.0 for lamp in layout))
        self.assertTrue(all(-1.0 <= lamp[1] <= 1.0 for lamp in layout))
        self.assertTrue(any(lamp[3] == -1 for lamp in layout))
        self.assertTrue(any(lamp[3] == 0 for lamp in layout))

        non_padding_points = [lamp for lamp in layout if lamp[:3] != [0.0, 0.0, 0]]
        self.assertLessEqual(max(abs(lamp[0]) for lamp in non_padding_points), 4.0 / 5.0 + 1e-6)
        self.assertAlmostEqual(0.96, max(abs(lamp[1]) for lamp in non_padding_points), places=6)

        section_actives = [
            [lamp for lamp in layout[i * 250:(i + 1) * 250] if lamp[3] == 0]
            for i in range(0, 8)
        ]
        self.assertTrue(all(section for section in section_actives))

        top_left_active = section_actives[0] + section_actives[1]
        top_right_active = section_actives[2] + section_actives[3]
        bottom_right_active = section_actives[4] + section_actives[5]
        bottom_left_active = section_actives[6] + section_actives[7]

        self.assertTrue(all(lamp[0] <= 0 and lamp[1] >= 0 for lamp in top_left_active))
        self.assertTrue(all(lamp[0] >= 0 and lamp[1] >= 0 for lamp in top_right_active))
        self.assertTrue(all(lamp[0] >= 0 and lamp[1] <= 0 for lamp in bottom_right_active))
        self.assertTrue(all(lamp[0] <= 0 and lamp[1] <= 0 for lamp in bottom_left_active))

        center_top_active = [
            lamp
            for lamp in top_left_active + top_right_active
            if abs(lamp[0]) < (0.8 / 2.5)
        ]
        center_bottom_active = [
            lamp
            for lamp in bottom_left_active + bottom_right_active
            if abs(lamp[0]) < (0.8 / 2.5)
        ]

        self.assertTrue(all(lamp[1] >= 0 for lamp in center_top_active))
        self.assertTrue(all(lamp[1] <= 0 for lamp in center_bottom_active))

        center_columns = sorted(set(round(lamp[0], 6) for lamp in center_top_active))
        self.assertGreaterEqual(len(center_columns), 2)
        self.assertEqual(center_columns, sorted(set(round(lamp[0], 6) for lamp in center_bottom_active)))
        for x in center_columns:
            ys = [lamp[1] for lamp in center_top_active if round(lamp[0], 6) == x]
            self.assertGreater(max(ys), 0.05)

    def testDualRadialLayoutRequiresSpokesDivisibleByFour(self):
        result = self.runGenerator(
            'dual-radial',
            '--width', '4',
            '--height', '5',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '50',
            '--center-spacing', '1.6',
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn('divisible by 4', result.stderr)

    def testDualRadialLayoutAllowsSpokesDivisibleByFourButNotEight(self):
        result = self.runGenerator(
            'dual-radial',
            '--width', '4',
            '--height', '5',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '28',
            '--center-spacing', '1.6',
            '--max-spoke-length', '2.2',
            '--source-modes', 'framebuffer',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'dual-radial', len(layout), sections=8)
        self.assertEqual(8 * 250, len(layout))

    def testDualRadialLayoutCanClipSpokesToFitSections(self):
        result = self.runGenerator(
            'dual-radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '52',
            '--center-spacing', '1.5',
            '--max-spoke-length', '2.8',
            '--source-modes', 'framebuffer',
        )

        strings = json.loads(result.stdout)
        layout = [lamp for string in strings for lamp in string]
        self.assertLayoutStats(result, 'dual-radial', len(layout), sections=8)
        self.assertEqual(8 * 250, len(layout))
        self.assertIn('Dual radial section top-left/0: 8 fan runs, 0 center runs', result.stderr)
        self.assertIn('Dual radial section top-left/1: 5 fan runs, 3 center runs', result.stderr)
        self.assertIn('Dual radial section top-right/0: 5 fan runs, 3 center runs', result.stderr)
        self.assertIn('Dual radial section top-right/1: 8 fan runs, 0 center runs', result.stderr)
        self.assertIn('Max used LEDs per section: 246', result.stderr)

    def testDualRadialLayoutWithZeroCenterSpacingMatchesRadial(self):
        radial = self.runGenerator(
            'radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--source-modes', 'framebuffer',
        )
        dual_radial = self.runGenerator(
            'dual-radial',
            '--width', '6',
            '--height', '7',
            '--led-distance', '0.1',
            '--hub-radius', '0.2',
            '--spokes', '32',
            '--center-spacing', '0',
            '--source-modes', 'framebuffer',
        )

        self.assertLayoutStats(radial, 'radial', 8 * 250, sections=8)
        self.assertLayoutStats(dual_radial, 'dual-radial', 8 * 250, sections=8)
        self.assertEqual(json.loads(radial.stdout), json.loads(dual_radial.stdout))
