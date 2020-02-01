import geometry
import geometry.simple
import OpenGL.GL as gl

class bytearray(geometry.simple.texquad):
    fragment_code = """
        uniform sampler2D tex;
        uniform lowp float supersample;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            f_color = textureLod(tex, v_texcoor, supersample);
        } """
        
    def __init__(self, supersample=0):
        self.tex = gl.glGenTextures(1)
        self.supersample = supersample
        super(bytearray, self).__init__()

    def getVertices(self):
        verts = [(-1, 1), (+1, 1), (+1, -1), (-1, -1)]
        coors = [(1, 0), (0, 0), (0, 1), (1, 1)]
        
        return { 'position' : verts, 'texcoor' : coors }

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)
        
        geometry.base.draw(self)
        
    def setRGB(self, bytes, w, h):
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if self.supersample else gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, bytes)
        if self.supersample:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
