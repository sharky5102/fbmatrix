#!/usr/bin/env python3
import argparse
import dataclasses
import json
import logging
import math
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
if sys.platform != 'win32':
    from dmx import DMXReceiver
else:
    DMXReceiver = None
import ndi
import artnet
import matrix_buffer
from channel_mapping import ChannelMapping
import sacn_receiver
import led_effect


DMX_CHANNELS = 12


def fsync_directory(directory):
    # Windows cannot open directories for fsync; the file itself is still synced.
    if not hasattr(os, 'O_DIRECTORY'):
        return
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def get_shader_effect():
    # shader_effect imports OpenGL, so load it only after command-line backend
    # selection has configured PyOpenGL.
    import shader_effect
    return shader_effect


def validate_matrix_config(size, start_universe, channels=510, start_address=1, protocol='artnet'):
    if protocol not in ('artnet', 'sacn'):
        raise ValueError('Unknown matrix protocol')
    count = matrix_buffer.channel_count(size)
    module = sacn_receiver if protocol == 'sacn' else artnet
    return module.validate_config(count, start_universe, channels, start_address)


def matrix_channel_mapping(buffer, start_universe, channels, start_address, protocol):
    validate_matrix_config(buffer.size, start_universe, channels, start_address, protocol)
    return ChannelMapping(buffer.channel_count, channels, start_universe,
                          start_address, sink=buffer)


def validate_control_config(protocol, artnet_config, sacn_config, start_address):
    artnet_port = validate_matrix_protocol_config(artnet_config, 'port_address', 'Art-Net')
    sacn_universe = validate_matrix_protocol_config(sacn_config, 'universe', 'sACN')
    # The 12-channel DMX profile has to fit inside a single universe.
    if protocol not in ('artnet', 'sacn'):
        raise ValueError('Unknown Network Control protocol')
    if protocol == 'artnet':
        artnet.validate_config(DMX_CHANNELS, artnet_port, 512, start_address)
    else:
        sacn_receiver.validate_config(DMX_CHANNELS, sacn_universe, 512, start_address)


def validate_matrix_protocol_config(config, key, label):
    if not isinstance(config, dict) or set(config) != {key}:
        raise ValueError('Invalid %s Network Matrix settings' % label)
    return config[key]


