import geometry
import geometry.simple
import fit_to_leds
import OpenGL.GL as gl

class yuv420(geometry.simple.texquad):
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
        super(yuv420, self).__init__()

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


class yuv422(geometry.simple.texquad):
    """Packed UYVY 4:2:2 upload and GPU conversion used by NDI."""
    fragment_code = """
        uniform sampler2D tex;
        uniform highp float width;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
    """ + fit_to_leds.GLSL + """
        void main()
        {
            highp float insideSource;
            highp vec2 sourceUV = fitSourceUV(v_texcoor, insideSource);
            if (insideSource < 0.5) {
                f_color = vec4(0.0, 0.0, 0.0, 1.0);
                return;
            }
            highp vec4 pair = textureLod(tex, sourceUV, 0.0);
            highp float pixel = floor(sourceUV.x * width);
            highp float y = mod(pixel, 2.0) < 1.0 ? pair.g : pair.a;
            highp float u = pair.r - 0.5;
            highp float v = pair.b - 0.5;
            f_color = vec4(y + 1.402 * v,
                           y - 0.344 * u - 0.714 * v,
                           y + 1.772 * u, 1.0);
        } """

    def __init__(self):
        self.tex = gl.glGenTextures(1)
        self.width = 1
        self.height = 1
        self.target_aspect = 1.0
        self.fit_mode = 0
        super(yuv422, self).__init__()

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, 'width')
        gl.glUniform1f(loc, self.width)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'fitSourceAspect'),
                       float(self.width) / self.height)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'fitTargetAspect'),
                       self.target_aspect)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'fitMode'),
                       self.fit_mode)
        super(yuv422, self).draw()

    def setUYVY(self, data, width, height, stride):
        if stride != width * 2:
            data = b''.join(bytes(data[y * stride:y * stride + width * 2])
                            for y in range(height))
        self.width = width
        self.height = height
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width // 2, height, 0,
                        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)

    def set_fit(self, mode, target_aspect):
        self.fit_mode = fit_to_leds.mode_code(mode)
        self.target_aspect = float(target_aspect)
