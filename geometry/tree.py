import geometry
import ledlayout
import OpenGL.GL as gl
import numpy as np

class tree(geometry.base):
    lampsize = 1/50

    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        
        in highp vec3 position;
        in highp float id;

        out highp vec2 v_texcoor;
        out highp float v_id;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,1.0);
            v_texcoor = position.xy / 4.0 + 0.5;
            v_id = id;
        } """

    fragment_code = """
        uniform sampler2D tex;
        uniform sampler2D lamptex;
        uniform highp float supersample;
        uniform highp float time;
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp float v_id;
        
        void main()
        {
            highp vec4 lamp = texelFetch(lamptex, ivec2(int(v_id), 0), 0);
            int source_mode = int(lamp.w + 0.5);
            highp vec3 t;

            if (lamp.w < -0.5) {
                t = vec3(0.0, 0.0, 0.0);
            } else if (source_mode == 1) {
                t = vec3(1.0, 0.0, 0.0);
            } else if (source_mode == 2) {
                t = vec3(0.0, 0.0, 1.0);
            } else if (source_mode == 3) {
                t = vec3(0.0, 1.0, 0.0);
            } else if (source_mode == 4) {
                t = vec3(1.0, 1.0, 1.0);
            } else {
                t = textureLod(tex, lamp.xy, supersample).rgb;
            }
			
            if (v_id < time * 100.0) {
                f_color = vec4(t, 1.0);
            } else {
                f_color = vec4(t, 0.1);
            }

        } """
        
    attributes = { 'position' : 3, 'id' : 1 }
        
    def __init__(self, jsondata, supersample=0, emitter_shape=None,
                 string_lengths=None):
        self.lamps = ledlayout.require_xyzc_layout(jsondata)
        self.tex = 0
        self.direct_emitter_texture = emitter_shape is not None
        self.supersample = 0 if emitter_shape is not None else supersample
        self.time = 0

        # Present the lamp locations as a single-row texture. Modern OpenGL
        # supports non-power-of-two texture dimensions.
        self.mapwidth = len(self.lamps)

        data = np.zeros(self.mapwidth, (np.float32, 4))
        if emitter_shape is not None:
            width, height = emitter_shape
            flat_index = 0
            for string_index, string_length in enumerate(string_lengths):
                for led_index in range(string_length):
                    data[flat_index][0] = (led_index + 0.5) / width
                    data[flat_index][1] = (string_index + 0.5) / height
                    # A mode outside the source-mode range means that lamp.xy
                    # addresses the already-rendered emitter texture directly.
                    data[flat_index][3] = 5
                    flat_index += 1
        else:
            bounds = ledlayout.active_xy_bounds(self.lamps)
            for i in range(0, len(self.lamps)):
                lamp = self.lamps[i]
                data[i][0], data[i][1] = ledlayout.normalized_xy(
                    lamp[0], lamp[1], bounds)
                data[i][2] = lamp[2];
                data[i][3] = lamp[3];
        
        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F, self.mapwidth, 1, 0, gl.GL_RGBA, gl.GL_FLOAT, data)

        super(tree, self).__init__()

    def getVertices(self):
        verts = []
        ids = []
        
        sqverts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 0, 1), (0, 0, 1)]
        faces = [
            0, 2, 1, #face front
            0, 3, 2,
            2, 3, 4, #face top
            2, 4, 5,
            1, 2, 5, #face right
            1, 5, 6,
            0, 7, 4, #face left
            0, 4, 3,
            5, 4, 7, #face back
            5, 7, 6,
            0, 6, 7, #face bottom
            0, 1, 6
        ]

        for i in range(0, len(self.lamps)):
            vert = self.lamps[i]
            for face in faces:
                lx, ly, lz, _marker = vert
                ly = -ly
                x, y, z = sqverts[face]
                
                verts.append((x*self.lampsize+lx, y*self.lampsize+ly, z*self.lampsize+lz))
                ids.append(i)
                
        return { 'position' : verts, 'id' : ids }
                
    def setColor(self, color):
        self.color = color

    def setTime(self, time):
        self.time = time

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        if not self.direct_emitter_texture:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)

        loc = gl.glGetUniformLocation(self.program, "lamptex")
        gl.glUniform1i(loc, 1)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)

        loc = gl.glGetUniformLocation(self.program, "time")
        gl.glUniform1f(loc, self.time)
        super(tree, self).draw()

    def setTexture(self, tex):
        self.tex = tex
