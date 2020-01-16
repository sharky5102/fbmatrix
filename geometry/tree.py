import geometry
import math
import OpenGL.GL as gl
import json
import numpy as np

from PIL import Image

class tree(geometry.base):
    lampsize = 1/50

    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        
        in highp vec3 position;
        in highp float id;

        out highp vec2 v_texcoor;
        out highp float v_id;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,1.0);
            v_texcoor = position.xy / 4.0 + 0.5;
            v_id = id;
        } """

    fragment_code = """
        uniform sampler2D tex;
        uniform sampler2D lamptex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp float v_id;
        
        void main()
        {
            highp vec2 lamppos = texelFetch(lamptex, ivec2(int(v_id), 0), 0).xy * vec2(0.5,0.5) + vec2(.5,.5);
            highp vec3 t = textureLod(tex, lamppos, 0.0).rgb;
			
            f_color = vec4(t, 1.0);
        } """
        
    attributes = { 'position' : 3, 'id' : 1 }
        
    def __init__(self, jsondata):
        self.lamps = json.loads(jsondata)
        self.tex = 0
        
        for lamp in self.lamps:
            lamp[1] = -lamp[1]

        # Present the lamp locations as a 1d texture
        self.mapwidth = pow(2, math.ceil(math.log(len(self.lamps))/math.log(2)))

        data = np.zeros(self.mapwidth, (np.float32, 3))
        
        for i in range(0, len(self.lamps)):
            lamp = self.lamps[i]
            data[i][0] = lamp[0];
            data[i][1] = lamp[1];
            data[i][2] = lamp[2];
        
        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB16F, self.mapwidth, 1, 0, gl.GL_RGB, gl.GL_FLOAT, data)

        super(tree, self).__init__()

    def getVertices(self):
        verts = []
        ids = []
        
        sqverts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 0, 1), (0, 0, 1)]
        faces = [
            0, 2, 1, #face front
            0, 3, 2,
            2, 3, 4, #face top
            2, 4, 5,
            1, 2, 5, #face right
            1, 5, 6,
            0, 7, 4, #face left
            0, 4, 3,
            5, 4, 7, #face back
            5, 7, 6,
            0, 6, 7, #face bottom
            0, 1, 6
        ]

        for i in range(0, len(self.lamps)):
            vert = self.lamps[i]
            for face in faces:
                lx, ly, lz = vert
                x, y, z = sqverts[face]
                
                verts.append((x*self.lampsize+lx, y*self.lampsize+ly, z*self.lampsize+lz))
                ids.append(i)
                
        return { 'position' : verts, 'id' : ids }
                
    def setColor(self, color):
        self.color = color

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

        loc = gl.glGetUniformLocation(self.program, "lamptex")
        gl.glUniform1i(loc, 1)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        
        super(tree, self).draw()

    def setTexture(self, tex):
        self.tex = tex
