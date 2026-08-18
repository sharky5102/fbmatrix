import ledlayout


MAX_LEDS_PER_STRING = 2000
MAX_STRINGS = 14


def output_mode(displaytype, layout=None):
    if displaytype == 'ws2811':
        if layout is None:
            raise RuntimeError('WS2811 display requires a layout argument')
        strings = ledlayout.require_xyzc_string_layout(
            layout, MAX_LEDS_PER_STRING, MAX_STRINGS)
        height = max((len(string) for string in strings), default=0)
        if height == 0:
            raise RuntimeError('WS2811 layout must contain at least one LED')
        return 840, height, 27000, 1, 1, 48
    return 4096, 194, 50000, 0, 0, 0


def output_stats(displaytype, mode, layout=None):
    width, height, clock, vfp, vsync, vbp = mode
    fps = clock * 1000 / (width * (height + vfp + vsync + vbp))
    if displaytype == 'ws2811':
        strings = ledlayout.require_xyzc_string_layout(
            layout, MAX_LEDS_PER_STRING, MAX_STRINGS)
        active = sum(
            source_mode != -1
            for string in strings
            for _x, _y, _z, source_mode in string)
        inactive = sum(len(string) for string in strings) - active
        return (
            'FBMatrix: %d strings, %d active LEDs, %d inactive LEDs, '
            '%dx%d, %.2f FPS' %
            (len(strings), active, inactive, width, height, fps))
    return 'FBMatrix: HUB75, %dx%d, %.2f FPS' % (width, height, fps)
