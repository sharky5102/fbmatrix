import sys
import numpy as np
import OpenGL.GL as gl
import OpenGL.GLUT as glut
import time
import fbo
import signal

import displays.ws2811
import displays.hub75e
import geometry.simple
import assembly.tree
import fbmatrix

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

class TestHub75(unittest.TestCase):
    height = 194
    width = 4096
    maxDiff = None
    
    # Set to True to overwrite the test data
    write = False
    
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
        if self.write:
            self.writeFrameData(filename, data)
            
        with open(filename, 'rt') as f:
            for expected, actual in zip(f.readlines(), hub75ToText(data, self.width)):
                self.assertEquals(expected.rstrip(), actual)
        
    def testSimple16Scan(self):
        self.renderer = fbmatrix.renderer()
        screen = fbo.FBO(self.width, self.height)
        with screen:
            self.renderer.render = lambda: self.testPatternWhite()
            self.renderer.display()       

            data = gl.glReadPixels(0, 0, 4096, 194, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None);

        self.assertFrameData('tst/data/hub75_32x32_white.txt', data)
