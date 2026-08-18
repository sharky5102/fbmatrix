import math
import statistics


def require_xyzc_layout(layout):
    if not layout:
        raise RuntimeError('Layout must contain at least one LED')

    normalized = []

    for i, lamp in enumerate(layout):
        if len(lamp) != 4:
            raise RuntimeError('Layout entry %d must be [x, y, z, c]' % i)

        x, y, z, c = lamp

        if isinstance(c, bool) or int(c) != c:
            raise RuntimeError('Layout entry %d source mode must be an integer' % i)

        if int(c) < -1 or int(c) > 4:
            raise RuntimeError('Layout entry %d source mode must be -1, 0, 1, 2, 3 or 4' % i)

        normalized.append((float(x), float(y), float(z), int(c)))

    return normalized


def require_xyzc_string_layout(layout, max_string_length=2000, max_strings=14):
    if not layout:
        raise RuntimeError('Layout must contain at least one string')
    if len(layout) > max_strings:
        raise RuntimeError(
            'Layout contains %d strings; at most %d are supported' %
            (len(layout), max_strings))

    normalized = []
    for string_index, string in enumerate(layout):
        if len(string) > max_string_length:
            raise RuntimeError(
                'Layout string %d contains %d LEDs; at most %d are supported' %
                (string_index, len(string), max_string_length))
        try:
            normalized.append(require_xyzc_layout(string) if string else [])
        except (TypeError, ValueError, RuntimeError) as e:
            raise RuntimeError('Layout string %d: %s' % (string_index, e)) from e

    return normalized


def flatten_string_layout(layout):
    return [lamp for string in layout for lamp in string]


def active_xy_bounds(layout):
    """Return physical XY bounds for LEDs which can display source content."""
    if (layout and len(layout[0]) == 4 and
            not isinstance(layout[0][0], (list, tuple))):
        lamps = require_xyzc_layout(layout)
    else:
        lamps = flatten_string_layout(require_xyzc_string_layout(layout))
    active = [lamp for lamp in lamps if lamp[3] != -1]
    points = active or lamps
    return (
        min(lamp[0] for lamp in points),
        max(lamp[0] for lamp in points),
        min(lamp[1] for lamp in points),
        max(lamp[1] for lamp in points),
    )


def normalized_xy(x, y, bounds):
    """Map physical layout coordinates to source-texture UV coordinates."""
    min_x, max_x, min_y, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    u = (x - min_x) / width if width else 0.5
    # Layout Y points up, while uploaded source images use top-down rows.
    v = (max_y - y) / height if height else 0.5
    return u, v


def typical_active_spacing(layout):
    """Estimate XY spacing from consecutive active LEDs in each string."""
    strings = require_xyzc_string_layout(layout)
    distances = []
    active_count = 0
    for string in strings:
        previous = None
        for lamp in string:
            if lamp[3] == -1:
                previous = None
                continue
            active_count += 1
            if previous is not None:
                distance = math.hypot(
                    lamp[0] - previous[0], lamp[1] - previous[1])
                if distance > 0:
                    distances.append(distance)
            previous = lamp

    if distances:
        return statistics.median(distances)

    min_x, max_x, min_y, max_y = active_xy_bounds(strings)
    extent = max(max_x - min_x, max_y - min_y)
    if active_count > 1 and extent:
        return extent / (active_count - 1)
    return 1.0