@dataclasses.dataclass(init=False)
class AppState:
    # Fields are durable by default. Runtime-only fields must opt out, making a
    # newly added setting automatically participate in serialization.
    effect: str
    color1: list
    color2: list
    color3: list
    speed: float
    brightness: float
    autoplay: bool
    autoplay_interval: float
    autoplay_effects: list
    input_mode: str
    ndi_source: str | None
    matrix_size: int
    matrix_channels_per_universe: int
    matrix_start_address: int
    matrix_artnet: dict
    matrix_sacn: dict
    matrix_protocol: str
    matrix_status: dict = dataclasses.field(metadata={'persist': False})
    network_control_enabled: bool
    network_control_protocol: str
    network_control_artnet: dict
    network_control_sacn: dict
    network_control_start_address: int
    network_control_hold: float
    network_control_status: dict = dataclasses.field(metadata={'persist': False})
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
        color1=(0.0, 0.0, 1.0),
        color2=(1.0, 1.0, 0.0),
        color3=(1.0, 0.0, 0.0),
        speed=1.0,
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
        matrix_size=16,
        matrix_artnet=None,
        matrix_sacn=None,
        matrix_channels_per_universe=510,
        matrix_start_address=1,
        matrix_protocol='artnet',
        network_control_enabled=False,
        network_control_protocol='artnet',
        network_control_artnet=None,
        network_control_sacn=None,
        network_control_start_address=1,
        network_control_hold=30.0,
    ):
        self.lock = threading.Lock()
        self.effect = effect
        self.color1 = validate_color(color1)
        self.color2 = validate_color(color2)
        self.color3 = validate_color(color3)
        self.speed = speed
        self.brightness = brightness
        self.autoplay = autoplay
        self.autoplay_interval = autoplay_interval
        self.autoplay_effects = autoplay_effects or []
        self.input_mode = input_mode
        self.ndi_source = ndi_source
        if matrix_protocol not in ('artnet', 'sacn'):
            raise ValueError('Unknown Network Matrix protocol')
        matrix_artnet = {'port_address': 0} if matrix_artnet is None else matrix_artnet
        matrix_sacn = {'universe': 1} if matrix_sacn is None else matrix_sacn
        artnet_port = validate_matrix_protocol_config(matrix_artnet, 'port_address', 'Art-Net')
        sacn_universe = validate_matrix_protocol_config(matrix_sacn, 'universe', 'sACN')
        validate_matrix_config(matrix_size, artnet_port, matrix_channels_per_universe, matrix_start_address)
        validate_matrix_config(matrix_size, sacn_universe, matrix_channels_per_universe, matrix_start_address, protocol='sacn')
        self.matrix_protocol = matrix_protocol
        self.matrix_artnet = dict(matrix_artnet)
        self.matrix_sacn = dict(matrix_sacn)
        self.matrix_channels_per_universe = matrix_channels_per_universe
        self.matrix_start_address = matrix_start_address
        self.matrix_size = matrix_size
        self.matrix_status = {}
        network_control_artnet = ({'port_address': 0} if network_control_artnet is None
                                  else network_control_artnet)
        network_control_sacn = ({'universe': 1} if network_control_sacn is None
                                else network_control_sacn)
        validate_control_config(network_control_protocol, network_control_artnet,
                                network_control_sacn, network_control_start_address)
        if not isinstance(network_control_enabled, bool):
            raise ValueError('Network Control enabled must be boolean')
        if (isinstance(network_control_hold, bool) or
                not isinstance(network_control_hold, (int, float)) or
                not math.isfinite(network_control_hold) or network_control_hold < 0):
            raise ValueError('Network Control hold must be a non-negative number')
        self.network_control_enabled = network_control_enabled
        self.network_control_protocol = network_control_protocol
        self.network_control_artnet = dict(network_control_artnet)
        self.network_control_sacn = dict(network_control_sacn)
        self.network_control_start_address = network_control_start_address
        self.network_control_hold = float(network_control_hold)
        self.network_control_status = {}
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
            # fsyncing the file makes its contents durable; fsyncing the
            # directory makes the rename durable as well.  Both are needed to
            # survive power loss without reverting to or losing the snapshot.
            fsync_directory(directory)
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
                 ndi_runtime=None, matrix=None, led_effects_dir='led_effects',
                 dmx_receiver=None, dmx_start=1, dmx_hold=30.0,
                 artnet_poll_broadcast=False, artnet_node_name='fbmserve'):
        self.effects_dir = effects_dir
        self.effects = effects
        self.width = width
        self.height = height
        self.state = state
        self.commands = commands
        self.started = time.monotonic()
        self.effect_time = 0.0
        self.last_effect_tick = self.started
        self.next_autoplay = time.monotonic()
        self.current_effect = None
        self.failed_effect = None
        self.quad = None
        self.ndi_runtime = ndi_runtime
        self.ndi_receiver = None
        self.current_ndi_source = None
        self.ndi_quad = None
        self.network_dmx_receivers = {}
        self.network_buffers = {}
        self.network_mappings = {}
        self.network_config = None
        self.network_buffer = None
        self.network_quad = None
        self.next_network_debug = 0.0
        self.next_ndi_status = 0.0
        self.matrix = matrix
        self.led_effects_dir = led_effects_dir
        self.current_led_effect = None
        self.failed_led_effect = None
        self.dmx_receiver = dmx_receiver
        self.dmx_start = dmx_start
        self.dmx_hold = dmx_hold
        self.artnet_poll_broadcast = artnet_poll_broadcast
        self.artnet_node_name = artnet.validate_node_name(artnet_node_name)
        self.dmx_values = None
        self.last_dmx_frame = None
        self.schedule_autoplay()

    def render(self):
        self.apply_commands()
        self.apply_autoplay()
        snapshot = self.state.snapshot()
        tick = time.monotonic()
        self.apply_dmx(snapshot, tick)
        self.configure_network_inputs(snapshot)
        self.apply_network_dmx(snapshot, tick)
        self.effect_time += (tick - self.last_effect_tick) * snapshot['speed']
        self.last_effect_tick = tick

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
                now, snapshot['brightness'])

        if snapshot['input_mode'] != 'network_matrix':
            self.state.update(matrix_status={})

        if snapshot['input_mode'] == 'network_matrix':
            self.close_ndi_receiver()
            self.render_network_matrix(snapshot)
            return

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

        self.quad.set_params(self.effect_time, snapshot['color1'], snapshot['color2'],
                             snapshot['color3'])
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
            self.close_ndi_receiver()
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

    def render_network_matrix(self, snapshot):
        protocol = snapshot['matrix_protocol']
        start_universe = (snapshot['matrix_sacn']['universe'] if protocol == 'sacn'
                          else snapshot['matrix_artnet']['port_address'])
        config = (protocol, snapshot['matrix_size'], start_universe,
                  snapshot['matrix_channels_per_universe'], snapshot['matrix_start_address'],
                  self.artnet_node_name)
        try:
            if self.network_buffer is None:
                status = self.state.snapshot()['matrix_status']
                status.setdefault('packets', 0)
                status.setdefault('age', None)
                status.setdefault('universes', 0)
                self.state.update(matrix_status=status)
                return
            pixels = self.network_buffer.snapshot()
            receiver = self.network_dmx_receivers[protocol]
            status = receiver.status()
            status.update(receiver.mapping_status(self.network_mappings['matrix']))
            status['universes'] = validate_matrix_config(
                config[1], config[2], config[3], config[4], protocol)
            self.network_quad.setRGB(pixels, config[1], config[1])
            self.network_quad.render()
            network_logger = sacn_receiver.logger if protocol == 'sacn' else artnet.logger
            if network_logger.isEnabledFor(logging.DEBUG) and time.monotonic() >= self.next_network_debug:
                self.next_network_debug = time.monotonic() + 1.0
                network_logger.debug('Rendered RGB buffer %dx%d to framebuffer %dx%d; '
                                     'nonzero=%d/%d peak=%d brightness=%.3f LED effect=%s',
                                     config[1], config[1], self.width, self.height,
                                     sum(value != 0 for value in pixels), len(pixels), max(pixels),
                                     snapshot['brightness'], snapshot['led_effect'])
            self.state.update(matrix_status=status, error=status['error'])
        except (OSError, RuntimeError) as error:
            self.state.update(error='%s: %s' % (protocol.upper(), error))

    def close_network_dmx_receiver(self):
        for receiver in self.network_dmx_receivers.values():
            receiver.close()
        self.network_dmx_receivers.clear()
        self.network_buffers.clear()
        self.network_mappings.clear()
        self.network_config = None
        self.network_buffer = None
        if hasattr(self, 'state'):
            self.state.update(matrix_status={}, network_control_status={})

    def configure_network_inputs(self, snapshot):
        matrix_enabled = snapshot['input_mode'] == 'network_matrix'
        control_enabled = snapshot['network_control_enabled']
        config = (
            matrix_enabled, snapshot['matrix_protocol'], snapshot['matrix_size'],
            snapshot['matrix_artnet']['port_address'], snapshot['matrix_sacn']['universe'],
            snapshot['matrix_channels_per_universe'], snapshot['matrix_start_address'],
            control_enabled, snapshot['network_control_protocol'],
            snapshot['network_control_artnet']['port_address'],
            snapshot['network_control_sacn']['universe'],
            snapshot['network_control_start_address'], self.artnet_node_name)
        if config == self.network_config:
            return
        previous_config = self.network_config
        previous_control = self.network_mappings.get('control')
        for receiver in self.network_dmx_receivers.values():
            receiver.close()
        self.network_dmx_receivers.clear()
        self.network_buffers.clear()
        self.network_mappings.clear()
        self.network_buffer = None
        self.network_config = config
        self.state.update(matrix_status={})
        control_config_unchanged = (
            previous_config is not None and previous_control is not None and
            previous_config[7:12] == config[7:12])
        if not control_enabled or not control_config_unchanged:
            self.state.update(network_control_status={})
        try:
            self._create_network_dmx_receivers(snapshot, matrix_enabled, control_enabled)
        except (OSError, RuntimeError, ValueError) as error:
            for receiver in self.network_dmx_receivers.values():
                receiver.close()
            self.network_dmx_receivers.clear()
            self.network_buffers.clear()
            self.network_mappings.clear()
            self.network_buffer = None
            # A failed bind must be retried on the next render even when settings are unchanged.
            self.network_config = None
            if control_enabled:
                self.state.update(network_control_status={
                    'error': str(error), 'packets': 0, 'age': None,
                    'diagnostics': {}})
            else:
                self.state.update(error=str(error))

    def _create_network_dmx_receivers(self, snapshot, matrix_enabled, control_enabled):
        mappings_by_protocol = {}
        if matrix_enabled:
            protocol = snapshot['matrix_protocol']
            universe = (snapshot['matrix_sacn']['universe'] if protocol == 'sacn'
                        else snapshot['matrix_artnet']['port_address'])
            buffer = matrix_buffer.PixelBuffer(snapshot['matrix_size'])
            mapping = matrix_channel_mapping(buffer, universe,
                snapshot['matrix_channels_per_universe'], snapshot['matrix_start_address'], protocol)
            self.network_buffer = buffer
            self.network_buffers['matrix'] = buffer
            self.network_mappings['matrix'] = mapping
            mappings_by_protocol.setdefault(protocol, []).append(mapping)
        if control_enabled:
            protocol = snapshot['network_control_protocol']
            universe = (snapshot['network_control_sacn']['universe'] if protocol == 'sacn'
                        else snapshot['network_control_artnet']['port_address'])
            buffer = matrix_buffer.ChannelBuffer(DMX_CHANNELS)
            mapping = ChannelMapping(DMX_CHANNELS, 512, universe,
                                     snapshot['network_control_start_address'], sink=buffer)
            self.network_buffers['control'] = buffer
            self.network_mappings['control'] = mapping
            mappings_by_protocol.setdefault(protocol, []).append(mapping)
        for protocol, mappings in mappings_by_protocol.items():
            if protocol == 'sacn':
                receiver = sacn_receiver.Receiver(mappings)
            else:
                description = 'fbmserve Network Control/Matrix'
                receiver = artnet.Receiver(mappings,
                    poll_broadcast=self.artnet_poll_broadcast,
                    node_name=self.artnet_node_name, description=description)
            self.network_dmx_receivers[protocol] = receiver
        if matrix_enabled and self.network_quad is None:
            # Backend selection must precede the first OpenGL import.
            from assembly.network_matrix import NetworkMatrixQuad
            self.network_quad = NetworkMatrixQuad()

    def apply_network_dmx(self, snapshot, now):
        if not snapshot['network_control_enabled']:
            self.state.update(network_control_status={})
            return
        protocol = snapshot['network_control_protocol']
        receiver = self.network_dmx_receivers.get(protocol)
        mapping = self.network_mappings.get('control')
        buffer = self.network_buffers.get('control')
        if receiver is None or mapping is None or buffer is None:
            status = self.state.snapshot()['network_control_status']
            if snapshot['network_control_enabled'] and status.get('error'):
                return
            self.state.update(network_control_status={})
            return
        status = receiver.status()
        status.update(receiver.mapping_status(mapping))
        status['protocol'] = protocol
        status['universe'] = (snapshot['network_control_sacn']['universe'] if protocol == 'sacn'
                              else snapshot['network_control_artnet']['port_address'])
        self.state.update(network_control_status=status)
        if (status['packets'] and status['age'] is not None and
                status['age'] <= snapshot['network_control_hold']):
            frame = bytes((0,)) + buffer.snapshot()
            values = dmx_values(frame, 1, self.effects)
            if values is not None:
                snapshot.update(values)

    def close_ndi_receiver(self):
        if self.ndi_receiver is not None:
            self.ndi_receiver.close()
        self.ndi_receiver = None
        self.current_ndi_source = None
        self.state.update(ndi_status={})

    def close(self):
        self.close_network_dmx_receiver()
        self.close_ndi_receiver()
        if self.dmx_receiver is not None:
            self.dmx_receiver.close()

    def apply_dmx(self, snapshot, now):
        if self.dmx_receiver is None:
            return
        frame = self.dmx_receiver.read_dmx_frame()
        if frame is not None:
            values = dmx_values(frame, self.dmx_start, self.effects)
            if values is not None:
                self.dmx_values = values
                self.last_dmx_frame = now
        if (self.dmx_values is not None and self.last_dmx_frame is not None and
                now - self.last_dmx_frame <= self.dmx_hold):
            snapshot.update(self.dmx_values)

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
                if 'input_mode' in command['values']:
                    self.close_ndi_receiver()
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

        self.state.update(effect=effect)
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
        self.matrix.ledbuffer.set_effect_source(source, effect_id=effect_id)
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
        if not isinstance(payload, dict):
            raise ValueError('Expected an object')
        if 'hue' in payload:
            raise ValueError('Hue has been replaced by color1, color2 and color3')
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
            if mode not in ('effect', 'ndi', 'network_matrix'):
                raise ValueError('Unknown input mode')
            values['input_mode'] = mode

        if 'matrix_protocol' in payload:
            protocol = payload['matrix_protocol']
            if protocol not in ('artnet', 'sacn'):
                raise ValueError('Unknown Network Matrix protocol')
            values['matrix_protocol'] = protocol

        if any(key in payload for key in (
                'matrix_size', 'matrix_channels_per_universe', 'matrix_start_address',
                'matrix_protocol', 'matrix_artnet', 'matrix_sacn')):
            current = self.server.app_state.snapshot()
            protocol = payload.get('matrix_protocol', current['matrix_protocol'])
            size = payload.get('matrix_size', current['matrix_size'])
            artnet_config = payload.get('matrix_artnet', current['matrix_artnet'])
            sacn_config = payload.get('matrix_sacn', current['matrix_sacn'])
            channels = payload.get('matrix_channels_per_universe', current['matrix_channels_per_universe'])
            address = payload.get('matrix_start_address', current['matrix_start_address'])
            artnet_port = validate_matrix_protocol_config(artnet_config, 'port_address', 'Art-Net')
            sacn_universe = validate_matrix_protocol_config(sacn_config, 'universe', 'sACN')
            # Keep both independently saved protocol profiles valid while
            # editing shared matrix dimensions and channel packing.
            validate_matrix_config(size, artnet_port, channels, address)
            validate_matrix_config(size, sacn_universe, channels, address, protocol='sacn')
            values.update(matrix_protocol=protocol, matrix_size=size,
                          matrix_artnet=artnet_config, matrix_sacn=sacn_config,
                          matrix_channels_per_universe=channels, matrix_start_address=address)

        control_keys = ('network_control_enabled', 'network_control_protocol',
                        'network_control_artnet', 'network_control_sacn',
                        'network_control_start_address', 'network_control_hold')
        if any(key in payload for key in control_keys):
            current = self.server.app_state.snapshot()
            enabled = parse_bool(payload.get('network_control_enabled',
                                             current['network_control_enabled']))
            protocol = payload.get('network_control_protocol', current['network_control_protocol'])
            artnet_config = payload.get('network_control_artnet', current['network_control_artnet'])
            sacn_config = payload.get('network_control_sacn', current['network_control_sacn'])
            address = payload.get('network_control_start_address',
                                   current['network_control_start_address'])
            hold = payload.get('network_control_hold', current['network_control_hold'])
            if (isinstance(hold, bool) or not isinstance(hold, (int, float)) or
                    not math.isfinite(hold) or hold < 0 or hold > 3600):
                raise ValueError('Network Control hold must be from 0 to 3600 seconds')
            validate_control_config(protocol, artnet_config, sacn_config, address)
            values.update(network_control_enabled=enabled,
                          network_control_protocol=protocol,
                          network_control_artnet=artnet_config,
                          network_control_sacn=sacn_config,
                          network_control_start_address=address,
                          network_control_hold=float(hold))

        if 'ndi_source' in payload:
            source = payload['ndi_source']
            values['ndi_source'] = None if source is None else str(source)

        for key in ('color1', 'color2', 'color3'):
            if key in payload:
                values[key] = validate_color(payload[key])

        if 'speed' in payload:
            if isinstance(payload['speed'], bool):
                raise ValueError('Speed must be a number')
            try:
                speed = float(payload['speed'])
            except (TypeError, ValueError) as e:
                raise ValueError('Speed must be a number') from e
            if not math.isfinite(speed):
                raise ValueError('Speed must be a finite number')
            values['speed'] = clamp(speed, 0.0, 4.0)

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


