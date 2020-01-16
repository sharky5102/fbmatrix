import geometry
import math
import OpenGL.GL as gl
import numpy as np
import ctypes
import json

class signalgenerator(geometry.base):
    vertex_code = """
        uniform mat4 modelview;
        uniform mat4 projection;
        
        in vec2 position;
        in vec2 texcoor;

        out vec2 v_texcoor;
        
        void main()
        {
            gl_Position = projection * modelview * vec4(position,0,1);
            v_texcoor = texcoor;
        } """

    fragment_code = """
        uniform sampler2D tex;
        uniform sampler2D lamptex;
		uniform int max_id;
		
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp float v_id;
        
        void main()
        {
            int y = int(v_texcoor.y * 500.0);
			int pixel, bit;
			lowp float bitoffset;
			
			if(false) {
				// ws2811 - 400kbit/sec
				pixel = y / 2;
				int subpixel = y % 2;
				
				bit = int(v_texcoor.x * 12.0); // 12 bits per scanline
				bit += int(subpixel * 12); // second scanline
				bitoffset = (v_texcoor.x * 12.0) - float(bit % 12);
            } else {
                // ws2812b - 800kbit/sec
                pixel = y;

				bit = int(v_texcoor.x * 24.0); // 24 bits per scanline
				bitoffset = (v_texcoor.x * 24.0) - float(bit % 24);
			}
			
			highp vec3 t;
			
			if (pixel > max_id) {
				t = vec3(1.0, 1.0, 1.0);
			} else {
				highp vec2 lamppos = texelFetch(lamptex, ivec2(pixel, 0), 0).xy * vec2(0.5,0.5) + vec2(.5,.5);
				t = textureLod(tex, lamppos, 3.0).rgb;
			}
			
            t = pow(t, vec3(2.2));
            
			int bitvalue;
			
			if (bit < 8)
				bitvalue = (int(t.r * 255.0) >> (7 - bit)) & 1;
			else if (bit < 16)
				bitvalue = (int(t.g * 255.0) >> (15 - bit)) & 1;
			else
				bitvalue = (int(t.b * 255.0) >> (23 - bit)) & 1;
				            
            highp float color;
            
            if(bitvalue == 0)
                color = bitoffset < 0.2 ? 1.0 : 0.0;
            else
                color = bitoffset < 0.46 ? 1.0 : 0.0;

            f_color = vec4(color, color, color, 1);
            
        } """
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS

    def __init__(self, filename):
        f = open(filename, 'rt')
        data = f.read()
        self.lamps = json.loads(data)
        self.tex = 0

        # Present the lamp locations as a 1d texture
        self.mapwidth = pow(2, math.ceil(math.log(len(self.lamps))/math.log(2)))

        data = np.zeros(self.mapwidth, (np.float32, 3))
        
        for i in range(0, len(self.lamps)):
            lamp = self.lamps[i]
            data[i][0] = lamp[0];
            data[i][1] = -lamp[1];
            data[i][2] = lamp[2];
        
        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB16F, self.mapwidth, 1, 0, gl.GL_RGB, gl.GL_FLOAT, data)

        super(signalgenerator, self).__init__()

    def getVertices(self):
        verts = [(-1, -1), (+1, -1), (+1, +1), (-1, +1)]
        coors = [(0, 1), (1, 1), (1, 0), (0, 0)]
        
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

        loc = gl.glGetUniformLocation(self.program, "max_id")
        gl.glUniform1i(loc, len(self.lamps))

        super(signalgenerator, self).draw()

    def setTexture(self, tex):
        self.tex = tex
        