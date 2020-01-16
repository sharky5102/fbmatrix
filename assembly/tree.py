import assembly
import random
import geometry.tree
import geometry.simple
import OpenGL.GL as gl
import numpy as np
import math
import pyrr
from pyrr import Matrix44

class tree():
    def __init__(self, filename):
        f = open(filename, 'rt')
        data = f.read()
        self.tree = geometry.tree.tree(data)
        self.lt = geometry.simple.texquad()
        
    def setProjection(self, M):
        self.projection = M

    def render(self, t):
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        M = np.eye(4, dtype=np.float32)
        M = M * Matrix44.from_scale( (.5, .5, .5))
        M = M * Matrix44.from_translation( (0, 0,- 2))
        M = M * Matrix44.from_x_rotation(0)
        M = M * Matrix44.from_scale( (.4, .4, .4))
        M = M * Matrix44.from_translation( (0, 0, -50))

        projection = pyrr.matrix44.create_perspective_projection(3, 1, 0.001, 10000)
        self.tree.setProjection(projection)
        self.tree.setModelView(M)
        self.tree.render()
        gl.glDisable(gl.GL_DEPTH_TEST)

    def setTexture(self, tex):
        self.tree.setTexture(tex)
        self.lt.setTexture(tex)