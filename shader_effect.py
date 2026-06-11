import os
import re

import OpenGL.GL as gl

import geometry


class ShaderEffect(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;

        in highp vec2 position;
        in highp vec2 texcoor;

        out highp vec2 v_texcoor;

        void main()
        {
            gl_Position = projection * modelview * vec4(position, 0.0, 1.0);
            v_texcoor = texcoor;
        } """

    attributes = {'position': 2, 'texcoor': 2}
    primitive = gl.GL_QUADS

    def __init__(self, source, width, height):
        self.fragment_code = self.wrap_source(source)
        self.width = width
        self.height = height
        self.time = 0.0
        self.hue = 0.0
        self.brightness = 1.0
        super(ShaderEffect, self).__init__()

    def getVertices(self):
        return {
            'position': [(-1, -1), (1, -1), (1, 1), (-1, 1)],
            'texcoor': [(0, 0), (1, 0), (1, 1), (0, 1)],
        }

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "iTime")
        gl.glUniform1f(loc, self.time)
        loc = gl.glGetUniformLocation(self.program, "iResolution")
        gl.glUniform2f(loc, self.width, self.height)
        loc = gl.glGetUniformLocation(self.program, "iHue")
        gl.glUniform1f(loc, self.hue)
        loc = gl.glGetUniformLocation(self.program, "iBrightness")
        gl.glUniform1f(loc, self.brightness)

        super(ShaderEffect, self).draw()

    def set_params(self, now, hue, brightness):
        self.time = now
        self.hue = hue
        self.brightness = brightness

    @staticmethod
    def wrap_source(source):
        source = strip_version(source)
        return """
            precision highp float;

            out highp vec4 f_color;
            in highp vec2 v_texcoor;

            uniform highp float iTime;
            uniform highp vec2 iResolution;
            uniform highp float iHue;
            uniform highp float iBrightness;

            """ + source + """

            void main()
            {
                highp vec4 color;
                mainImage(color, v_texcoor * iResolution);
                f_color = vec4(color.rgb * iBrightness, color.a);
            } """


def strip_version(source):
    return re.sub(r'^\s*#version\s+.+$', '', source, count=1, flags=re.MULTILINE)


def effect_name(effect_id):
    return effect_id.replace('_', ' ').replace('-', ' ').title()


def discover_effects(effects_dir):
    effects = []
    if not os.path.isdir(effects_dir):
        return effects

    for filename in sorted(os.listdir(effects_dir)):
        if filename.endswith('.frag'):
            effect_id = os.path.splitext(filename)[0]
            effects.append({
                'id': effect_id,
                'name': effect_name(effect_id),
            })

    return effects


def load_effect_source(effects_dir, effect_id):
    if not re.match(r'^[A-Za-z0-9_-]+$', effect_id):
        raise ValueError('Invalid effect id')

    filename = os.path.join(effects_dir, effect_id + '.frag')
    with open(filename, 'rt', encoding='utf-8') as f:
        return f.read()
