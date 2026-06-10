import json
from json import JSONDecodeError

import fbmatrix


def add_args(parser):
    parser.add_argument('--display', default='hub75e', choices=['hub75e', 'ws2811'], help='Output display type')
    parser.add_argument('--supersample', type=float, default=3, help='Texture LOD used for output pixel sampling')
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


def load_layout(filename):
    last_error = None

    for encoding in ('utf-8-sig', 'utf-16'):
        try:
            with open(filename, 'rt', encoding=encoding) as f:
                return json.load(f)
        except (UnicodeDecodeError, JSONDecodeError) as e:
            last_error = e

    raise RuntimeError('Could not read layout JSON from %s: %s' % (filename, last_error))


def renderer_from_args(args):
    layout = None

    if args.display == 'ws2811' or args.emulate:
        layout = load_layout(args.layout)

    return fbmatrix.renderer(
        emulate=args.emulate,
        preview=args.preview,
        raw=args.raw,
        display=args.display,
        rows=args.rows,
        columns=args.columns,
        supersample=args.supersample,
        order=args.order,
        oe=args.oe,
        extract=args.extract,
        layout=layout,
    )
