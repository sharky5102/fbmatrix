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

    if not args.stretch:
        if args.fit:
            if screenAspect > videoAspect:
                # Pillar box
                M = M * Matrix44.from_scale( (1, screenAspect/videoAspect, 1, 1))
            else:
                # Letter box
                M = M * Matrix44.from_scale( (videoAspect/screenAspect, 1, 1))
        else:
            if screenAspect > videoAspect:
                # Pillar box
                M = M * Matrix44.from_scale( (videoAspect/screenAspect, 1, 1))
            else:
                # Letter box
                M = M * Matrix44.from_scale( (1, screenAspect/videoAspect, 1))

    bytearray.setProjection(M)
    bytearray.render()

import common

parser = argparse.ArgumentParser(description='Framebuffer RGB matrix player')
common.add_args(parser)
parser.add_argument('--fit', action='store_true', help='Fit the video as large as it can but maintaining aspect ratio. This means some part will be cut off')
parser.add_argument('--stretch', action='store_true', help='Stretch the video to fit the screen exactly, which means aspect ratio will not be preserved. I really hate it when people do this.')
parser.add_argument('videofile', help='Video to play')

args = parser.parse_args()

player = MediaPlayer(args.videofile)

matrix = common.renderer_from_args(args)

bytearray = assembly.bytearray.bytearray(supersample = args.supersample)

matrix.run(render)
