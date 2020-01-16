import assembly
import random
import geometry.tree
import geometry.simple
import OpenGL.GL as gl
import numpy as np
import transforms
import math
import pyrr

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
        #transforms.rotate(M, t*20, 0, 1, 0)
        #transforms.rotate(M, t*20, 1, 0, 0)
        transforms.scale(M, .5, .5, .5)
        transforms.translate(M, 0, 0, -2)

        transforms.rotate(M, 00, 1, 0, 0)
        transforms.scale(M, .4, .4, .4)
        transforms.translate(M, 0, 0, -10)

        projection = pyrr.matrix44.create_perspective_projection(3, 1, 0.001, 10000)
        self.tree.setProjection(projection)
        self.tree.setModelView(M)
        self.tree.render()
#        self.lt.render()
        gl.glDisable(gl.GL_DEPTH_TEST)

    def setTexture(self, tex):
        self.tree.setTexture(tex)
        self.lt.setTexture(tex)