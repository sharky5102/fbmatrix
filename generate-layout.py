#!/usr/bin/python
import argparse
import json
import math
import sys


def source_mode(source_modes, index):
    if source_modes == 'row-colors':
        return index % 3 + 1

    return 0


def generate_square(columns, rows, source_modes):
    size = min(2.0 / columns, 2.0 / rows)
    yoff = -(rows * size) / 2
    xoff = -(columns * size) / 2
    points = []

    for i in range(0, columns * rows):
        row = int(i / columns)
        right = False if row % 2 else True

        column = i - (row * columns)
        if not right:
            column = columns - 1 - column

        points.append((
            xoff + ((column + 0.5) * size),
            yoff + ((row + 0.5) * size),
            0,
            source_mode(source_modes, row),
        ))

    return points


def ray_rectangle_intersection(angle, width, height):
    dx = math.cos(angle)
    dy = math.sin(angle)
    half_width = width / 2.0
    half_height = height / 2.0
    candidates = []

    if abs(dx) > 1e-12:
        t = (half_width if dx > 0 else -half_width) / dx
        y = t * dy
        if t > 0 and -half_height - 1e-9 <= y <= half_height + 1e-9:
            candidates.append((t, half_width if dx > 0 else -half_width, y))

    if abs(dy) > 1e-12:
        t = (half_height if dy > 0 else -half_height) / dy
        x = t * dx
        if t > 0 and -half_width - 1e-9 <= x <= half_width + 1e-9:
            candidates.append((t, x, half_height if dy > 0 else -half_height))

    if not candidates:
        raise RuntimeError('Spoke does not intersect rectangle')

    return min(candidates, key=lambda candidate: candidate[0])


def edge_name(x, y, width, height):
    half_width = width / 2.0
    half_height = height / 2.0

    if abs(x - half_width) < 1e-8:
        return 'right'
    if abs(y - half_height) < 1e-8:
        return 'top'
    if abs(x + half_width) < 1e-8:
        return 'left'
    if abs(y + half_height) < 1e-8:
        return 'bottom'

    raise RuntimeError('Spoke endpoint is not on a rectangle edge')


def quarter_name(x, y):
    if x >= 0 and y >= 0:
        return 'top-right'
    if x < 0 and y >= 0:
        return 'top-left'
    if x < 0 and y < 0:
        return 'bottom-left'

    return 'bottom-right'


def normalize_point(x, y, width, height, mode):
    scale = max(width, height) / 2.0
    return (x / scale, y / scale, 0, mode)


def points_on_spoke(angle, edge_distance, hub_radius, led_distance, outward, mode, width, height):
    count = int(math.floor((edge_distance - hub_radius) / led_distance)) + 1
    distances = [hub_radius + (i * led_distance) for i in range(0, count)]

    if not outward:
        distances = list(reversed(distances))

    return [
        normalize_point(
            math.cos(angle) * distance,
            math.sin(angle) * distance,
            width,
            height,
            mode,
        )
        for distance in distances
    ]


def inactive_hop_points(start, end, led_distance, width, height):
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    count = int(math.floor(distance / led_distance))
    points = []

    for i in range(0, count):
        t = (i + 1.0) / (count + 1.0)
        x = start[0] + ((end[0] - start[0]) * t)
        y = start[1] + ((end[1] - start[1]) * t)
        points.append(normalize_point(x, y, width, height, -1))

    return points


