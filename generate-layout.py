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


def ray_rectangle_intersection_from(origin_x, origin_y, angle, width, height):
    dx = math.cos(angle)
    dy = math.sin(angle)
    half_width = width / 2.0
    half_height = height / 2.0
    candidates = []

    if abs(dx) > 1e-12:
        x_edge = half_width if dx > 0 else -half_width
        t = (x_edge - origin_x) / dx
        y = origin_y + (t * dy)
        if t > 0 and -half_height - 1e-9 <= y <= half_height + 1e-9:
            candidates.append((t, x_edge, y))

    if abs(dy) > 1e-12:
        y_edge = half_height if dy > 0 else -half_height
        t = (y_edge - origin_y) / dy
        x = origin_x + (t * dx)
        if t > 0 and -half_width - 1e-9 <= x <= half_width + 1e-9:
            candidates.append((t, x, y_edge))

    if not candidates:
        raise RuntimeError('Spoke does not intersect rectangle')

    return min(candidates, key=lambda candidate: candidate[0])


def ray_rectangle_intersection(angle, width, height):
    return ray_rectangle_intersection_from(0.0, 0.0, angle, width, height)


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


def edge_crossing_position(edge, point, width, height):
    x, y = point

    if edge == 'top' or edge == 'bottom':
        return x + (width / 2.0)

    return y + (height / 2.0)


def print_perimeter_crossings(crossings):
    for edge in ('top', 'right', 'bottom', 'left'):
        values = sorted(crossings[edge])
        formatted = ', '.join('%.3f' % value for value in values)
        print('Perimeter crossings %s: %s' % (edge, formatted), file=sys.stderr)


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


def clipped_endpoint(start, end, max_length):
    if max_length is None:
        return end

    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance <= max_length:
        return end
    if distance <= 1e-12:
        return end

    scale = max_length / distance
    return (
        start[0] + ((end[0] - start[0]) * scale),
        start[1] + ((end[1] - start[1]) * scale),
    )


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


def points_on_segment(start, end, led_distance, outward, mode, width, height):
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    count = int(math.floor(distance / led_distance)) + 1
    distances = [i * led_distance for i in range(0, count)]

    if not outward:
        distances = list(reversed(distances))

    if distance <= 1e-12:
        raise RuntimeError('Segment has no length')

    dx = (end[0] - start[0]) / distance
    dy = (end[1] - start[1]) / distance

    return [
        normalize_point(
            start[0] + (dx * offset),
            start[1] + (dy * offset),
            width,
            height,
            mode,
        )
        for offset in distances
    ]


def inactive_hop_points(start, end, led_distance, width, height):
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    count = int(math.floor(distance / led_distance))
    points = []

    for i in range(0, count):
        t = (i + 1.0) / (count + 1.0)
        x = start[0] + ((end[0] - start[0]) * t)
        y = start[1] + ((end[1] - start[1]) * t)
        points.append(normalize_point(x, y, width, height, 4))

    return points


def finish_fixed_section(section, section_leds, description):
    if len(section) > section_leds:
        raise RuntimeError(
            '%s needs %d LEDs, but --section-leds is %d'
            % (description, len(section), section_leds)
        )

    return section + ([(0.0, 0.0, 0, -1)] * (section_leds - len(section)))


