#!/usr/bin/python

from OpenGL.GL import *
from OpenGL.GL.EXT.framebuffer_object import *

class FBO:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.tex = glGenTextures(1)

        glBindTexture(GL_TEXTURE_2D, self.tex);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_INT, None)
        glGenerateMipmap(GL_TEXTURE_2D)

        self.fbo = glGenFramebuffers(1)
        
        glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, self.fbo);
        
        glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT, GL_COLOR_ATTACHMENT0_EXT, GL_TEXTURE_2D, self.tex, 0);
        
        glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, 0);
        
    def __enter__(self):
        glPushAttrib(GL_VIEWPORT_BIT)
        glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, self.fbo);
        glViewport(0, 0, self.width, self.height);
        
    def __exit__(self, type, value, traceback):
#        glGenerateMipmap(GL_TEXTURE_2D)
        glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, 0)
        glPopAttrib()
        
    def bind(self):
        glBindTexture(GL_TEXTURE_2D, self.tex)

    def getTexture(self):
        return self.tex