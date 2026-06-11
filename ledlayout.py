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

        if int(c) < -1 or int(c) > 3:
            raise RuntimeError('Layout entry %d source mode must be -1, 0, 1, 2 or 3' % i)

        normalized.append((float(x), float(y), float(z), int(c)))

    return normalized
