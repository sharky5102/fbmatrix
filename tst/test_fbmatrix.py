import sys
import os
import numpy as np
import OpenGL.GL as gl
import OpenGL.GLUT as glut
import time
import fbo
import signal
import tempfile

import common
import displays.ws2811
import displays.hub75e
import geometry.simple
import assembly.tree
import fbmatrix
import ledlayout

import unittest
from OpenGL.GL.EXT.framebuffer_object import *

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

def ws2811_signal_bits(data, width, row=0):
    line = list(scanlines(data, width * 4))[row]
    pixels = np.frombuffer(line, dtype=[('r', 'B'), ('g', 'B'), ('b', 'B'), ('a', 'B')])
    bit_width = width // 24
    bits = []

    for bit in range(24):
        start = bit * bit_width
        end = (bit + 1) * bit_width
        channel = pixels['r'][start:end]
        bits.append(int(np.count_nonzero(channel)))

    return bits

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
        self.renderer = fbmatrix.renderer()
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: self.testPatternWhite()
            self.renderer.display()       

            data = gl.glReadPixels(0, 0, 4096, 194, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None);

        self.assertFrameData('tst/data/hub75_32x32_white.txt', data)

    def testFieldFirstOrder(self):
        self.renderer = fbmatrix.renderer(order='field-first')
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: self.testPatternWhite()
            self.renderer.display()       

            data = gl.glReadPixels(0, 0, 4096, 194, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None);

        self.assertFrameData('tst/data/hub75_fieldfirst_32x32_white.txt', data)

class TestWS2811(unittest.TestCase):
    height = 500
    width = 840
    layout = [[0.0, 0.0, 0.0, 0]]

    def readFrameData(self, color, layout=None):
        self.renderer = fbmatrix.renderer(display='ws2811', layout=layout or self.layout)
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: render_solid(color)
            self.renderer.display()

            return gl.glReadPixels(0, 0, self.width, self.height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

    def assertSignalPattern(self, color, expected_bits, layout=None):
        data = self.readFrameData(color, layout)
        high_counts = ws2811_signal_bits(data, self.width)

        for high_count, expected_bit in zip(high_counts, expected_bits):
            if expected_bit:
                self.assertGreater(high_count, 10)
            else:
                self.assertLess(high_count, 10)

    def testWhiteSignalHasAllOneBits(self):
        self.assertSignalPattern((1, 1, 1), [1] * 24)

    def testBlackSignalHasAllZeroBits(self):
        self.assertSignalPattern((0, 0, 0), [0] * 24)

    def testRedSignalEncodesRedChannelFirst(self):
        self.assertSignalPattern((1, 0, 0), [1] * 8 + [0] * 16)

    def testSourceModeRedIgnoresFramebuffer(self):
        self.assertSignalPattern((0, 0, 0), [1] * 8 + [0] * 16, [[0.0, 0.0, 0.0, 1]])

    def testSourceModeBlueIgnoresFramebuffer(self):
        self.assertSignalPattern((0, 0, 0), [0] * 16 + [1] * 8, [[0.0, 0.0, 0.0, 2]])

    def testSourceModeGreenIgnoresFramebuffer(self):
        self.assertSignalPattern((0, 0, 0), [0] * 8 + [1] * 8 + [0] * 8, [[0.0, 0.0, 0.0, 3]])

    def testEmulationAcceptsLayout(self):
        fbmatrix.renderer(display='ws2811', layout=self.layout, emulate=True)


class TestLayout(unittest.TestCase):
    def testLayoutRequiresColorMarker(self):
        with self.assertRaisesRegex(RuntimeError, r'\[x, y, z, c\]'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0]])

    def testLayoutSourceModeMustBeInteger(self):
        with self.assertRaisesRegex(RuntimeError, 'integer'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0, 1.5]])

    def testLayoutSourceModeMustBeKnown(self):
        with self.assertRaisesRegex(RuntimeError, '0, 1, 2 or 3'):
            ledlayout.require_xyzc_layout([[0.0, 0.0, 0.0, 4]])

    def testLoadLayoutClearsSourceModesByDefault(self):
        with tempfile.NamedTemporaryFile('wt', suffix='.json', delete=False) as f:
            f.write('[[0, 0, 0, 2]]')
            filename = f.name

        try:
            self.assertEqual(common.load_layout(filename), [(0.0, 0.0, 0.0, 0)])
        finally:
            os.unlink(filename)

    def testLoadLayoutCanPreserveSourceModes(self):
        with tempfile.NamedTemporaryFile('wt', suffix='.json', delete=False) as f:
            f.write('[[0, 0, 0, 2]]')
            filename = f.name

        try:
            self.assertEqual(common.load_layout(filename, preserve_source_modes=True), [(0.0, 0.0, 0.0, 2)])
        finally:
            os.unlink(filename)

