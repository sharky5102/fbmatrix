"""RGB upload with the first pixel at the top left of the framebuffer."""
from assembly.bytearray import bytearray


class NetworkMatrixQuad(bytearray):
    def getVertices(self):
        return {
            'position': [(-1, 1), (1, 1), (1, -1), (-1, -1)],
            'texcoor': [(0, 0), (1, 0), (1, 1), (0, 1)],
        }
