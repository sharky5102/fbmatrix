"""sACN Network Matrix receiver backed by the ``sacn`` PyPI package.

The receiver tracks one synchronization universe at a time. If incoming data
switches to another sync universe, it discards pending updates and clears the
matrix before processing the new stream.
"""
import logging
import socket
import threading
import time

import sacn
from sacn.messages.sync_packet import SyncPacket
from sacn.receiving.receiver_socket_udp import ReceiverSocketUDP

from matrix_buffer import PixelBuffer, universe_count

logger = logging.getLogger(__name__)
PORT = 5568
MAX_UNIVERSE = 63999
ACN_PACKET_PREFIX = b'\x00\x10\x00\x00ASC-E1.17\x00\x00\x00'
NETWORK_DATA_LOSS_TIMEOUT = 2.5


class _ReceiverHandlerProxy:
    """Inspect sync packets, then pass all datagrams to the sacn package.

    The package provides SyncPacket.make_sync_packet(), but its receiver only
    exposes DMX callbacks. This proxy wires the sync parser into that path.
    """
    def __init__(self, sync_callback, maintenance_callback):
        self.sync_callback = sync_callback
        self.maintenance_callback = maintenance_callback
        self.handler = None

    def on_data(self, data, current_time):
        packet = bytes(data)
        sync_packet = parse_sync_packet(packet)
        if sync_packet is not None:
            self.sync_callback(sync_packet.syncAddr, sync_packet.sequence)
        self.maintenance_callback()
        if self.handler is not None:
            self.handler.on_data(data, current_time)

    def on_periodic_callback(self, current_time):
        self.maintenance_callback()
        if self.handler is not None:
            self.handler.on_periodic_callback(current_time)


class _SyncAwareSocket(ReceiverSocketUDP):
    """Use sacn's normal UDP socket/thread while also exposing sync packets."""
    def __init__(self, bind_address, bind_port, sync_callback, maintenance_callback):
        self.handler_proxy = _ReceiverHandlerProxy(sync_callback, maintenance_callback)
        super().__init__(self.handler_proxy, bind_address, bind_port)


def parse_sync_packet(packet):
    """Parse an E1.31 sync packet using the sacn package's packet parser."""
    # SyncPacket.make_sync_packet validates the vectors and fields, but assumes
    # E1.31 input and accepts 47-byte packets; validate the full ACN header and
    # 49-byte sync packet before passing it to that parser.
    if len(packet) < 49 or not packet.startswith(ACN_PACKET_PREFIX):
        return None
    try:
        return SyncPacket.make_sync_packet(packet)
    except (TypeError, ValueError, IndexError):
        return None


def validate_config(size, start_universe, channels_per_universe=510, start_address=1):
    count = universe_count(size, channels_per_universe, start_address)
    if type(start_universe) is not int or not 1 <= start_universe <= MAX_UNIVERSE - count + 1:
        raise ValueError('Matrix universe range must fit within sACN universes 1 to 63999')
    return count