def generate_radial(width, height, led_distance, hub_radius, spokes, section_leds, source_modes, max_spoke_length=None):
    if spokes % 8 != 0:
        raise RuntimeError('Radial layout requires --spokes to be divisible by 8')
    if width <= 0 or height <= 0:
        raise RuntimeError('Radial layout requires positive --width and --height')
    if led_distance <= 0:
        raise RuntimeError('Radial layout requires positive --led-distance')
    if hub_radius < 0:
        raise RuntimeError('Radial layout requires non-negative --hub-radius')
    if section_leds <= 0:
        raise RuntimeError('Radial layout requires positive --section-leds')
    if max_spoke_length is not None and max_spoke_length <= 0:
        raise RuntimeError('Radial layout requires positive --max-spoke-length')

    spacing = (2.0 * math.pi) / spokes
    first_angle = spacing / 2.0
    spoke_data = []

    for i in range(0, spokes):
        angle = (first_angle - (i * spacing)) % (2.0 * math.pi)
        edge_distance, edge_x, edge_y = ray_rectangle_intersection(angle, width, height)
        if edge_distance <= hub_radius:
            raise RuntimeError('Hub radius reaches beyond spoke %d' % i)

        perimeter_point = (edge_x, edge_y)
        original_edge = edge_name(edge_x, edge_y, width, height)
        hub_x = math.cos(angle) * hub_radius
        hub_y = math.sin(angle) * hub_radius
        active_length = edge_distance - hub_radius
        if max_spoke_length is not None:
            active_length = min(active_length, max_spoke_length)
            edge_distance = hub_radius + active_length
            edge_x = math.cos(angle) * edge_distance
            edge_y = math.sin(angle) * edge_distance

        spoke_data.append({
            'index': i,
            'angle': angle,
            'edge': original_edge,
            'quarter': quarter_name(edge_x, edge_y),
            'edge_point': (edge_x, edge_y),
            'perimeter_point': perimeter_point,
            'hub_point': (hub_x, hub_y),
            'edge_distance': edge_distance,
        })

    print_perimeter_crossings({
        edge: [
            edge_crossing_position(edge, spoke['perimeter_point'], width, height)
            for spoke in spoke_data
            if spoke['edge'] == edge
        ]
        for edge in ('top', 'right', 'bottom', 'left')
    })

    quarter_order = [
        'top-left',
        'top-right',
        'bottom-right',
        'bottom-left',
    ]

    points = []

    for quarter_index, quarter in enumerate(quarter_order):
        quarter_spokes = [
            spoke
            for spoke in spoke_data
            if spoke['quarter'] == quarter
        ]
        quarter_spokes.sort(key=lambda spoke: spoke['angle'], reverse=True)
        if len(quarter_spokes) < 4:
            raise RuntimeError(
                'Radial quarter %s has %d spokes; quarters need at least 4 spokes to make two hub-to-hub sections'
                % (quarter, len(quarter_spokes))
            )
        split = min(
            range(2, len(quarter_spokes), 2),
            key=lambda candidate: abs((len(quarter_spokes) - candidate) - candidate),
        )

        for half_index, section_spokes in enumerate((quarter_spokes[:split], quarter_spokes[split:])):
            section_index = (quarter_index * 2) + half_index
            if len(section_spokes) % 2:
                raise RuntimeError(
                    'Radial section %s/%d has %d spokes; sections must have an even number of spokes to start and end at the hub'
                    % (quarter, half_index, len(section_spokes))
                )

            section = []

            for spoke_index, spoke in enumerate(section_spokes):
                outward = spoke_index % 2 == 0
                mode = source_mode(source_modes, spoke['index'])
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

            print(
                'Radial section %s/%d: %d spokes, %d used LEDs'
                % (quarter, half_index, len(section_spokes), len(section)),
                file=sys.stderr,
            )
            points.extend(finish_fixed_section(section, section_leds, 'Radial section %s/%d' % (quarter, half_index)))

    return points


def median(values):
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2

    if len(sorted_values) % 2:
        return sorted_values[middle]

    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def dual_radial_edge_spacing(spokes):
    spacings = []

    for i in range(1, len(spokes)):
        prev = spokes[i - 1]['edge_point']
        current = spokes[i]['edge_point']
        if spokes[i - 1]['edge'] == spokes[i]['edge']:
            spacings.append(math.hypot(current[0] - prev[0], current[1] - prev[1]))

    return spacings


