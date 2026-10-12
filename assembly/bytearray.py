import geometry
import geometry.simple
import OpenGL.GL as gl
import fit_to_leds

class bytearray(geometry.simple.texquad):
    fragment_code = """
        uniform sampler2D tex;
        uniform lowp float supersample;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
    """ + fit_to_leds.GLSL + """
        void main()
        {
            highp float insideSource;
            highp vec2 sourceUV = fitSourceUV(v_texcoor, insideSource);
            f_color = insideSource > 0.5
                ? textureLod(tex, sourceUV, supersample)
                : vec4(0.0, 0.0, 0.0, 1.0);
        } """
        
    def __init__(self, supersample=0):
        self.tex = gl.glGenTextures(1)
        self.supersample = supersample
        self.source_aspect = 1.0
        self.target_aspect = 1.0
        self.fit_mode = 0
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

        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'fitSourceAspect'),
                       self.source_aspect)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'fitTargetAspect'),
                       self.target_aspect)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'fitMode'),
                       self.fit_mode)
        
        geometry.base.draw(self)
        
    def setRGB(self, bytes, w, h):
        self.source_aspect = float(w) / h
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if self.supersample else gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB, w, h, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, bytes)
        if self.supersample:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

    def set_fit(self, mode, target_aspect):
        self.fit_mode = fit_to_leds.mode_code(mode)
        self.target_aspect = float(target_aspect)

