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

        const int depth = 12;
        const int height = 16;
        
        void setRBits(out ivec3 p, lowp int D, lowp int LAT, lowp int A, lowp int B2, lowp int E, lowp int B, lowp int C) {
                p.r = (D   << BIT_D) |
                      (LAT << BIT_LAT) |
                      (A   << BIT_A) |
                      (B2  << BIT_B2) |
                      (E   << BIT_E) |
                      (B   << BIT_B) |
                      (C   << BIT_C);
        }

        void setGBits(inout ivec3 p, lowp int R2, lowp int G1, lowp int G2, lowp int CLK) {
                p.g = (R2  << BIT_R2) |
                      (G1  << BIT_G1) |
                      (G2  << BIT_G2) |
                      (CLK << BIT_CLK);
        }

        void setBBits(inout ivec3 p, lowp int OE, lowp int R1, lowp int B1) {
                p.b = (OE  << BIT_OE) |
                      (R1  << BIT_R1) |
                      (B1  << BIT_B1);
        }

        ORDER_FUNC;

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
            highp vec3 top = textureLod(tex, ttexpos, supersample).rgb;
            highp vec2 btexpos = vec2(float(dx) / float(columns), 1.0 - (float(dy+16) / 31.0));
            highp vec3 bottom = textureLod(tex, btexpos, supersample).rgb;
            
            lowp int dbitplane = 15 - dsubframe;
            lowp int OE = (t < ((4096 >> subframe))) ? 1 : 0;
            
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
            setRBits(data, D, LAT, A, B2, E, B, C);
            setGBits(data, R2, G1, G2, CLK);
            setBBits(data, OE, R1, B1);
            
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
        
    attributes = { 'position' : 2, 'texcoor' : 2 }
    primitive = gl.GL_QUADS

    def __init__(self, columns, rows, supersample, order='line-first'):
        self.columns = columns
        self.rows = rows
        self.supersample = supersample
        self.fragment_code = self.fragment_code.replace('ORDER_FUNC;', self.order[order])
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
        