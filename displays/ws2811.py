import geometry
import math
import ledlayout
import OpenGL.GL as gl
import numpy as np
import ctypes

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
        uniform highp float supersample;
		
        out highp vec4 f_color;
        in highp vec2 v_texcoor;
        in highp float v_id;

        const int BIT_A = 2;
        const int BIT_B = 6;
        const int BIT_C = 7;
        const int BIT_D = 0;
        const int BIT_E = 4;
        const int BIT_OE = 0;
        const int BIT_LAT = 1;
        const int BIT_CLK = 5;
        const int BIT_R1 = 1;
        const int BIT_G1 = 1;
        const int BIT_B1 = 2;
        const int BIT_R2 = 0;
        const int BIT_G2 = 4;
        const int BIT_B2 = 3;
        
        const int MASK_A = (1 << BIT_A);
        const int MASK_B = (1 << BIT_B);
        const int MASK_C = (1 << BIT_C);
        const int MASK_D = (1 << BIT_D);
        const int MASK_E = (1 << BIT_E);
        const int MASK_OE = (1 << BIT_OE);
        const int MASK_LAT = (1 << BIT_LAT);
        const int MASK_CLK = (1 << BIT_CLK);
        const int MASK_R1 = (1 << BIT_R1);
        const int MASK_G1 = (1 << BIT_G1);
        const int MASK_B1 = (1 << BIT_B1);
        const int MASK_R2 = (1 << BIT_R2);
        const int MASK_G2 = (1 << BIT_G2);
        const int MASK_B2 = (1 << BIT_B2);

        const int depth = 12;
        const int height = 16;
        
        void setBits(out ivec3 p, lowp int D, lowp int LAT, lowp int A, lowp int B2, lowp int E, lowp int B, lowp int C, lowp int R2, lowp int G1, lowp int G2, lowp int CLK, lowp int OE, lowp int R1, lowp int B1) {
                p.r =   (D   > 0 ? MASK_D : 0) +
                        (LAT > 0 ? MASK_LAT : 0) +
                        (A   > 0 ? MASK_A : 0) +
                        (B2  > 0 ? MASK_B2 : 0) +
                        (E   > 0 ? MASK_E : 0) +
                        (B   > 0 ? MASK_B : 0) +
                        (C   > 0 ? MASK_C : 0);

                p.g = (R2 > 0 ? MASK_R2 : 0) +
                      (G1 > 0 ? MASK_G1 : 0) +
                      (G2 > 0 ? MASK_G2 : 0) +
                      (CLK > 0 ? MASK_CLK : 0);

                p.b = (OE > 0 ? MASK_OE : 0) +
                      (R1 > 0 ? MASK_R1 : 0) +
                      (B1 > 0 ? MASK_B1 : 0);
        }
        
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
				highp vec4 lamp = texelFetch(lamptex, ivec2(pixel, 0), 0);
				int source_mode = int(lamp.w + 0.5);
				if (source_mode == 1) {
					t = vec3(1.0, 0.0, 0.0);
				} else if (source_mode == 2) {
					t = vec3(0.0, 0.0, 1.0);
				} else if (source_mode == 3) {
					t = vec3(0.0, 1.0, 0.0);
				} else {
					highp vec2 lamppos = lamp.xy * vec2(0.5,0.5) + vec2(.5,.5);
					t = textureLod(tex, lamppos, supersample).rgb;
				}
			}
			
            t = pow(t, vec3(2.2));
            
			int bitvalue;
			
			if (bit < 8)
				bitvalue = (int(t.r * 255.0) >> (7 - bit)) & 1;
			else if (bit < 16)
				bitvalue = (int(t.g * 255.0) >> (15 - bit)) & 1;
			else
				bitvalue = (int(t.b * 255.0) >> (23 - bit)) & 1;
				            
            int signal;
            
            if(bitvalue == 0)
                signal = bitoffset < 0.2 ? 1 : 0;
            else
                signal = bitoffset < 0.46 ? 1 : 0;

            // setBits(data, D, LAT, A, B2, E, B, C, R2, G1, G2, CLK, OE, R1, B1);
            lowp ivec3 data;
            setBits(data, signal, signal, signal, signal, signal, signal, signal, signal, signal, signal, signal, signal, signal, signal);
            
            f_color = vec4(float(data.r) / 255.0, float(data.g) / 255.0, float(data.b) / 255.0, 1.0);            
        } """
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS

    def __init__(self, layout, supersample):
        self.lamps = ledlayout.require_xyzc_layout(layout)
        self.tex = 0
        self.supersample = supersample

        # Present the lamp locations as a 1d texture
        self.mapwidth = pow(2, math.ceil(math.log(len(self.lamps))/math.log(2)))

        data = np.zeros(self.mapwidth, (np.float32, 4))
        
        for i in range(0, len(self.lamps)):
            lamp = self.lamps[i]
            data[i][0] = lamp[0];
            data[i][1] = -lamp[1];
            data[i][2] = lamp[2];
            data[i][3] = lamp[3];
        
        self.lamptex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.lamptex)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameterf(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA16F, self.mapwidth, 1, 0, gl.GL_RGBA, gl.GL_FLOAT, data)

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

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)


        super(signalgenerator, self).draw()

    def setTexture(self, tex):
        self.tex = tex
        
