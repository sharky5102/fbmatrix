#!/usr/bin/env python3
import fbmatrix
import argparse
import assembly.bytearray
import common

def render_contrast():
    global bytearray
    
    width = 32
    height = 32
    
    bytes = b''
    for y in range(0, height):
        for x in range(0, width):
            c = b'\x00\x00\x00'
            if x+y & 3 == 0:
                c = b'\xff\xff\xff'
            else:
                c = b'\x00\x00\x00'
                
            if x == 0 or x == width-1 or y == 0 or y == height-1:
                c = b'\xff\x00\x00'
                
            bytes += c
    
    bytearray.setRGB(bytes, width, height)
    
    bytearray.render()

z = 0
def render_gradient():
    global bytearray
    global z
    global args
    
    width = 32
    height = 32
    
    data = b''
    for y in range(0, height):
        for x in range(0, width):
            if args.channel == 'all':
                c = bytes([x*4+z, x*4+z, x*4+z])
            if args.channel == 'red':
                c = bytes([x*4+z, 0, 0])
            if args.channel == 'green':
                c = bytes([0, x*4+z, 0])
            if args.channel == 'blue':
                c = bytes([0, 0, x*4+z])
            data += c
    
    bytearray.setRGB(data, width, height)
    
    bytearray.render()
    
    z+=1
    z = z % (128)

def render_tear():
    global bytearray
    global z
    global args
    
    width = 32
    height = 32
    
    data = b''
    for y in range(0, height):
        for x in range(0, width):
            if x >= z and x < z + 1:
                if args.channel == 'all':
                    c = bytes([255, 255, 255])
                if args.channel == 'red':
                    c = bytes([255, 0, 0])
                if args.channel == 'green':
                    c = bytes([0, 255, 0])
                if args.channel == 'blue':
                    c = bytes([0, 0, 255])
            else:
                c = bytes([0,0,0])

            data += c
    
    bytearray.setRGB(data, width, height)
    
    bytearray.render()
    
    z+=1
    z = z % (32)


parser = argparse.ArgumentParser(description='Amazing WS2811 VGA driver')
common.add_args(parser)

parser.add_argument('type', help='Test pattern. One of: gradient, contrast')
parser.add_argument('--channel', default='all', help='Test pattern color if applicable. One of red, green, blue or all')

patterns = {
  'contrast' : render_contrast,
  'gradient' : render_gradient,
  'tear': render_tear
}

args = parser.parse_args()

if args.type not in patterns:
    print('type must be one of %r' % patterns.keys())
    exit(1)
    
channels = ['all', 'red', 'green', 'blue']
if args.channel not in channels:
    print('channel muse be one of %r' % channels)
    exit(1)

matrix = common.renderer_from_args(args)

bytearray = assembly.bytearray.bytearray()

matrix.run(patterns[args.type])
