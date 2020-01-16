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

def signal_handler(sig, frame):
        sys.exit(0)

class renderer(object):
    def __init__(self, emulate=False, preview=False, raw=False, display='hub75e', rows=32, columns=32, supersample=3):
        self.emulate = emulate
        self.preview = preview
        self.raw = raw
        self.displaytype = display
        self.rows = rows
        self.columns = columns
        self.supersample = supersample
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
            
        if self.emulate:
            gl.glClearColor(0, 0, 0, 0)    
            gl.glClear(gl.GL_COLOR_BUFFER_BIT| gl.GL_DEPTH_BUFFER_BIT)
            
            gl.glViewport(0, 0, int(self.screenWidth/2), self.screenHeight)
            self.tree.render(0)
            
            gl.glViewport(int(self.screenWidth/2), 0, int(self.screenWidth/2), self.screenHeight)
            self.texquad.render()
            
        else:
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            
            if self.preview:   
                self.texquad.render()
            else:
                self.signalgenerator.render()
                    
        glut.glutSwapBuffers()
        glut.glutPostRedisplay()
    
    def reshape(self,width,height):
        self.screenWidth = width
        self.screenHeight = height
        
        gl.glViewport(0, 0, width, height)

    def keyboard(self, key, x, y ):
        if key == b'\033':
            sys.exit( )

    def init(self):
        # Initialize display
        glut.glutInit()
        glut.glutInitDisplayMode(glut.GLUT_DOUBLE | glut.GLUT_RGBA)
        glut.glutCreateWindow(b'fbmatrix')
        if self.preview or self.raw:
            glut.glutReshapeWindow(512, 512)
        elif self.emulate:
            glut.glutReshapeWindow(1024, 512)

        glut.glutReshapeFunc(lambda w,h: self.reshape(w,h))
        glut.glutDisplayFunc(lambda: self.display())
        glut.glutKeyboardFunc(lambda k,x,y: self.keyboard(k,x,y))

        # Primary offscreen framebuffer
        self.mainfbo = fbo.FBO(512, 512)

        # Initialize display shader
        layoutfile = 'layout.json'

        if self.displaytype == 'ws2811':
            self.signalgenerator = displays.ws2811.signalgenerator(layoutfile, supersample=self.supersample)
            self.signalgenerator.setTexture(self.mainfbo.getTexture())
        elif self.displaytype == 'hub75e':
            self.signalgenerator = displays.hub75e.signalgenerator(columns=self.columns, rows=self.rows, supersample=self.supersample)
            self.signalgenerator.setTexture(self.mainfbo.getTexture())

        # Emulation shader
        if self.emulate or self.preview:
            self.texquad = geometry.simple.texquad()
            self.texquad.setTexture(self.mainfbo.getTexture())

        # Tree emulator
        if self.emulate:
            self.tree = assembly.tree.tree(layoutfile)
            self.tree.setTexture(self.mainfbo.getTexture())

        # Render
        glut.glutSetCursor(glut.GLUT_CURSOR_NONE);
        if not self.raw and not self.preview and not self.emulate:
            glut.glutFullScreen()

    def run(self, render):
        self.render = render
        signal.signal(signal.SIGINT, signal_handler)

        glut.glutMainLoop()

