#!/usr/bin/env python3
import fbmatrix
import argparse
import time
import assembly.bytearray
from ffpyplayer.player import MediaPlayer
import numpy as np
from pyrr import Matrix44

def render():
    global bytearray, player
    global args
    
    videoAspect = screenAspect = args.columns/args.rows
    
    frame, val = player.get_frame()

    if frame:
        img, t = frame

        data = img.to_bytearray()[0]
        size = img.get_size()
        
        videoAspect = size[0]/size[1]
        
        data = bytes(data)
        bytearray.setRGB(data, size[0], size[1])

        time.sleep(val)

    M = np.eye(4, dtype=np.float32)
    
    if screenAspect > videoAspect:
        # Pillar box
        M = M * Matrix44.from_scale( (1, videoAspect/screenAspect, 1))
    else:
        # Letter box
        M = M * Matrix44.from_scale( (1, screenAspect/videoAspect, 1))

    bytearray.setProjection(M)
    bytearray.render()

parser = argparse.ArgumentParser(description='Amazing WS2811 VGA driver')
parser.add_argument('--emulate', action='store_const', const=True, help='Emulate tree')
parser.add_argument('--preview', action='store_const', const=True, help='Preview source video instead of actual output')
parser.add_argument('--raw', action='store_const', const=True, help='Raw mode; show raw output in a window')
parser.add_argument('--display', default='hub75e', help='Display type (ws2811, hub75e)')
parser.add_argument('--columns', default=32, help='Number of columns for matrix displays', type=int)
parser.add_argument('--rows', default=32, help='Number of rows for matrix displays', type=int)
parser.add_argument('videofile', help='Video to play')

args = parser.parse_args()

player = MediaPlayer(args.videofile)

matrix = fbmatrix.renderer(emulate=args.emulate, preview=args.preview, raw=args.raw, display=args.display, columns=args.columns, rows=args.rows)

bytearray = assembly.bytearray.bytearray()

matrix.run(render)
