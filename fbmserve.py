#!/usr/bin/env python3
import argparse
import dataclasses
import json
import mimetypes
import os
import queue
import random
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import common
import ndi
import led_effect


def get_shader_effect():
    # shader_effect imports OpenGL, so load it only after command-line backend
    # selection has configured PyOpenGL.
    import shader_effect
    return shader_effect


@dataclasses.dataclass(init=False)
class AppState:
    # Fields are durable by default. Runtime-only fields must opt out, making a
    # newly added setting automatically participate in serialization.
    effect: str
    hue: float
    brightness: float
    autoplay: bool
    autoplay_interval: float
    autoplay_effects: list
    input_mode: str
    ndi_source: str | None
    led_effect: str
    supersample: float
    ndi_status: dict = dataclasses.field(metadata={'persist': False})
    error: str | None = dataclasses.field(metadata={'persist': False})
    state_file: object = dataclasses.field(
        metadata={'persist': False, 'snapshot': False})
    lock: object = dataclasses.field(
        metadata={'persist': False, 'snapshot': False})

    def __init__(
        self,
        effect,
        hue=0.0,
        brightness=1.0,
        autoplay=False,
        autoplay_interval=30.0,
        autoplay_effects=None,
        input_mode='effect',
        ndi_source=None,
        ndi_status=None,
        led_effect_id='default',
        supersample=3.0,
        state_file=None,
        led_effect=None,
    ):
        self.lock = threading.Lock()
        self.effect = effect
        self.hue = hue
        self.brightness = brightness
        self.autoplay = autoplay
        self.autoplay_interval = autoplay_interval
        self.autoplay_effects = autoplay_effects or []
        self.input_mode = input_mode
        self.ndi_source = ndi_source
        self.ndi_status = ndi_status or {}
        self.led_effect = led_effect_id if led_effect is None else led_effect
        self.supersample = supersample
        self.error = None
        self.state_file = state_file
        if self.state_file is not None:
            self._persist()

    def snapshot(self):
        with self.lock:
            return {
                item.name: self._copy_collection(getattr(self, item.name))
                for item in dataclasses.fields(self)
                if item.metadata.get('snapshot', True)
            }

    @classmethod
    def persisted_keys(cls):
        return tuple(item.name for item in dataclasses.fields(cls)
                     if item.metadata.get('persist', True))

    @staticmethod
    def _copy_collection(value):
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return dict(value)
        return value

    def update(self, **values):
        with self.lock:
            persist = self.state_file is not None and any(
                key in self.persisted_keys() and getattr(self, key) != value
                for key, value in values.items())
            for key, value in values.items():
                setattr(self, key, value)
            if persist:
                self._persist_locked()

    def _persist(self):
        with self.lock:
            self._persist_locked()

    def _persist_locked(self):
        payload = {
            key: self._copy_collection(getattr(self, key))
            for key in self.persisted_keys()
        }
        directory = os.path.dirname(os.path.abspath(self.state_file))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=directory,
                    prefix='.fbmstate-', delete=False) as f:
                temporary = f.name
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.state_file)
        except OSError as e:
            print('Unable to save state to %s: %s' %
                  (self.state_file, e), file=sys.stderr)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


