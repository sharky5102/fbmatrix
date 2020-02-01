import geometry
import geometry.simple
import OpenGL.GL as gl

class bytearray(geometry.simple.texquad):
    fragment_code = """
        uniform sampler2D texy;
        uniform sampler2D texu;
        uniform sampler2D texv;
        uniform lowp float supersample;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        
        void main()
        {
            highp float y = textureLod(texy, v_texcoor, supersample).r;
            highp float u = textureLod(texu, v_texcoor, supersample).r - 0.5;
            highp float v = textureLod(texv, v_texcoor, supersample).r - 0.5;
            
            highp float r = y +             (1.402 * v);  
            highp float g = y - (0.344 * u) - (0.714 * v);  
            highp float b = y + (1.772 * u);  
            f_color = vec4(r,g,b,1.0);  
        } """
        
    def __init__(self, supersample=0):
        self.lum = gl.glGenTextures(1)
        self.crB = gl.glGenTextures(1)
        self.crR = gl.glGenTextures(1)
        self.supersample = supersample
        super(bytearray, self).__init__()

    def getVertices(self):
        verts = [(-1, 1), (+1, 1), (+1, -1), (-1, -1)]
        coors = [(1, 0), (0, 0), (0, 1), (1, 1)]
        
        return { 'position' : verts, 'texcoor' : coors }

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "texy")
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lum)
        gl.glUniform1i(loc, 0)

        loc = gl.glGetUniformLocation(self.program, "texu")
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.crB)
        gl.glUniform1i(loc, 1)

        loc = gl.glGetUniformLocation(self.program, "texv")
        gl.glActiveTexture(gl.GL_TEXTURE2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.crR)
        gl.glUniform1i(loc, 2)

        gl.glActiveTexture(gl.GL_TEXTURE0)

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)
        
        geometry.base.draw(self)
        
    def setYUV420(self, data, w, h):
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lum)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if self.supersample else gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, bytes(data[0]))
        if self.supersample:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

        hw = int(w/2)
        hh = int(h/2)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self.crB)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if self.supersample else gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, hw, hh, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, bytes(data[1]))
        if self.supersample:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

        gl.glBindTexture(gl.GL_TEXTURE_2D, self.crR)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if self.supersample else gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, hw, hh, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, bytes(data[2]))
        if self.supersample:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        

