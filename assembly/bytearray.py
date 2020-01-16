import geometry
import geometry.simple
import OpenGL.GL as gl

class bytearray(geometry.simple.texquad):
    fragment_code = """
        uniform sampler2D tex;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            f_color = texture(tex, v_texcoor);
        } """
        
    def __init__(self):
        self.tex = gl.glGenTextures(1)
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
        
        geometry.base.draw(self)
        
    def setRGB(self, bytes, w, h):
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, bytes)
