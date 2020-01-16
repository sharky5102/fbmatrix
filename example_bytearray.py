#!/usr/bin/env python3
import fbmatrix
import argparse
import assembly.bytearray

def render():
    global bytearray
    
    width = 4
    height = 4
    
    bytearray.setRGB((b'\xff\x00\x00' * width + b'\x00\xff\x00' * width) * int(height/2), width, height)
    
    bytearray.render()

parser = argparse.ArgumentParser(description='Amazing WS2811 VGA driver')
parser.add_argument('--emulate', action='store_const', const=True, help='Emulate tree')
parser.add_argument('--preview', action='store_const', const=True, help='Preview windows instead of actual output')
parser.add_argument('--raw', action='store_const', const=True, help='Raw mode - use with --preview to view raw pixel data')
parser.add_argument('--display', default='hub75e', help='Display type (ws2811, hub75e)')

args = parser.parse_args()

matrix = fbmatrix.renderer(emulate=args.emulate, preview=args.preview, raw=args.raw, display=args.display, supersample=0)

bytearray = assembly.bytearray.bytearray()

matrix.run(render)
