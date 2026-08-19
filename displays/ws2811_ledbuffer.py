import OpenGL.GL as gl
import numpy as np

import geometry
import led_effect
import ledlayout


class ledbuffer(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        in highp vec2 position;
        in highp vec2 texcoor;
        out highp vec2 v_texcoor;
        void main() {
            gl_Position = projection * modelview * vec4(position, 0, 1);
            v_texcoor = texcoor;
        } """

    fragment_template = """
        precision highp float;
        uniform sampler2D tex;
        uniform sampler2D lamptex;
        uniform ivec2 led_dimensions;
        uniform highp vec4 source_bounds;
        uniform highp float supersample;
        uniform highp float iTime;
        uniform highp float iHue;
        uniform highp float iBrightness;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;

        highp vec4 sampleSource(vec3 ledPosition) {
            highp vec2 extent = source_bounds.yw - source_bounds.xz;
            highp vec2 sourcePos = vec2(
                extent.x == 0.0 ? 0.5
                    : (ledPosition.x - source_bounds.x) / extent.x,
                extent.y == 0.0 ? 0.5
                    : (source_bounds.w - ledPosition.y) / extent.y);
            return textureLod(tex, sourcePos, supersample);
        }

        highp vec4 defaultSource(vec3 ledPosition, int sourceMode) {
            if (sourceMode < 0) return vec4(0.0, 0.0, 0.0, 1.0);
            if (sourceMode == 1) return vec4(1.0, 0.0, 0.0, 1.0);
            if (sourceMode == 2) return vec4(0.0, 1.0, 0.0, 1.0);
            if (sourceMode == 3) return vec4(0.0, 0.0, 1.0, 1.0);
            if (sourceMode == 4) return vec4(1.0, 1.0, 1.0, 1.0);
            return sampleSource(ledPosition);
        }

        LED_EFFECT_SOURCE

        void main() {
            ivec2 emitter = ivec2(v_texcoor * vec2(led_dimensions));
            emitter = clamp(emitter, ivec2(0), led_dimensions - ivec2(1));
            highp vec4 lamp = texelFetch(lamptex, emitter, 0);
            if (lamp.w < -1.5) {
                f_color = vec4(0.0, 0.0, 0.0, 1.0);
                return;
            }
            int sourceMode = lamp.w < -0.5 ? -1 : int(lamp.w + 0.5);
            highp vec4 ledColor;
            mainLed(ledColor, lamp.xyz, float(emitter.x), emitter.y,
                    sourceMode);
            f_color = vec4(
                clamp(ledColor.rgb * iBrightness, 0.0, 1.0),
                ledColor.a);
        } """

    attributes = {'position': 2, 'texcoor': 2}
    primitive = gl.GL_QUADS

    def __init__(self, layout, supersample, effect_source=None):
        self.strings = ledlayout.require_xyzc_string_layout(layout)
        self.width = max(len(string) for string in self.strings)
        self.height = len(self.strings)
        self.supersample = supersample
        self.tex = 0
        self.time = 0.0
        self.hue = 0.0
        self.brightness = 1.0
        self.set_effect_source(effect_source or led_effect.DEFAULT_LED_EFFECT,
                               compile_program=False)

        data = np.zeros((self.height, self.width, 4), dtype=np.float32)
        # -2 marks rectangular padding; -1 remains a real, inactive emitter.
        data[:, :, 3] = -2
        self.source_bounds = ledlayout.active_xy_bounds(self.strings)
        for string_index, string in enumerate(self.strings):
            for led_index, lamp in enumerate(string):
                data[string_index, led_index] = lamp

        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                           gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F,
                        self.width, self.height, 0, gl.GL_RGBA, gl.GL_FLOAT,
                        data)
        super().__init__()

    def getVertices(self):
        return {
            'position': [(-1, -1), (+1, -1), (+1, +1), (-1, +1)],
            'texcoor': [(0, 0), (1, 0), (1, 1), (0, 1)],
        }

    def draw(self):
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'tex'), 0)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'lamptex'), 1)
        gl.glUniform2i(gl.glGetUniformLocation(self.program, 'led_dimensions'),
                       self.width, self.height)
        min_x, max_x, min_y, max_y = self.source_bounds
        gl.glUniform4f(gl.glGetUniformLocation(self.program, 'source_bounds'),
                       min_x, max_x, min_y, max_y)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'supersample'),
                       self.supersample)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'iTime'), self.time)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'iHue'), self.hue)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'iBrightness'),
                       self.brightness)
        super().draw()

    def setTexture(self, tex):
        self.tex = tex

    def set_params(self, now, hue, brightness):
        self.time = now
        self.hue = hue
        self.brightness = brightness

    def set_effect_source(self, source, compile_program=True):
        source = led_effect.strip_version(source)
        self.fragment_code = self.fragment_template.replace(
            'LED_EFFECT_SOURCE', source)
        if compile_program:
            self.program = self.loadShaderProgram()