class Receiver(PixelBuffer):
    def __init__(self, size=16, start_universe=1, channels_per_universe=510,
                 start_address=1, bind_address='0.0.0.0'):
        validate_config(size, start_universe, channels_per_universe, start_address)
        super().__init__(size, start_universe, channels_per_universe, start_address)
        self.seen_universes = set()
        self.last_datagram = 'none'
        self.next_debug = 0.0
        self.bind_address = bind_address
        self.stopped = threading.Event()
        self.sync_lock = threading.Lock()
        self.sync_address = 0
        self.sync_seen = False
        self.sync_last_packet = None
        self.sync_force = False
        self.sync_sequence = None
        self.pending = {}
        self.joined_sync_address = None
        sync_socket = _SyncAwareSocket(
            bind_address, PORT, self._on_sync, self._expire_sync_streams)
        try:
            self.receiver = sacn.sACNreceiver(
                bind_address=bind_address, bind_port=PORT, socket=sync_socket)
        except Exception:
            sync_socket.stop()
            raise
        # The library's supported custom-socket hook receives its private packet
        # handler only after construction; wire that handler into our proxy before
        # starting the library's normal receive thread.
        sync_socket.handler_proxy.handler = self.receiver._handler
        try:
            for universe in range(start_universe, start_universe + self.universes):
                self.receiver.register_listener(
                    'universe', self._on_packet, universe=universe)
                self.receiver.join_multicast(universe)
            self.receiver.start()
        except Exception:
            self.receiver.stop()
            raise
        logger.info('Listening on sACN UDP %d; matrix=%dx%d; universes=%d..%d; start channel=%d; packing=%d',
                    PORT, size, size, start_universe,
                    start_universe + self.universes - 1, start_address,
                    channels_per_universe)
        self.debug_thread = None
        if logger.isEnabledFor(logging.DEBUG):
            self.debug_thread = threading.Thread(
                target=self._debug_loop, name='sacn-debug', daemon=True)
            self.debug_thread.start()

    def _on_packet(self, packet):
        if packet.dmxStartCode != 0:
            self._reject('unsupported_start_code')
            return
        channel_offset = self.start_address - 1 if packet.universe == self.start_universe else 0
        sync_address = packet.syncAddr
        with self.sync_lock:
            if sync_address != self.sync_address:
                self._switch_sync_address(sync_address)

            if sync_address == 0:
                accepted = self.update_channels(
                    packet.universe, packet.dmxData, channel_offset)
            elif sync_address != self.joined_sync_address:
                self._reject('sync_join_error')
                accepted = self.update_channels(
                    packet.universe, packet.dmxData, channel_offset)
            else:
                now = time.monotonic()
                active = (self.sync_seen and self.sync_last_packet is not None and
                          now - self.sync_last_packet < NETWORK_DATA_LOSS_TIMEOUT)
                self.sync_force = packet.option_ForceSync
                if active or (self.sync_seen and not packet.option_ForceSync):
                    # Keep only the newest packet for each matrix universe. The
                    # next matching sync packet publishes all pending universes.
                    self.pending[packet.universe] = (packet.dmxData, channel_offset)
                    self.mark_packet_received()
                    accepted = True
                else:
                    self.pending.pop(packet.universe, None)
                    accepted = self.update_channels(
                        packet.universe, packet.dmxData, channel_offset)
        if logger.isEnabledFor(logging.DEBUG):
            self._log_packet(packet, accepted)

    def _switch_sync_address(self, sync_address):
        """Reset to black and switch the single synchronization stream."""
        old_address = self.joined_sync_address
        self.pending.clear()
        self.sync_seen = False
        self.sync_last_packet = None
        self.sync_force = False
        self.sync_sequence = None
        self.sync_address = sync_address
        self.joined_sync_address = None
        with self.lock:
            self.pixels[:] = bytes(len(self.pixels))
        if old_address is not None:
            self.receiver.leave_multicast(old_address)
        if sync_address != 0:
            try:
                # The sync universe uses the same E1.31 multicast mapping as a
                # data universe. Join it on the library's shared socket.
                self.receiver.join_multicast(sync_address)
                self.joined_sync_address = sync_address
            except OSError as error:
                with self.lock:
                    self.error = str(error)

    def _log_packet(self, packet, accepted):
        if logger.isEnabledFor(logging.DEBUG):
            data = packet.dmxData
            source = getattr(packet, 'sourceName', 'unknown')
            self.last_datagram = (
                'source=%r universe=%d sync_universe=%d force_sync=%s start_code=0x%02x '
                'slots=%d nonzero=%d first12=%s accepted=%s' %
                (source, packet.universe, packet.syncAddr, packet.option_ForceSync,
                 packet.dmxStartCode, len(data), sum(value != 0 for value in data),
                 list(data[:12]), accepted))
            if len(self.seen_universes) < 32:
                self.seen_universes.add(packet.universe)
            self._debug_report()

    def _debug_loop(self):
        while not self.stopped.wait(0.25):
            self._debug_report()

    def _expire_sync_streams(self):
        now = time.monotonic()
        with self.sync_lock:
            if (self.sync_seen and self.sync_last_packet is not None and
                    now - self.sync_last_packet >= NETWORK_DATA_LOSS_TIMEOUT):
                self.sync_last_packet = None
                if self.sync_force:
                    self.pending.clear()

    def _on_sync(self, universe, sequence):
        now = time.monotonic()
        with self.sync_lock:
            if universe != self.sync_address or universe != self.joined_sync_address:
                return
            previous = self.sync_sequence
            if previous is not None:
                difference = (sequence - previous) & 0xff
                if difference == 0 or difference > 127:
                    return
            self.sync_sequence = sequence
            self.sync_seen = True
            self.sync_last_packet = now
            changes = [(data_universe, data, offset)
                       for data_universe, (data, offset) in self.pending.items()]
            self.pending.clear()
            if changes:
                self.update_channels_batch(changes)
            with self.lock:
                self.diagnostics['sync_published'] += bool(changes)
                self.diagnostics['sync'] += 1

    def _debug_report(self):
        now = time.monotonic()
        if now < self.next_debug:
            return
        self.next_debug = now + 1.0
        pixels, status = self.snapshot()
        logger.debug('RX totals=%s; observed universes (up to 32)=%s; last datagram: %s; '
                     'buffer nonzero=%d/%d peak=%d last accepted age=%s',
                     dict(self.diagnostics), sorted(self.seen_universes)[:32],
                     self.last_datagram, sum(value != 0 for value in pixels),
                     len(pixels), max(pixels),
                     None if status['age'] is None else round(status['age'], 2))

    def close(self):
        self.stopped.set()
        self.receiver.stop()
        if self.debug_thread is not None:
            self.debug_thread.join()
