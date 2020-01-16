#!/usr/bin/env python3
import fbmatrix
import argparse
import time
import assembly.bytearray
from ffpyplayer.player import MediaPlayer

def render():
    global bytearray, player
    
    frame, val = player.get_frame()

    if frame:
        img, t = frame

        data = img.to_bytearray()[0]
        size = img.get_size()
        data = bytes(data)
        bytearray.setRGB(data, size[0], size[1])

        time.sleep(val)
    
    bytearray.render()

parser = argparse.ArgumentParser(description='Amazing WS2811 VGA driver')
parser.add_argument('--emulate', action='store_const', const=True, help='Emulate tree')
parser.add_argument('--preview', action='store_const', const=True, help='Preview windows instead of actual output')
parser.add_argument('--raw', action='store_const', const=True, help='Raw mode - use with --preview to view raw pixel data')
parser.add_argument('--display', default='ws2811', help='Display type (ws2811, hub75e)')
parser.add_argument('videofile', help='Video to play')

args = parser.parse_args()

player = MediaPlayer(args.videofile)

matrix = fbmatrix.renderer(emulate=args.emulate, preview=args.preview, raw=args.raw, display=args.display)

bytearray = assembly.bytearray.bytearray()

matrix.run(render)
