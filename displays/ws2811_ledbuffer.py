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
        uniform sampler2D lamptex0;
        uniform sampler2D lamptex1;
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

        LED_EFFECT_SOURCE

        void main() {
            ivec2 emitter = ivec2(v_texcoor * vec2(led_dimensions));
            emitter = clamp(emitter, ivec2(0), led_dimensions - ivec2(1));
            highp vec4 lamp0 = texelFetch(lamptex0, emitter, 0);
            highp vec4 lamp1 = texelFetch(lamptex1, emitter, 0);
            if (lamp0.w < 0.0) {
                f_color = vec4(0.0, 0.0, 0.0, 1.0);
                return;
            }
            highp vec4 ledColor;
            mainLed(ledColor, lamp0.xyz, float(emitter.x), float(emitter.y),
                    lamp0.w, lamp1.x, lamp1.y);
            if (lamp0.w <= 0.0)
                ledColor = vec4(0.0, 0.0, 0.0, 1.0);
            f_color = vec4(
                clamp(ledColor.rgb * iBrightness, 0.0, 1.0),
                ledColor.a);
        } """

    attributes = {'position': 2, 'texcoor': 2}
    primitive = gl.GL_QUADS

    def __init__(self, layout, supersample, effect_source=None):
        self.strings = ledlayout.require_led_string_layout(layout)
        self.width = max(len(string) for string in self.strings)
        self.height = len(self.strings)
        self.supersample = supersample
        self.tex = 0
        self.time = 0.0
        self.hue = 0.0
        self.brightness = 1.0
        self.set_effect_source(effect_source or led_effect.DEFAULT_LED_EFFECT,
                               compile_program=False)

        data0 = np.zeros((self.height, self.width, 4), dtype=np.float32)
        data1 = np.zeros((self.height, self.width, 4), dtype=np.float32)
        # Negative enabled marks rectangular texture padding, which is not a
        # physical emitter. Zero enabled remains a real but inactive LED.
        data0[:, :, 3] = -1
        self.source_bounds = ledlayout.active_xy_bounds(self.strings)
        for string_index, string in enumerate(self.strings):
            for led_index, lamp in enumerate(string):
                data0[string_index, led_index] = lamp[:4]
                data1[string_index, led_index, :2] = lamp[4:6]

        self.lamptex = gl.glGenTextures(2)
        for texture, data in zip(self.lamptex, (data0, data1)):
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                               gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                               gl.GL_NEAREST)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F,
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
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex[0])
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'lamptex0'), 1)
        gl.glActiveTexture(gl.GL_TEXTURE2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex[1])
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'lamptex1'), 2)
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
