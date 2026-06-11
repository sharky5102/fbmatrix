import json
from json import JSONDecodeError

import fbmatrix
import ledlayout


def add_args(parser):
    parser.add_argument('--display', default='hub75e', choices=['hub75e', 'ws2811'], help='Output display type')
    parser.add_argument('--supersample', type=float, default=3, help='Mip level used when sampling the source framebuffer for LED output')
    parser.add_argument('--source-scale', type=float, default=1, help='Scale factor for the source framebuffer resolution')
    parser.add_argument('--source-columns', type=int, default=None, help='Source framebuffer columns. Overrides --source-scale width')
    parser.add_argument('--source-rows', type=int, default=None, help='Source framebuffer rows. Overrides --source-scale height')
    parser.add_argument('--emulate', action='store_true', help='Render display emulation')
    parser.add_argument('--preview', action='store_true', help='Preview the source framebuffer')
    parser.add_argument('--raw', action='store_true', help='Use a windowed raw framebuffer')

    hub75 = parser.add_argument_group('HUB75 options')
    hub75.add_argument('--columns', type=int, default=32, help='HUB75 matrix columns')
    hub75.add_argument('--rows', type=int, default=32, help='HUB75 matrix rows')
    hub75.add_argument('--order', default='line-first', choices=['line-first', 'field-first'], help='HUB75 scan output order')
    hub75.add_argument('--oe', default='normal', choices=['normal', 'inverted'], help='HUB75 output-enable polarity')
    hub75.add_argument('--extract', default='bcm', help='HUB75 bitplane extraction mode')

    ws2811 = parser.add_argument_group('WS2811 options')
    ws2811.add_argument('--layout', default='layout.json', help='JSON file containing WS2811 LED positions')


def load_layout(filename, preserve_source_modes=False):
    last_error = None

    for encoding in ('utf-8-sig', 'utf-16'):
        try:
            with open(filename, 'rt', encoding=encoding) as f:
                layout = ledlayout.require_xyzc_layout(json.load(f))
                if preserve_source_modes:
                    return layout

                return [(x, y, z, 0) for x, y, z, source_mode in layout]
        except (UnicodeDecodeError, JSONDecodeError) as e:
            last_error = e

    raise RuntimeError('Could not read layout JSON from %s: %s' % (filename, last_error))


def renderer_from_args(args, preserve_source_modes=False):
    layout = None

    if args.display == 'ws2811' or args.emulate:
        layout = load_layout(args.layout, preserve_source_modes=preserve_source_modes)

    if args.source_scale <= 0:
        raise RuntimeError('--source-scale must be greater than zero')
    if args.source_columns is not None and args.source_columns <= 0:
        raise RuntimeError('--source-columns must be greater than zero')
    if args.source_rows is not None and args.source_rows <= 0:
        raise RuntimeError('--source-rows must be greater than zero')

    source_columns = args.source_columns or max(1, int(args.columns * args.source_scale))
    source_rows = args.source_rows or max(1, int(args.rows * args.source_scale))

    return fbmatrix.renderer(
        emulate=args.emulate,
        preview=args.preview,
        raw=args.raw,
        display=args.display,
        rows=args.rows,
        columns=args.columns,
        source_rows=source_rows,
        source_columns=source_columns,
        supersample=args.supersample,
        order=args.order,
        oe=args.oe,
        extract=args.extract,
        layout=layout,
    )