def dmx_values(frame, start, effects):
    """Map a zero-start-code DMX frame to fbmserve's 12-channel profile."""
    if not frame or frame[0] != 0:
        return None
    channels = frame[start:start + DMX_CHANNELS]
    if len(channels) != DMX_CHANNELS or not effects:
        return None
    scale = 1.0 / 255.0
    effect_index = channels[1] * len(effects) // 256
    return {
        'brightness': channels[0] * scale,
        'effect': effects[effect_index]['id'],
        'speed': channels[2] * scale * 4.0,
        'color1': [value * scale for value in channels[3:6]],
        'color2': [value * scale for value in channels[6:9]],
        'color3': [value * scale for value in channels[9:12]],
    }


def validate_color(value):
    """RGB components are finite numbers in [0, 1]; black is a real color."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('Expected an RGB array with three components')
    if any(isinstance(component, bool) or
           not isinstance(component, (int, float)) or
           not 0.0 <= component <= 1.0 for component in value):
        raise ValueError('RGB components must be numbers from 0 to 1')
    return list(value)


def parse_color(value):
    try:
        return validate_color([float(component) for component in value.split(',')])
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


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
        # Migrate snapshots saved before Network Matrix was added.
        # Advertised Art-Net identity is command-line configuration, not state.
        values.pop('matrix_node_name', None)
        values.setdefault('matrix_size', 16)
        values.setdefault('matrix_artnet', {'port_address': 0})
        values.setdefault('matrix_sacn', {'universe': 1})
        values.setdefault('matrix_protocol', 'artnet')
        values.setdefault('matrix_channels_per_universe', 510)
        values.setdefault('matrix_start_address', 1)
        values.setdefault('network_control_enabled', False)
        values.setdefault('network_control_protocol', 'artnet')
        values.setdefault('network_control_artnet', {'port_address': 0})
        values.setdefault('network_control_sacn', {'universe': 1})
        values.setdefault('network_control_start_address', 1)
        values.setdefault('network_control_hold', 30.0)
        artnet_port = validate_matrix_protocol_config(values['matrix_artnet'], 'port_address', 'Art-Net')
        sacn_universe = validate_matrix_protocol_config(values['matrix_sacn'], 'universe', 'sACN')
        validate_matrix_config(values['matrix_size'], artnet_port,
                               values['matrix_channels_per_universe'], values['matrix_start_address'])
        validate_matrix_config(values['matrix_size'], sacn_universe,
                             values['matrix_channels_per_universe'], values['matrix_start_address'], protocol='sacn')
        if values['matrix_protocol'] not in ('artnet', 'sacn'):
            raise ValueError('unknown Network Matrix protocol')
        validate_control_config(values['network_control_protocol'],
                                values['network_control_artnet'],
                                values['network_control_sacn'],
                                values['network_control_start_address'])
        if not isinstance(values['network_control_enabled'], bool):
            raise ValueError('invalid Network Control enabled value')
        hold = values['network_control_hold']
        if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not math.isfinite(hold) or not 0 <= hold <= 3600:
            raise ValueError('invalid Network Control hold')
        if set(values) != set(AppState.persisted_keys()):
            raise ValueError('unexpected or missing fields')
        if values['effect'] not in effect_ids:
            raise ValueError('unknown effect')
        if values['led_effect'] not in led_effect_ids:
            raise ValueError('unknown LED effect')
        if values['input_mode'] not in ('effect', 'ndi', 'network_matrix'):
            raise ValueError('unknown input mode')
        if values['ndi_source'] is not None and not isinstance(values['ndi_source'], str):
            raise ValueError('invalid NDI source')
        if not isinstance(values['autoplay_effects'], list) or any(
                not isinstance(item, str) or item not in effect_ids
                for item in values['autoplay_effects']):
            raise ValueError('invalid autoplay effects')
        if not isinstance(values['autoplay'], bool):
            raise ValueError('invalid autoplay value')
        for key in ('color1', 'color2', 'color3'):
            values[key] = validate_color(values[key])
        for key, low, high in (
            ('speed', 0.0, 4.0),
            ('brightness', 0.0, 1.0),
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
    for index, default in enumerate(('0,0,1', '1,1,0', '1,0,0'), start=1):
        parser.add_argument('--color%d' % index, type=parse_color, default=default,
                            help='Initial RGB color as R,G,B with components from 0 to 1')
    parser.add_argument('--brightness', type=float, default=1.0, help='Initial brightness from 0.0 to 1.0')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='Initial effect speed multiplier from 0.0 to 4.0')
    parser.add_argument('--autoplay', action='store_true', help='Randomly switch effects on the server')
    parser.add_argument('--autoplay-interval', type=float, default=30.0, help='Seconds between autoplay effect switches')
    parser.add_argument('--state-file', default=None,
                        help='Persist server state to this JSON file')
    parser.add_argument('--dmx-device', default='/dev/dmx-in',
                        help='DMX input TTY (default: /dev/dmx-in)')
    parser.add_argument('--dmx-start', type=int, default=None,
                        help='Enable DMX using this 1-based start address')
    parser.add_argument('--dmx-hold', type=float, default=30.0,
                        help='Seconds to retain DMX values after signal loss')
    parser.add_argument('--artnet-debug', action='store_true',
                        help='Log ArtNet reception and framebuffer diagnostics once per second')
    parser.add_argument('--sacn-debug', action='store_true',
                        help='Log sACN reception and framebuffer diagnostics once per second')
    parser.add_argument('--artnet-name', type=artnet.validate_node_name, default='fbmserve',
                        help='Advertised Art-Net node name (default: fbmserve)')
    parser.add_argument('--artnet-poll-broadcast', action='store_true',
                        help='TEST ONLY: broadcast ArtPollReply packets to 255.255.255.255')
    args = parser.parse_args()
    if args.artnet_debug or args.sacn_debug:
        logging.basicConfig(level=logging.WARNING,
                            format='%(asctime)s %(name)s: %(message)s')
    if args.artnet_debug:
        artnet.logger.setLevel(logging.DEBUG)
    if args.sacn_debug:
        sacn_receiver.logger.setLevel(logging.DEBUG)
    if sys.platform == 'win32' and args.dmx_start is not None:
        parser.error('DMX input is not supported on Windows')
    if args.dmx_start is not None and not 1 <= args.dmx_start <= 513 - DMX_CHANNELS:
        parser.error('--dmx-start must be between 1 and %d' % (513 - DMX_CHANNELS))
    if not math.isfinite(args.dmx_hold) or args.dmx_hold < 0:
        parser.error('--dmx-hold must be a finite, non-negative number')
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
        'color1': args.color1,
        'color2': args.color2,
        'color3': args.color3,
        'speed': clamp(args.speed, 0.0, 4.0),
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
    dmx_receiver = (DMXReceiver(args.dmx_device)
                    if args.dmx_start is not None and DMXReceiver is not None else None)

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
                             led_effects_dir, dmx_receiver, args.dmx_start or 1,
                             args.dmx_hold, args.artnet_poll_broadcast, args.artnet_name)
    try:
        matrix.run(renderer.render)
    finally:
        renderer.close()
        server.shutdown()
        if ndi_discovery is not None:
            ndi_discovery.close()


if __name__ == '__main__':
    main()