class InputRenderer:
    def __init__(self, effects_dir, effects, width, height, state, commands,
                 ndi_runtime=None, matrix=None, led_effects_dir='led_effects'):
        self.effects_dir = effects_dir
        self.effects = effects
        self.width = width
        self.height = height
        self.state = state
        self.commands = commands
        self.started = time.monotonic()
        self.next_autoplay = time.monotonic()
        self.current_effect = None
        self.failed_effect = None
        self.quad = None
        self.ndi_runtime = ndi_runtime
        self.ndi_receiver = None
        self.current_ndi_source = None
        self.ndi_quad = None
        self.next_ndi_status = 0.0
        self.matrix = matrix
        self.led_effects_dir = led_effects_dir
        self.current_led_effect = None
        self.failed_led_effect = None
        self.schedule_autoplay()

    def render(self):
        self.apply_commands()
        self.apply_autoplay()
        snapshot = self.state.snapshot()

        if self.matrix is not None:
            self.matrix.set_supersample(snapshot['supersample'])

        if (self.has_ledbuffer() and
                snapshot['led_effect'] != self.current_led_effect and
                snapshot['led_effect'] != self.failed_led_effect):
            try:
                self.load_led_effect(snapshot['led_effect'])
            except (RuntimeError, FileNotFoundError) as e:
                self.failed_led_effect = snapshot['led_effect']
                self.state.update(error=str(e))

        if self.has_ledbuffer():
            now = time.monotonic() - self.started
            self.matrix.ledbuffer.set_params(
                now, snapshot['hue'], snapshot['brightness'])

        if snapshot['input_mode'] == 'ndi':
            self.render_ndi(snapshot)
            return

        if snapshot['effect'] != self.current_effect and snapshot['effect'] != self.failed_effect:
            try:
                self.load_effect(snapshot['effect'])
            except RuntimeError as e:
                self.failed_effect = snapshot['effect']
                self.state.update(error=str(e))

        if self.quad is None:
            return

        now = time.monotonic() - self.started
        self.quad.set_params(now, snapshot['hue'])
        self.quad.render()

    def render_ndi(self, snapshot):
        source = snapshot['ndi_source']
        if not source:
            self.state.update(error='Select an NDI source')
            return
        if self.ndi_runtime is None:
            self.state.update(error='NDI is unavailable; set %s to libndi.so' % ndi.LIBRARY_ENV)
            return
        if source != self.current_ndi_source:
            self.close_receiver()
            try:
                self.ndi_receiver = ndi.Receiver(self.ndi_runtime, source)
                if self.ndi_quad is None:
                    import assembly.yuv
                    self.ndi_quad = assembly.yuv.yuv422()
                self.current_ndi_source = source
                self.next_ndi_status = 0.0
                self.state.update(error=None, ndi_status={})
            except RuntimeError as e:
                self.state.update(error=str(e))
                return
        try:
            self.ndi_receiver.receive_video(self.ndi_quad.setUYVY, timeout_ms=2)
            self.ndi_quad.render()
            now = time.monotonic()
            if now >= self.next_ndi_status:
                self.state.update(ndi_status=self.ndi_receiver.stats())
                self.next_ndi_status = now + 1.0
        except RuntimeError as e:
            self.state.update(error=str(e))

    def close_receiver(self):
        if self.ndi_receiver is not None:
            self.ndi_receiver.close()
        self.ndi_receiver = None
        self.current_ndi_source = None
        self.state.update(ndi_status={})

    def close(self):
        self.close_receiver()

    def apply_commands(self):
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return

            if command['type'] == 'set_state':
                self.state.update(**command['values'])
                if any(key in command['values'] for key in (
                    'effect',
                    'autoplay',
                    'autoplay_interval',
                    'autoplay_effects',
                )):
                    self.schedule_autoplay()
                if command['values'].get('input_mode') == 'effect':
                    self.close_receiver()
                    self.state.update(error=None)
                if 'effect' in command['values'] and command['values']['effect'] != self.failed_effect:
                    self.failed_effect = None
                if ('led_effect' in command['values'] and
                        command['values']['led_effect'] != self.failed_led_effect):
                    self.failed_led_effect = None

    def apply_autoplay(self):
        snapshot = self.state.snapshot()
        if not snapshot['autoplay']:
            return
        if snapshot['input_mode'] != 'effect':
            return

        now = time.monotonic()
        if now < self.next_autoplay:
            return

        effect_ids = [item['id'] for item in self.effects]
        if not effect_ids:
            return

        selected = set(snapshot['autoplay_effects'])
        autoplay_effect_ids = [effect_id for effect_id in effect_ids if effect_id in selected]
        if not autoplay_effect_ids:
            self.schedule_autoplay(now=now)
            return

        choices = [effect_id for effect_id in autoplay_effect_ids if effect_id != snapshot['effect']]
        if choices:
            effect = random.choice(choices)
        else:
            effect = autoplay_effect_ids[0]

        self.state.update(effect=effect, hue=random.random())
        self.failed_effect = None
        self.schedule_autoplay(now=now)

    def schedule_autoplay(self, now=None):
        snapshot = self.state.snapshot()
        now = time.monotonic() if now is None else now
        self.next_autoplay = now + snapshot['autoplay_interval']

    def load_effect(self, effect_id):
        shader_effect = get_shader_effect()
        source = shader_effect.load_effect_source(self.effects_dir, effect_id)
        self.quad = shader_effect.ShaderEffect(source, self.width, self.height)
        self.current_effect = effect_id
        self.failed_effect = None
        self.state.update(error=None)

    def load_led_effect(self, effect_id):
        source = led_effect.load_effect_source(
            self.led_effects_dir, effect_id)
        self.matrix.ledbuffer.set_effect_source(source)
        self.current_led_effect = effect_id
        self.failed_led_effect = None
        self.state.update(error=None)

    def has_ledbuffer(self):
        return self.matrix is not None and hasattr(self.matrix, 'ledbuffer')