def generate_radial(width, height, led_distance, hub_radius, spokes, section_leds, source_modes):
    if spokes % 4 != 0:
        raise RuntimeError('Radial layout requires --spokes to be divisible by 4')
    if width <= 0 or height <= 0:
        raise RuntimeError('Radial layout requires positive --width and --height')
    if led_distance <= 0:
        raise RuntimeError('Radial layout requires positive --led-distance')
    if hub_radius < 0:
        raise RuntimeError('Radial layout requires non-negative --hub-radius')
    if section_leds <= 0:
        raise RuntimeError('Radial layout requires positive --section-leds')

    spacing = (2.0 * math.pi) / spokes
    first_angle = spacing / 2.0
    spoke_data = []

    for i in range(0, spokes):
        angle = (first_angle - (i * spacing)) % (2.0 * math.pi)
        edge_distance, edge_x, edge_y = ray_rectangle_intersection(angle, width, height)
        if edge_distance <= hub_radius:
            raise RuntimeError('Hub radius reaches beyond spoke %d' % i)

        hub_x = math.cos(angle) * hub_radius
        hub_y = math.sin(angle) * hub_radius

        spoke_data.append({
            'angle': angle,
            'edge': edge_name(edge_x, edge_y, width, height),
            'quarter': quarter_name(edge_x, edge_y),
            'edge_point': (edge_x, edge_y),
            'hub_point': (hub_x, hub_y),
            'edge_distance': edge_distance,
        })

    section_order = [
        ('top-left', 'left'),
        ('top-left', 'top'),
        ('top-right', 'top'),
        ('top-right', 'right'),
        ('bottom-right', 'right'),
        ('bottom-right', 'bottom'),
        ('bottom-left', 'bottom'),
        ('bottom-left', 'left'),
    ]

    points = []

    for section_index, (quarter, edge) in enumerate(section_order):
        section_spokes = [
            spoke
            for spoke in spoke_data
            if spoke['quarter'] == quarter and spoke['edge'] == edge
        ]

        section_spokes.sort(key=lambda spoke: spoke['angle'], reverse=True)
        section = []

        for spoke_index, spoke in enumerate(section_spokes):
            outward = spoke_index % 2 == 0
            mode = source_mode(source_modes, section_index)
            section.extend(points_on_spoke(
                spoke['angle'],
                spoke['edge_distance'],
                hub_radius,
                led_distance,
                outward,
                mode,
                width,
                height,
            ))

            if spoke_index + 1 < len(section_spokes):
                current_end = spoke['edge_point'] if outward else spoke['hub_point']
                next_spoke = section_spokes[spoke_index + 1]
                next_outward = (spoke_index + 1) % 2 == 0
                next_start = next_spoke['hub_point'] if next_outward else next_spoke['edge_point']
                section.extend(inactive_hop_points(current_end, next_start, led_distance, width, height))

        if len(section) > section_leds:
            raise RuntimeError(
                'Radial section %s/%s needs %d LEDs, but --section-leds is %d'
                % (quarter, edge, len(section), section_leds)
            )

        section.extend([(0.0, 0.0, 0, -1)] * (section_leds - len(section)))
        points.extend(section)

    return points


def parse_args():
    parser = argparse.ArgumentParser(description='Layout generator')
    parser.add_argument('type', choices=['square', 'radial'], help='Layout type to generate')
    parser.add_argument(
        '--source-modes',
        default='row-colors',
        choices=['framebuffer', 'row-colors'],
        help='Source mode values to write into the generated layout',
    )

    square = parser.add_argument_group('square layout')
    square.add_argument('--columns', help='Number of columns for matrix displays', type=int)
    square.add_argument('--rows', help='Number of rows for matrix displays', type=int)

    radial = parser.add_argument_group('radial layout')
    radial.add_argument('--width', help='Physical rectangle width in meters', type=float)
    radial.add_argument('--height', help='Physical rectangle height in meters', type=float)
    radial.add_argument('--led-distance', help='Physical LED spacing in meters', type=float)
    radial.add_argument('--hub-radius', help='Radius of the central hub in meters', type=float)
    radial.add_argument('--spokes', help='Number of radial spokes', type=int)
    radial.add_argument('--section-leds', help='LED slots per radial section', type=int, default=250)

    args = parser.parse_args()

    if args.type == 'square' and (args.columns is None or args.rows is None):
        parser.error('square layout requires --columns and --rows')

    if args.type == 'radial':
        missing = [
            name
            for name in ('width', 'height', 'led_distance', 'hub_radius', 'spokes')
            if getattr(args, name) is None
        ]
        if missing:
            parser.error('radial layout requires %s' % ', '.join('--' + name.replace('_', '-') for name in missing))

    return args


def main():
    args = parse_args()

    try:
        if args.type == 'square':
            points = generate_square(args.columns, args.rows, args.source_modes)
        else:
            points = generate_radial(
                args.width,
                args.height,
                args.led_distance,
                args.hub_radius,
                args.spokes,
                args.section_leds,
                args.source_modes,
            )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(json.dumps(points))
    return 0


if __name__ == '__main__':
    sys.exit(main())
