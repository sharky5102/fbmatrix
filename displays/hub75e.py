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
        uniform int columns;
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

        ORDER_FUNC;
        OUTPUT_ENABLE_FUNC;

        void main()
        {
            highp int physx = int(v_texcoor.x * 4096.0);
            highp int physy = int(v_texcoor.y * 194.0);
            
            highp int physend = 192;
            
            highp int dsubframe;
            highp int dy;
            
            getLineParams(physy, dy, dsubframe);
            
            highp int subframe;
            highp int y;
            
            getLineParams(physy-1, y, subframe);
            
            highp int nextsubframe;
            highp int nexty;
            
            getLineParams(physy+1, nexty, nextsubframe);
            
            if (physy == 0)
                y = 0;
                
            if (nexty != y && physx > 4000)
                y++;

            highp int t = physx;
            
            lowp ivec3 data;
            lowp int LAT = t >= 3850 && t < 3860 ? 1 : 0;
            
            lowp int A = ((y & 0x1) > 0) ? 1 : 0;
            lowp int B = ((y & 0x2) > 0) ? 1 : 0;
            lowp int C = ((y & 0x4) > 0) ? 1 : 0;
            lowp int D = ((y & 0x8) > 0) ? 1 : 0;
            lowp int E = ((y & 0x10) > 0) ? 1 : 0;

            int dx = (1919 - (t / 2)) % columns;
            highp vec2 ttexpos = vec2(float(dx) / float(columns), 1.0 - (float(dy) / 31.0));
            highp vec3 top = texture(tex, ttexpos).rgb;
            highp vec2 btexpos = vec2(float(dx) / float(columns), 1.0 - (float(dy+16) / 31.0));
            highp vec3 bottom = texture(tex, btexpos).rgb;
            
            lowp int dbitplane = 15 - dsubframe;

            lowp int OE = getOE(t, subframe);
            
            if (t > 3840)
                OE = 0;

            if (physy == 0)
                OE = 0;
            
            lowp int CLK;
            if (t < 3840)
                CLK = ((t & 1) == 0) ? 0 : 1;
            else
                CLK = 0;
                
            lowp int R1 = 0, G1 = 0, B1 = 0, R2 = 0, G2 = 0, B2 = 0;

            top = pow(top, vec3(2.2));
            bottom = pow(bottom, vec3(2.2));

            R1 = (int(top.r * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;
            G1 = (int(top.g * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;
            B1 = (int(top.b * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;
            
            R2 = (int(bottom.r * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;
            G2 = (int(bottom.g * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;
            B2 = (int(bottom.b * 65535.0 ) & (1 << dbitplane)) > 0 ? 1 : 0;

            if (physy >= physend) {
              R1 = G1 = B1 = R2 = G2 = B2 = 0;
              OE = 0;
            }
            
            OE = OE == 0 ? 1 : 0;
            setBits(data, D, LAT, A, B2, E, B, C, R2, G1, G2, CLK, OE, R1, B1);
            
            f_color = vec4(float(data.r) / 255.0, float(data.g) / 255.0, float(data.b) / 255.0, 1.0);
            
        } """
        
    order = {
        'line-first': """
            void getLineParams(int physy, out int y, out int subframe) {
                y = physy / depth;
                subframe = physy % depth;
            }""",
        'field-first': """
            void getLineParams(int physy, out int y, out int subframe) {
                y = physy % height;
                subframe = physy / height;
            }""" 
    }

    output_enable = {
        'normal': """
            int getOE(int t, int subframe) {
                return (t < ((4096 >> subframe))) ? 1 : 0;
            }
        """,
        'es-pwm': """
        int getOE(int t, int subframe) {
            int rep;
            
            switch(subframe) {
                case 0: rep = 1; break;
                default:
                    rep = (1 << subframe) + subframe;
            }
            return (t % rep) == 0 ? 1 : 0;
        }
        """
    }
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS

    def __init__(self, columns, rows, supersample, order='line-first', oe='normal'):
        self.columns = columns
        self.rows = rows
        self.supersample = supersample
        self.fragment_code = self.fragment_code.replace('ORDER_FUNC;', self.order[order]).replace('OUTPUT_ENABLE_FUNC;', self.output_enable[oe])
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

        loc = gl.glGetUniformLocation(self.program, "columns")
        gl.glUniform1i(loc, self.columns)

        loc = gl.glGetUniformLocation(self.program, "supersample")
        gl.glUniform1f(loc, self.supersample)
        
        super(signalgenerator, self).draw()

    def setTexture(self, tex):
        self.tex = tex
        