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


def require_xyzc_string_layout(layout, max_string_length=500, max_strings=14):
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