def dual_radial_section_points(runs, led_distance, mode, width, height):
    section = []

    for run_index, run in enumerate(runs):
        outward = run_index % 2 == 0
        section.extend(points_on_segment(
            run['start'],
            run['end'],
            led_distance,
            outward,
            mode,
            width,
            height,
        ))

        if run_index + 1 < len(runs):
            current_end = run['end'] if outward else run['start']
            next_run = runs[run_index + 1]
            next_outward = (run_index + 1) % 2 == 0
            next_start = next_run['start'] if next_outward else next_run['end']
            section.extend(inactive_hop_points(current_end, next_start, led_distance, width, height))

    return section


def split_dual_radial_part(part_name, runs, led_distance, section_leds, source_modes, section_index, width, height):
    if len(runs) < 4 or len(runs) % 2:
        raise RuntimeError('Dual radial part %s must contain an even number of runs for two sections' % part_name)

    best = None
    for split in range(2, len(runs), 2):
        first = dual_radial_section_points(
            runs[:split],
            led_distance,
            source_mode(source_modes, section_index),
            width,
            height,
        )
        second = dual_radial_section_points(
            runs[split:],
            led_distance,
            source_mode(source_modes, section_index + 1),
            width,
            height,
        )
        score = max(len(first), len(second))
        if best is None or score < best[0]:
            best = (score, split, first, second)

    sections = []
    for offset, section in enumerate((best[2], best[3])):
        section_runs = runs[:best[1]] if offset == 0 else runs[best[1]:]
        fan_runs = sum(1 for run in section_runs if run['kind'] == 'fan')
        center_runs = sum(1 for run in section_runs if run['kind'] == 'center')
        print(
            'Dual radial section %s/%d: %d fan runs, %d center runs, %d used LEDs'
            % (part_name, offset, fan_runs, center_runs, len(section)),
            file=sys.stderr,
        )
        sections.extend(finish_fixed_section(
            section,
            section_leds,
            'Dual radial section %s/%d' % (part_name, offset),
        ))

    return sections


