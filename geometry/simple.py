import geometry
import math
import OpenGL.GL as gl
import numpy as np
import ctypes

from PIL import Image

class circle(geometry.base):
    srcblend = gl.GL_SRC_ALPHA
    dstblend = gl.GL_ONE
    
    segs = 16
    def __init__(self):
        self.color = (1,1,1,1)
        super(circle, self).__init__()
    
    def getVertices(self):
        colors = []
        verts = []

        for i in range(0,self.segs):
            colors.append(self.color)
            colors.append(self.color)
            colors.append(self.color)
            verts.append((0,0))
            verts.append((math.sin(math.pi*2*i/self.segs), math.cos(math.pi*2*i/self.segs)))
            verts.append((math.sin(math.pi*2*(i+1)/self.segs), math.cos(math.pi*2*(i+1)/self.segs)))

        return { 'position' : verts, 'color' : colors }

    def setColor(self, color):
        self.color = color

class square(geometry.base):
    def __init__(self):
        self.color = (1,1,1,1)
        super(square, self).__init__()
    
    def getVertices(self):
        verts = [ (0,0), (0,1), (1,1),   (0,0), (1,0), (1,1) ]
        
        return { 'position' : verts, 'color' : [self.color] * 6 }

    def setColor(self, color):
        self.color = color


class texquad(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        uniform vec4 objcolor;
        
        in highp vec2 position;
        in highp vec2 texcoor;

        out highp vec2 v_texcoor;
        out highp vec4 v_color;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,0.0,1.0);
            v_texcoor = texcoor;
            v_color = objcolor;
        } """

    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp vec4 v_color;
        
        void main()
        {
            f_color = textureLod(tex, v_texcoor, 0.0) * v_color;
        } """
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS
        
    def getVertices(self):
        verts = [(-1, -1), (+1, -1), (+1, +1), (-1, +1)]
        coors = [(0, 0), (1, 0), (1, 1), (0, 1)]
        
        return { 'position' : verts, 'texcoor' : coors }
        
    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        
        super(texquad, self).draw()

    def setTexture(self, tex):
        self.tex = tex



class alphatexquad(texquad):
    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp vec4 v_color;
        
        void main()
        {
            f_color = vec4(v_color.rgb, v_color.a * textureLod(tex, v_texcoor, 0.0).r);
        } """
        


class ballquad(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        
        in vec2 position;
        in vec2 texcoor;

        out vec2 v_texcoor;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,0,1);
            v_texcoor = texcoor;
        } """

    fragment_code = """
        uniform sampler2D tex;
        out vec4 f_color;
        in vec2 v_texcoor;
        
        void main()
        {
            float pixsize_x = 1.0/50;
            float pixsize_y = 1.0/10;
            
            vec2 coor;
            
            coor.x = (floor(v_texcoor.x/pixsize_x)+0.5)*pixsize_x;
            coor.y = (floor(v_texcoor.y/pixsize_y)+0.5)*pixsize_y;
            
            vec2 d = v_texcoor - coor;
            d.x *= 5;
            
            float p = pow(1-length(d)*6, 3);
            float p2 = length(d) > 1.0 * pixsize_x ? 0.0 : 1.0;
            
            vec4 t = textureLod(tex, coor, 3);
            
            f_color = (t * p + t * p2);
        } """
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS
        
    def getVertices(self):
        verts = [(-1, -1), (+1, -1), (+1, +1), (-1, +1)]
        coors = [(0, 0), (1, 0), (1, 1), (0, 1)]
        
        return { 'position' : verts, 'texcoor' : coors }
        
    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
#        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        
        super(texquad, self).draw()

    def setTexture(self, tex):
        self.tex = tex

class imgquad(texquad):
    fragment_code = """
        uniform sampler2D tex;
        out vec4 f_color;
        in vec2 v_texcoor;
        
        void main()
        {
            vec4 t = texture(tex, v_texcoor);
            
            f_color = t;
        } """

    def __init__(self, filename):
        im = Image.open(filename)

        imdata = np.fromstring(im.tostring(), np.uint8)
        self.tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, im.size[0], im.size[1], 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, imdata)

        super(imgquad, self).__init__()

class spotquad(texquad):
    tex = 0
    fragment_code = """
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            vec4 t = vec4(f_color.rgb, length(v_texcoor - vec2(0.5, 0.5)));
            
            t = vec4(1.0);
            f_color = t;
        } """

class copper(texquad):
    tex = 0
    dstblend = gl.GL_ONE
    fragment_code = """
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        uniform highp vec2 direction;
        uniform highp vec4 color;

        void main()
        {
            highp vec2 b = direction;
            highp vec2 a = v_texcoor;

            highp float c = (sin(dot(a,b) / dot(b,b)) + 1.0) / 2.0; 
            f_color = vec4(color.rgb, c);
        } """

    def getVertices(self):
        verts = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        coors = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        
        return { 'position' : verts, 'texcoor' : coors }

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "direction")
        gl.glUniform2f(loc, self.direction[0], self.direction[1])
        loc = gl.glGetUniformLocation(self.program, "color")
        gl.glUniform4f(loc, self.color[0], self.color[1], self.color[2], 1)
        
        super(copper, self).draw()
        
    def setDirection(self, v):
        self.direction = v

    def setColor(self, color):
        self.color = color

class lodtexquad(texquad):
    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp vec4 v_color;
        
        void main()
        {
            f_color = textureLod(tex, v_texcoor, 0.0) * v_color;
        } """

class blurtexquad(texquad):
    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            highp vec4 acc;
            lowp float n = 0.0;
            for(int i = - 8; i < 9; i++) {
                lowp float weight = 1.0; //8.0 - abs(float(i));
                acc += textureLod(tex, v_texcoor + vec2(0.01*float(i)/8.0, 0.0), 0.0) * weight;
                n += weight;
            }
            
            f_color = 1.4 * acc / n;
        } """

class vblurtexquad(texquad):
    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            highp vec4 acc;
            lowp float n = 0.0;
            for(int i = - 8; i < 9; i++) {
                lowp float weight = 1.0; //8.0 - abs(float(i));
                acc += textureLod(tex, v_texcoor + vec2(0.0, 0.01*float(i)/8.0), 0.0) * weight;
                n += weight;
            }
            
            f_color = 1.4 * acc / n;
        } """