class RequestHandler(BaseHTTPRequestHandler):
    server_version = 'fbmserve/0.1'

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/state':
            self.write_json(self.server.app_state.snapshot())
            return

        if parsed.path == '/api/effects':
            self.write_json(get_shader_effect().discover_effects(
                self.server.effects_dir))
            return

        if parsed.path == '/api/led-effects':
            self.write_json(led_effect.discover_effects(
                self.server.led_effects_dir))
            return

        if parsed.path == '/api/ndi/sources':
            discovery = self.server.ndi_discovery
            self.write_json({
                'available': discovery is not None,
                'sources': discovery.sources() if discovery is not None else [],
                'error': self.server.ndi_error,
            })
            return

        if parsed.path.startswith('/api/effects/') and parsed.path.endswith('/source'):
            self.write_effect_source(parsed.path)
            return

        if (parsed.path.startswith('/api/led-effects/') and
                parsed.path.endswith('/source')):
            self.write_led_effect_source(parsed.path)
            return

        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != '/api/state':
            self.send_error(404)
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
            values = self.normalize_state(payload)
        except (ValueError, json.JSONDecodeError) as e:
            self.write_json({'error': str(e)}, status=400)
            return

        self.server.commands.put({'type': 'set_state', 'values': values})
        self.server.app_state.update(**values)
        self.write_json(self.server.app_state.snapshot())

    def normalize_state(self, payload):
        values = {}

        if 'effect' in payload:
            effect = str(payload['effect'])
            available = {item['id'] for item in get_shader_effect().discover_effects(
                self.server.effects_dir)}
            if effect not in available:
                raise ValueError('Unknown effect')
            values['effect'] = effect

        if 'led_effect' in payload:
            effect = str(payload['led_effect'])
            available = {item['id'] for item in led_effect.discover_effects(
                self.server.led_effects_dir)}
            if effect not in available:
                raise ValueError('Unknown LED effect')
            values['led_effect'] = effect

        if 'input_mode' in payload:
            mode = str(payload['input_mode'])
            if mode not in ('effect', 'ndi'):
                raise ValueError('Unknown input mode')
            values['input_mode'] = mode

        if 'ndi_source' in payload:
            source = payload['ndi_source']
            values['ndi_source'] = None if source is None else str(source)

        if 'hue' in payload:
            values['hue'] = clamp(float(payload['hue']), 0.0, 1.0)

        if 'brightness' in payload:
            values['brightness'] = clamp(float(payload['brightness']), 0.0, 1.0)

        if 'supersample' in payload:
            values['supersample'] = clamp(float(payload['supersample']), 0.0, 16.0)

        if 'autoplay' in payload:
            values['autoplay'] = parse_bool(payload['autoplay'])

        if 'autoplay_interval' in payload:
            values['autoplay_interval'] = clamp(float(payload['autoplay_interval']), 1.0, 3600.0)

        if 'autoplay_effects' in payload:
            if not isinstance(payload['autoplay_effects'], list):
                raise ValueError('Expected autoplay_effects list')

            available = {item['id'] for item in get_shader_effect().discover_effects(
                self.server.effects_dir)}
            autoplay_effects = []
            for effect in payload['autoplay_effects']:
                effect = str(effect)
                if effect not in available:
                    raise ValueError('Unknown autoplay effect')
                if effect not in autoplay_effects:
                    autoplay_effects.append(effect)

            values['autoplay_effects'] = autoplay_effects

        return values

    def serve_static(self, request_path):
        if request_path == '/':
            request_path = '/index.html'

        relative = unquote(request_path).lstrip('/')
        web_dir = os.path.abspath(self.server.web_dir)
        filename = os.path.abspath(os.path.join(web_dir, relative))

        if filename != web_dir and not filename.startswith(web_dir + os.sep):
            self.send_error(403)
            return

        if not os.path.isfile(filename):
            self.send_error(404)
            return

        mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        with open(filename, 'rb') as f:
            data = f.read()

        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def write_effect_source(self, request_path):
        parts = request_path.strip('/').split('/')
        if len(parts) != 4:
            self.send_error(404)
            return

        effect_id = parts[2]
        try:
            source = get_shader_effect().load_effect_source(
                self.server.effects_dir, effect_id)
        except (ValueError, FileNotFoundError):
            self.send_error(404)
            return

        data = source.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def write_led_effect_source(self, request_path):
        parts = request_path.strip('/').split('/')
        if len(parts) != 4:
            self.send_error(404)
            return
        try:
            source = led_effect.load_effect_source(
                self.server.led_effects_dir, parts[2])
        except (ValueError, FileNotFoundError):
            self.send_error(404)
            return
        data = source.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def write_json(self, payload, status=200):
        data = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt % args))


