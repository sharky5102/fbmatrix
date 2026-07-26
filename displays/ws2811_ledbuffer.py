import geometry
import ledlayout
import led_effect
import math
import OpenGL.GL as gl
import numpy as np


class ledbuffer(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;

        in highp vec2 position;
        in highp vec2 texcoor;

        out highp vec2 v_texcoor;

        void main()
        {
            gl_Position = projection * modelview * vec4(position,0,1);
            v_texcoor = texcoor;
        } """

    fragment_template = """
        precision highp float;

        uniform sampler2D tex;
        uniform sampler2D lamptex;
        uniform int led_count;
        uniform highp float supersample;
        uniform highp float iTime;
        uniform highp float iHue;
        uniform highp float iBrightness;

        out highp vec4 f_color;
        in highp vec2 v_texcoor;

        highp vec4 sampleSource(vec3 ledPosition) {
            highp vec2 sourcePos = ledPosition.xy * vec2(0.5, -0.5) + vec2(0.5, 0.5);
            return textureLod(tex, sourcePos, supersample);
        }

        highp vec4 defaultSource(vec3 ledPosition, int sourceMode) {
            if (sourceMode < 0) {
                return vec4(0.0, 0.0, 0.0, 1.0);
            } else if (sourceMode == 1) {
                return vec4(1.0, 0.0, 0.0, 1.0);
            } else if (sourceMode == 2) {
                return vec4(0.0, 1.0, 0.0, 1.0);
            } else if (sourceMode == 3) {
                return vec4(0.0, 0.0, 1.0, 1.0);
            } else if (sourceMode == 4) {
                return vec4(1.0, 1.0, 1.0, 1.0);
            }

            return sampleSource(ledPosition);
        }

        LED_EFFECT_SOURCE

        void main()
        {
            int pixel = int(v_texcoor.x * float(led_count));
            pixel = clamp(pixel, 0, led_count - 1);

            highp vec4 lamp = texelFetch(lamptex, ivec2(pixel, 0), 0);
            highp vec3 ledPosition = vec3(lamp.x, -lamp.y, lamp.z);
            int sourceMode = lamp.w < -0.5 ? -1 : int(lamp.w + 0.5);
            highp vec4 ledColor;
            mainLed(ledColor, ledPosition, float(pixel), sourceMode);

            f_color = vec4(clamp(ledColor.rgb, 0.0, 1.0), ledColor.a);
        } """

    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS

    def __init__(self, layout, supersample, effect_source=None):
        self.lamps = ledlayout.require_xyzc_layout(layout)
        self.tex = 0
        self.supersample = supersample
        self.time = 0.0
        self.hue = 0.0
        self.brightness = 1.0
        self.set_effect_source(effect_source or led_effect.DEFAULT_LED_EFFECT, compile_program=False)

        self.mapwidth = pow(2, math.ceil(math.log(len(self.lamps)) / math.log(2)))

        data = np.zeros(self.mapwidth, (np.float32, 4))

        for i in range(0, len(self.lamps)):
            lamp = self.lamps[i]
            data[i][0] = lamp[0]
            data[i][1] = -lamp[1]
            data[i][2] = lamp[2]
            data[i][3] = lamp[3]

        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F, self.mapwidth, 1, 0, gl.GL_RGBA, gl.GL_FLOAT, data)

        super(ledbuffer, self).__init__()

    def getVertices(self):
        verts = [(-1, -1), (+1, -1), (+1, +1), (-1, +1)]
        coors = [(0, 0), (1, 0), (1, 1), (0, 1)]

        return { 'position' : verts, 'texcoor' : coors }

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

        loc = gl.glGetUniformLocation(self.program, "led_count")
        gl.glUniform1i(loc, len(self.lamps))

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)

        loc = gl.glGetUniformLocation(self.program, "iTime")
        gl.glUniform1f(loc, self.time)

        loc = gl.glGetUniformLocation(self.program, "iHue")
        gl.glUniform1f(loc, self.hue)

        loc = gl.glGetUniformLocation(self.program, "iBrightness")
        gl.glUniform1f(loc, self.brightness)

        super(ledbuffer, self).draw()

    def setTexture(self, tex):
        self.tex = tex

    def set_params(self, now, hue, brightness):
        self.time = now
        self.hue = hue
        self.brightness = brightness

    def set_effect_source(self, source, compile_program=True):
        source = led_effect.strip_version(source)
        self.fragment_code = self.fragment_template.replace('LED_EFFECT_SOURCE', source)
        if compile_program:
            self.program = self.loadShaderProgram()
