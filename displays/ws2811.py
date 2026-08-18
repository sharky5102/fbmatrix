import OpenGL.GL as gl
import numpy as np

import fbo
import geometry
import ledlayout

MAX_LEDS_PER_STRING = 2000
MAX_STRINGS = 14
BITS_PER_LED = 24


def flatten_layout(layout):
    return ledlayout.flatten_string_layout(
        ledlayout.require_xyzc_string_layout(
            layout, MAX_LEDS_PER_STRING, MAX_STRINGS))


class _quad(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        in vec2 position;
        in vec2 texcoor;
        out vec2 v_texcoor;
        void main() {
            gl_Position = projection * modelview * vec4(position, 0, 1);
            v_texcoor = texcoor;
        } """
    attributes = {'position': 2, 'texcoor': 2}
    primitive = gl.GL_QUADS

    def getVertices(self):
        return {
            'position': [(-1, -1), (+1, -1), (+1, +1), (-1, +1)],
            'texcoor': [(0, 0), (1, 0), (1, 1), (0, 1)],
        }


class _bitgenerator(_quad):
    fragment_code = """
        uniform sampler2D tex;
        uniform sampler2D lamptex;
        uniform highp float supersample;
        uniform int string_length;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;

        const int MASK_A = (1 << 2), MASK_B = (1 << 6);
        const int MASK_C = (1 << 7), MASK_D = (1 << 0);
        const int MASK_E = (1 << 4), MASK_LAT = (1 << 1);
        const int MASK_R1 = (1 << 1), MASK_B1 = (1 << 2);
        const int MASK_R2 = (1 << 0), MASK_G1 = (1 << 1);
        const int MASK_G2 = (1 << 4), MASK_B2 = (1 << 3);
        const int MASK_OE = (1 << 0), MASK_CLK = (1 << 5);

        void setBits(out ivec3 p, int D, int LAT, int A, int B2, int E,
                     int B, int C, int R2, int G1, int G2, int CLK, int OE,
                     int R1, int B1) {
            p.r = (D > 0 ? MASK_D : 0) + (LAT > 0 ? MASK_LAT : 0) +
                  (A > 0 ? MASK_A : 0) + (B2 > 0 ? MASK_B2 : 0) +
                  (E > 0 ? MASK_E : 0) + (B > 0 ? MASK_B : 0) +
                  (C > 0 ? MASK_C : 0);
            p.g = (R2 > 0 ? MASK_R2 : 0) + (G1 > 0 ? MASK_G1 : 0) +
                  (G2 > 0 ? MASK_G2 : 0) + (CLK > 0 ? MASK_CLK : 0);
            p.b = (OE > 0 ? MASK_OE : 0) + (R1 > 0 ? MASK_R1 : 0) +
                  (B1 > 0 ? MASK_B1 : 0);
        }

        int getBit(int string_number, int pixel, int bit) {
            highp vec4 lamp = texelFetch(
                lamptex, ivec2(pixel, string_number), 0);
            highp vec3 color;
            int mode = int(lamp.w + 0.5);
            if (lamp.w < -0.5) color = vec3(0.0);
            else if (mode == 1) color = vec3(1.0, 0.0, 0.0);
            else if (mode == 2) color = vec3(0.0, 1.0, 0.0);
            else if (mode == 3) color = vec3(0.0, 0.0, 1.0);
            else if (mode == 4) color = vec3(1.0);
            else {
                color = textureLod(tex, lamp.xy, supersample).rgb;
            }
            color = pow(color, vec3(2.2));
            if (bit < 8)
                return (int(color.r * 255.0) >> (7 - bit)) & 1;
            if (bit < 16)
                return (int(color.g * 255.0) >> (15 - bit)) & 1;
            return (int(color.b * 255.0) >> (23 - bit)) & 1;
        }

        void main() {
            int pixel = int(v_texcoor.y * float(string_length));
            int bit = int(v_texcoor.x * 24.0);
            int R1 = 0, G1 = 0, B1 = 0, R2 = 0, G2 = 0, B2 = 0;
            int D = 0, LAT = 0, A = 0, B = 0, C = 0, E = 0, OE = 0;
            int CLK = 0;
            STRING_BITS;
            ivec3 data;
            setBits(data, D, LAT, A, B2, E, B, C, R2, G1, G2, CLK, OE,
                    R1, B1);
            f_color = vec4(vec3(data) / 255.0, 1.0);
        } """

    def __init__(self, strings, string_length, supersample, lamptex):
        names = ['R1', 'G1', 'B1', 'R2', 'G2', 'B2', 'D',
                 'LAT', 'A', 'B', 'C', 'E', 'OE', 'CLK']
        calls = ['%s = getBit(%d, pixel, bit)' % (name, index)
                 for index, name in enumerate(names[:len(strings)])]
        self.fragment_code = self.fragment_code.replace(
            'STRING_BITS;', ';\n            '.join(calls) + ';')
        self.string_length = string_length
        self.supersample = supersample
        self.lamptex = lamptex
        self.tex = 0
        super().__init__()

    def draw(self):
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'tex'), 0)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'lamptex'), 1)
        gl.glUniform1f(gl.glGetUniformLocation(self.program, 'supersample'),
                       self.supersample)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'string_length'),
                       self.string_length)
        super().draw()


class signalgenerator(_quad):
    fragment_code = """
        uniform sampler2D bitplane;
        uniform int string_length;
        uniform ivec3 active_mask;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        void main() {
            int pixel = int(v_texcoor.y * float(string_length));
            highp float position = v_texcoor.x * 24.0;
            int bit = int(position);
            lowp float offset = position - float(bit);
            ivec3 bits = ivec3(
                texelFetch(bitplane, ivec2(bit, pixel), 0).rgb * 255.0 +
                vec3(0.5));
            ivec3 data;
            if (offset < 0.2) data = active_mask;
            else if (offset < 0.46) data = bits;
            else data = ivec3(0);
            f_color = vec4(vec3(data) / 255.0, 1.0);
        } """

    def __init__(self, layout, supersample):
        self.strings = ledlayout.require_xyzc_string_layout(
            layout, MAX_LEDS_PER_STRING, MAX_STRINGS)
        self.lamps = ledlayout.flatten_string_layout(self.strings)
        self.string_length = max((len(string) for string in self.strings),
                                 default=0)
        if self.string_length == 0:
            raise RuntimeError('WS2811 layout must contain at least one LED')

        self.mapwidth = self.string_length
        self.mapheight = MAX_STRINGS
        data = np.zeros((self.mapheight, self.mapwidth, 4), dtype=np.float32)
        data[:, :, 3] = -1
        bounds = ledlayout.active_xy_bounds(self.strings)
        for string_index, string in enumerate(self.strings):
            for led_index, lamp in enumerate(string):
                u, v = ledlayout.normalized_xy(lamp[0], lamp[1], bounds)
                data[string_index, led_index] = (
                    u, v, lamp[2], lamp[3])
        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                           gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F,
                        self.mapwidth, self.mapheight, 0,
                        gl.GL_RGBA, gl.GL_FLOAT, data)

        self.bitplane = fbo.FBO(BITS_PER_LED, self.string_length,
                                mag_filter=gl.GL_NEAREST,
                                min_filter=gl.GL_NEAREST)
        self.bitgenerator = _bitgenerator(
            self.strings, self.string_length, supersample, self.lamptex)

        masks = [(2, 2), (1, 2), (2, 4), (1, 1), (1, 16), (0, 8),
                 (0, 1), (0, 2), (0, 4), (0, 64), (0, 128), (0, 16),
                 (2, 1), (1, 32)]
        self.active_mask = [0, 0, 0]
        for channel, mask in masks[:len(self.strings)]:
            self.active_mask[channel] |= mask
        super().__init__()

    def getVertices(self):
        return {
            'position': [(-1, -1), (+1, -1), (+1, +1), (-1, +1)],
            'texcoor': [(0, 1), (1, 1), (1, 0), (0, 0)],
        }

    def render(self):
        with self.bitplane:
            self.bitgenerator.render()
        super().render()

    def draw(self):
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.bitplane.getTexture())
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'bitplane'), 0)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, 'string_length'),
                       self.string_length)
        gl.glUniform3i(gl.glGetUniformLocation(self.program, 'active_mask'),
                       *self.active_mask)
        super().draw()

    def setTexture(self, tex):
        self.bitgenerator.tex = tex
