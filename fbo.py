#!/usr/bin/python

from OpenGL.GL import *
from OpenGL.GL.EXT.framebuffer_object import *

class FBO:
    def __init__(self, width, height, mag_filter = GL_LINEAR, min_filter = GL_LINEAR_MIPMAP_LINEAR):
        self.width = width
        self.height = height
        self.tex = glGenTextures(1)

        glBindTexture(GL_TEXTURE_2D, self.tex);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, mag_filter)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, min_filter)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glGenerateMipmap(GL_TEXTURE_2D)

        self.fbo = glGenFramebuffers(1)
        
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo);
        
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.tex, 0);

        # Check framebuffer completeness
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            # Provide human-readable status when possible
            status_map = {
                GL_FRAMEBUFFER_UNDEFINED: 'UNDEFINED',
                GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT: 'INCOMPLETE_ATTACHMENT',
                GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT: 'MISSING_ATTACHMENT',
                GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER: 'INCOMPLETE_DRAW_BUFFER',
                GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER: 'INCOMPLETE_READ_BUFFER',
                GL_FRAMEBUFFER_UNSUPPORTED: 'UNSUPPORTED',
                GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE: 'INCOMPLETE_MULTISAMPLE',
                GL_FRAMEBUFFER_INCOMPLETE_LAYER_TARGETS: 'INCOMPLETE_LAYER_TARGETS',
            }
            name = status_map.get(status, hex(status))
            raise RuntimeError(f"Framebuffer incomplete: {name} (0x{status:X})")

        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        
    def __enter__(self):
        glPushAttrib(GL_VIEWPORT_BIT)
        # prefer GL_FRAMEBUFFER_BINDING for wider availability
        try:
            self.lastFB = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        except Exception:
            self.lastFB = glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo);
        glViewport(0, 0, self.width, self.height);
        
    def __exit__(self, type, value, traceback):
        glBindFramebuffer(GL_FRAMEBUFFER, self.lastFB)
        glPopAttrib()
        
    def bind(self):
        glBindTexture(GL_TEXTURE_2D, self.tex)

    def getTexture(self):
        return self.tex