def clamp(value, low, high):
    return max(low, min(high, value))


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ('1', 'true', 'yes', 'on'):
            return True
        if value.lower() in ('0', 'false', 'no', 'off'):
            return False
    raise ValueError('Expected boolean value')


def load_state_file(filename, effect_ids, led_effect_ids):
    """Load and validate durable state, returning None for any bad snapshot."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            values = json.load(f)
        if not isinstance(values, dict):
            raise ValueError('expected an object')
        if set(values) != set(AppState.persisted_keys()):
            raise ValueError('unexpected or missing fields')
        if values['effect'] not in effect_ids:
            raise ValueError('unknown effect')
        if values['led_effect'] not in led_effect_ids:
            raise ValueError('unknown LED effect')
        if values['input_mode'] not in ('effect', 'ndi'):
            raise ValueError('unknown input mode')
        if values['ndi_source'] is not None and not isinstance(values['ndi_source'], str):
            raise ValueError('invalid NDI source')
        if not isinstance(values['autoplay_effects'], list) or any(
                not isinstance(item, str) or item not in effect_ids
                for item in values['autoplay_effects']):
            raise ValueError('invalid autoplay effects')
        if not isinstance(values['autoplay'], bool):
            raise ValueError('invalid autoplay value')
        for key, low, high in (
            ('hue', 0.0, 1.0), ('brightness', 0.0, 1.0),
            ('autoplay_interval', 1.0, 3600.0), ('supersample', 0.0, 16.0),
        ):
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('invalid %s' % key)
            if not low <= value <= high:
                raise ValueError('%s out of range' % key)
        return values
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print('Ignoring invalid state file %s: %s' % (filename, e),
              file=sys.stderr)
        return None


def create_server(host, port, web_dir, effects_dir, state, commands,
                  ndi_discovery=None, ndi_error=None,
                  led_effects_dir='led_effects'):
    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.web_dir = web_dir
    server.effects_dir = effects_dir
    server.led_effects_dir = led_effects_dir
    server.app_state = state
    server.commands = commands
    server.ndi_discovery = ndi_discovery
    server.ndi_error = ndi_error
    return server


def main():
    parser = argparse.ArgumentParser(description='Framebuffer RGB matrix shader server')
    common.add_args(parser)
    parser.set_defaults(source_scale=4)
    parser.add_argument('--host', default='0.0.0.0', help='HTTP server bind address')
    parser.add_argument('--port', type=int, default=8080, help='HTTP server port')
    parser.add_argument('--effects-dir', default='effects', help='Directory containing .frag effects')
    parser.add_argument('--led-effects-dir', default='led_effects', help='Directory containing per-emitter .frag effects')
    parser.add_argument('--web-dir', default='web', help='Directory containing the web UI')
    parser.add_argument('--effect', default=None, help='Initial effect id')
    parser.add_argument('--hue', type=float, default=0.0, help='Initial hue value from 0.0 to 1.0')
    parser.add_argument('--brightness', type=float, default=1.0, help='Initial brightness from 0.0 to 1.0')
    parser.add_argument('--autoplay', action='store_true', help='Randomly switch effects on the server')
    parser.add_argument('--autoplay-interval', type=float, default=30.0, help='Seconds between autoplay effect switches')
    parser.add_argument('--state-file', default=None,
                        help='Persist server state to this JSON file')
    args = parser.parse_args()
    matrix = common.renderer_from_args(args)

    effects_dir = os.path.abspath(args.effects_dir)
    led_effects_dir = os.path.abspath(args.led_effects_dir)
    web_dir = os.path.abspath(args.web_dir)
    effects = get_shader_effect().discover_effects(effects_dir)
    if not effects:
        raise RuntimeError('No effects found in %s' % effects_dir)

    effect = args.effect or effects[0]['id']
    if effect not in {item['id'] for item in effects}:
        raise RuntimeError('Unknown effect: %s' % effect)
    initial_state = {
        'effect': effect,
        'hue': clamp(args.hue, 0.0, 1.0),
        'brightness': clamp(args.brightness, 0.0, 1.0),
        'autoplay': args.autoplay,
        'autoplay_interval': clamp(args.autoplay_interval, 1.0, 3600.0),
        'autoplay_effects': [item['id'] for item in effects],
        'input_mode': 'effect',
        'ndi_source': None,
        'led_effect': 'default',
        'supersample': clamp(args.supersample, 0.0, 16.0),
    }
    if args.state_file is not None:
        saved = load_state_file(
            args.state_file,
            {item['id'] for item in effects},
            {item['id'] for item in led_effect.discover_effects(led_effects_dir)})
        if saved is not None:
            initial_state.update(saved)
    state = AppState(**initial_state, state_file=args.state_file)
    commands = queue.Queue()

    ndi_runtime = None
    ndi_discovery = None
    ndi_error = None
    if os.environ.get(ndi.LIBRARY_ENV):
        try:
            ndi_runtime = ndi.Runtime()
            ndi_discovery = ndi.Discovery(ndi_runtime)
        except (ndi.NDIUnavailable, RuntimeError) as e:
            raise RuntimeError('Fatal: NDI initialization failed: %s' % e) from e

    server = create_server(args.host, args.port, web_dir, effects_dir, state, commands,
                           ndi_discovery, ndi_error, led_effects_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print('fbmserve listening on http://%s:%d/' % (args.host, args.port))

    renderer = InputRenderer(effects_dir, effects, matrix.source_columns, matrix.source_rows,
                             state, commands, ndi_runtime, matrix,
                             led_effects_dir)
    try:
        matrix.run(renderer.render)
    finally:
        renderer.close()
        server.shutdown()
        if ndi_discovery is not None:
            ndi_discovery.close()


if __name__ == '__main__':
    main()
