#!/usr/bin/env python3
import fbmatrix
import argparse
import assembly.bytearray

def render():
    global bytearray
    
    width = 32
    height = 32
    
    bytes = b''
    for y in range(0, height):
        for x in range(0, width):
            c = b'\x00\x00\x00'
            if x+y & 7 == 0:
                c = b'\xff\xff\xff'
            else:
                c = b'\x00\x00\x00'
                
            if x == 0 or x == width-1 or y == 0 or y == height-1:
                c = b'\xff\x00\x00'
                
            bytes += c
    
    bytearray.setRGB(bytes, width, height)
    
    bytearray.render()

parser = argparse.ArgumentParser(description='Amazing WS2811 VGA driver')
parser.add_argument('--emulate', action='store_const', const=True, help='Emulate tree')
parser.add_argument('--preview', action='store_const', const=True, help='Preview windows instead of actual output')
parser.add_argument('--raw', action='store_const', const=True, help='Raw mode - use with --preview to view raw pixel data')
parser.add_argument('--display', default='hub75e', help='Display type (ws2811, hub75e)')
parser.add_argument('--field-first', action='store_true', help='Render in field-first order (instead of line-first)')

args = parser.parse_args()

matrix = fbmatrix.renderer(emulate=args.emulate, preview=args.preview, raw=args.raw, display=args.display, supersample=0, interpolate=False, order='field-first' if args.field_first else 'line-first')

bytearray = assembly.bytearray.bytearray()

matrix.run(render)