def generate_dual_radial(
        width,
        height,
        led_distance,
        hub_radius,
        spokes,
        center_spacing,
        section_leds,
        source_modes,
        max_spoke_length=None):
    if width <= 0 or height <= 0:
        raise RuntimeError('Dual radial layout requires positive --width and --height')
    if led_distance <= 0:
        raise RuntimeError('Dual radial layout requires positive --led-distance')
    if hub_radius < 0:
        raise RuntimeError('Dual radial layout requires non-negative --hub-radius')
    if center_spacing < 0:
        raise RuntimeError('Dual radial layout requires non-negative --center-spacing')
    if center_spacing == 0:
        return generate_radial(
            width,
            height,
            led_distance,
            hub_radius,
            spokes,
            section_leds,
            source_modes,
            max_spoke_length=max_spoke_length,
        )
    if spokes % 4 != 0:
        raise RuntimeError('Dual radial layout requires --spokes to be divisible by 4')
    if center_spacing + (2.0 * hub_radius) >= width:
        raise RuntimeError('Dual radial layout requires --center-spacing plus two hub radii to fit inside --width')
    if section_leds <= 0:
        raise RuntimeError('Dual radial layout requires positive --section-leds')
    if max_spoke_length is not None and max_spoke_length <= 0:
        raise RuntimeError('Dual radial layout requires positive --max-spoke-length')

    left_hub = (-center_spacing / 2.0, 0.0)
    right_hub = (center_spacing / 2.0, 0.0)
    side_spokes = spokes // 2
    spacing = math.pi / side_spokes
    spoke_sets = {
        'left-top': [],
        'left-bottom': [],
        'right-top': [],
        'right-bottom': [],
    }

    for i in range(0, side_spokes):
        left_angle = (math.pi / 2.0) + (spacing / 2.0) + (i * spacing)
        right_angle = (-math.pi / 2.0) + (spacing / 2.0) + (i * spacing)

        for side_name, hub, angle in (('left', left_hub, left_angle), ('right', right_hub, right_angle)):
            edge_distance, edge_x, edge_y = ray_rectangle_intersection_from(hub[0], hub[1], angle, width, height)
            if edge_distance <= hub_radius:
                raise RuntimeError('Hub radius reaches beyond %s spoke %d' % (side_name, i))

            start = (
                hub[0] + (math.cos(angle) * hub_radius),
                hub[1] + (math.sin(angle) * hub_radius),
            )
            end = clipped_endpoint(start, (edge_x, edge_y), max_spoke_length)
            spoke = {
                'kind': 'fan',
                'edge': edge_name(edge_x, edge_y, width, height),
                'edge_point': (edge_x, edge_y),
                'perimeter_point': (edge_x, edge_y),
                'start': start,
                'end': end,
            }
            vertical_half = 'top' if edge_y >= 0 else 'bottom'
            spoke_sets['%s-%s' % (side_name, vertical_half)].append(spoke)

    edge_spacings = []
    for side_name in ('left', 'right'):
        side_ordered = (
            spoke_sets['%s-top' % side_name]
            + list(reversed(spoke_sets['%s-bottom' % side_name]))
        )
        edge_spacings.extend(dual_radial_edge_spacing(side_ordered))

    center_line_spacing = median(edge_spacings) if edge_spacings else led_distance
    center_start = spoke_sets['left-top'][0]['edge_point'][0]
    center_end = spoke_sets['right-top'][-1]['edge_point'][0]
    center_width = center_end - center_start
    center_count = max(2, int(round(center_width / center_line_spacing)) - 1)
    quarter_spokes = spokes // 4
    desired_center_half_odd = quarter_spokes % 2 == 1

    if center_count % 2:
        center_count += 1
    if (center_count // 2) % 2 != desired_center_half_odd:
        center_count += 2

    center_count_divisor = center_count + 1

    center_xs = [
        center_start + ((center_width * (i+1)) / (center_count_divisor))
        for i in range(0, center_count)
    ]

    center_left_xs = center_xs[:center_count // 2]
    center_right_xs = center_xs[center_count // 2:]

    def center_run(x, y):
        edge = 'top' if y > 0 else 'bottom'
        max_center_length = None if max_spoke_length is None else max_spoke_length + hub_radius
        return {
            'kind': 'center',
            'edge': edge,
            'edge_point': (x, y),
            'perimeter_point': (x, y),
            'start': (x, 0.0),
            'end': clipped_endpoint((x, 0.0), (x, y), max_center_length),
        }

    part_specs = [
        (
            'top-left',
            list(reversed(spoke_sets['left-top']))
            + [center_run(x, height / 2.0) for x in center_left_xs],
        ),
        (
            'top-right',
            [center_run(x, height / 2.0) for x in center_right_xs]
            + list(reversed(spoke_sets['right-top'])),
        ),
        (
            'bottom-right',
            list(reversed(spoke_sets['right-bottom']))
            + [center_run(x, -height / 2.0) for x in reversed(center_right_xs)],
        ),
        (
            'bottom-left',
            [center_run(x, -height / 2.0) for x in reversed(center_left_xs)]
            + list(reversed(spoke_sets['left-bottom'])),
        ),
    ]

    all_runs = []
    for _part_name, runs in part_specs:
        all_runs.extend(runs)

    print_perimeter_crossings({
        edge: [
            edge_crossing_position(edge, run['perimeter_point'], width, height)
            for run in all_runs
            if run['edge'] == edge
        ]
        for edge in ('top', 'right', 'bottom', 'left')
    })

    points = []
    for part_index, (part_name, runs) in enumerate(part_specs):
        points.extend(split_dual_radial_part(
            part_name,
            runs,
            led_distance,
            section_leds,
            source_modes,
            part_index * 2,
            width,
            height,
        ))

    return points


def layout_stats(points, section_leds=None):
    active = sum(1 for point in points if point[3] != -1 and point[3] != 4)
    inactive = len(points) - active
    padding = sum(1 for point in points if point[3] == -1)
    connector = inactive - padding
    stats = {
        'total': len(points),
        'active': active,
        'inactive': inactive,
        'connector': connector,
        'padding': padding,
    }

    if section_leds:
        sections = [
            points[start:start + section_leds]
            for start in range(0, len(points), section_leds)
        ]
        used_per_section = [
            sum(1 for point in section if point[3] != -1 or point[:3] != (0.0, 0.0, 0))
            for section in sections
        ]
        active_per_section = [
            sum(1 for point in section if point[3] != -1)
            for section in sections
        ]
        inactive_per_section = [
            len(section) - active_count
            for section, active_count in zip(sections, active_per_section)
        ]

        stats.update({
            'sections': len(sections),
            'section_leds': section_leds,
            'max_used_per_section': max(used_per_section) if used_per_section else 0,
            'max_active_per_section': max(active_per_section) if active_per_section else 0,
            'max_inactive_per_section': max(inactive_per_section) if inactive_per_section else 0,
        })

    return stats


def print_layout_stats(layout_type, points, section_leds=None):
    stats = layout_stats(points, section_leds)

    print('Layout type: %s' % layout_type, file=sys.stderr)
    print('Total LEDs: %d' % stats['total'], file=sys.stderr)
    print('Active LEDs: %d' % stats['active'], file=sys.stderr)
    print('Inactive LEDs: %d' % stats['inactive'], file=sys.stderr)
    print('Inactive connector LEDs: %d' % stats['connector'], file=sys.stderr)
    print('Inactive padding LEDs: %d' % stats['padding'], file=sys.stderr)

    if section_leds:
        print('Sections: %d' % stats['sections'], file=sys.stderr)
        print('Section slots: %d' % stats['section_leds'], file=sys.stderr)
        print('Max used LEDs per section: %d' % stats['max_used_per_section'], file=sys.stderr)
        print('Max active LEDs per section: %d' % stats['max_active_per_section'], file=sys.stderr)
        print('Max inactive LEDs per section: %d' % stats['max_inactive_per_section'], file=sys.stderr)


def parse_args():
    parser = argparse.ArgumentParser(description='Layout generator')
    parser.add_argument('type', choices=['square', 'radial', 'dual-radial'], help='Layout type to generate')
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
    radial.add_argument('--center-spacing', help='Distance between circle centers for dual-radial layouts', type=float)
    radial.add_argument('--max-spoke-length', help='Maximum LED-bearing run length in meters before clipping', type=float)
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

    if args.type == 'dual-radial':
        missing = [
            name
            for name in ('width', 'height', 'led_distance', 'hub_radius', 'spokes', 'center_spacing')
            if getattr(args, name) is None
        ]
        if missing:
            parser.error('dual-radial layout requires %s' % ', '.join('--' + name.replace('_', '-') for name in missing))

    return args


def main():
    args = parse_args()

    try:
        if args.type == 'square':
            points = generate_square(args.columns, args.rows, args.source_modes)
        elif args.type == 'radial':
            points = generate_radial(
                args.width,
                args.height,
                args.led_distance,
                args.hub_radius,
                args.spokes,
                args.section_leds,
                args.source_modes,
                max_spoke_length=args.max_spoke_length,
            )
        else:
            points = generate_dual_radial(
                args.width,
                args.height,
                args.led_distance,
                args.hub_radius,
                args.spokes,
                args.center_spacing,
                args.section_leds,
                args.source_modes,
                max_spoke_length=args.max_spoke_length,
            )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print_layout_stats(args.type, points, args.section_leds if args.type != 'square' else None)
    print(json.dumps(points))
    return 0


if __name__ == '__main__':
    sys.exit(main())
