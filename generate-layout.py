#!/usr/bin/python
import math
import json
import argparse

parser = argparse.ArgumentParser(description='Layout generator')
parser.add_argument('--columns', help='Number of columns for matrix displays', type=int, required=True)
parser.add_argument('--rows', help='Number of rows for matrix displays', type=int, required=True)

args = parser.parse_args()

x = args.columns
y = args.rows

n = x * y
size = min(2.0 / x, 2.0 / y)

yoff = - (y * size)/2
xoff = - (x * size)/2

points = []

for i in range(0, n):
    row = int(i / x)
    right = False if row % 2 else True

    column = i - (row * x)
    if not right:
        column = x - 1 - column
    
    points.append( (xoff + ((column+0.5) * size), yoff + ((row+0.5) * size), 0) )


print(json.dumps(points))

