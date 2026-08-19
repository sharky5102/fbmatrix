import geometry
import ledlayout
import OpenGL.GL as gl

class tree(geometry.base):
    lampsize = 1/50

    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        
        in highp vec3 position;
        in highp float id;
        in highp vec2 emitter;

        out highp float v_id;
        out highp vec2 v_emitter;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,1.0);
            v_id = id;
            v_emitter = emitter;
        } """

    fragment_code = """
        uniform sampler2D tex;
        uniform highp vec2 emitter_dimensions;
        uniform highp float time;
        out highp vec4 f_color;
        in highp float v_id;
        in highp vec2 v_emitter;
        
        void main()
        {
            highp vec2 emitter_pos =
                (v_emitter + vec2(0.5)) / emitter_dimensions;
            highp vec3 t = textureLod(tex, emitter_pos, 0.0).rgb;
			
            if (v_id < time * 100.0) {
                f_color = vec4(t, 1.0);
            } else {
                f_color = vec4(t, 0.1);
            }

        } """
        
    attributes = { 'position' : 3, 'id' : 1, 'emitter' : 2 }
        
    def __init__(self, jsondata, emitter_shape, string_lengths):
        self.lamps = ledlayout.require_xyzc_layout(jsondata)
        self.tex = 0
        self.time = 0

        self.mapwidth, self.mapheight = emitter_shape
        if len(string_lengths) != self.mapheight:
            raise RuntimeError('string lengths do not match emitter height')
        if any(length > self.mapwidth for length in string_lengths):
            raise RuntimeError('string length exceeds emitter width')
        if sum(string_lengths) != len(self.lamps):
            raise RuntimeError('string lengths do not match lamp count')

        self.emitters = []
        for string_index, string_length in enumerate(string_lengths):
            for led_index in range(string_length):
                self.emitters.append((led_index, string_index))

        super(tree, self).__init__()

    def getVertices(self):
        verts = []
        ids = []
        emitters = []
        
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
                emitters.append(self.emitters[i])
                
        return { 'position' : verts, 'id' : ids, 'emitter' : emitters }
                
    def setColor(self, color):
        self.color = color

    def setTime(self, time):
        self.time = time

    def draw(self):
        loc = gl.glGetUniformLocation(self.program, "tex")
        gl.glUniform1i(loc, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)

        loc = gl.glGetUniformLocation(self.program, "emitter_dimensions")
        gl.glUniform2f(loc, self.mapwidth, self.mapheight)

        loc = gl.glGetUniformLocation(self.program, "time")
        gl.glUniform1f(loc, self.time)
        super(tree, self).draw()

    def setTexture(self, tex):
        self.tex = tex
