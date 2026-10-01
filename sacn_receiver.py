"""sACN channel receiver backed by the ``sacn`` PyPI package.

The receiver tracks one synchronization universe at a time. If incoming data
switches to another sync universe, it discards pending updates and clears the
channel sink before processing the new stream.
"""
import logging
from collections import Counter
import threading
import time
from channel_mapping import ChannelMapping

import sacn
from sacn.messages.sync_packet import SyncPacket
from sacn.receiving.receiver_socket_udp import ReceiverSocketUDP

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


class Receiver:
    """Receive sACN and route packets using a channel mapping."""
    def __init__(self, mappings, bind_address='0.0.0.0'):
        if not mappings:
            raise ValueError('At least one channel mapping is required')
        self.mappings = mappings
        self.universe_numbers = tuple(sorted({universe for mapping in self.mappings
                                              for universe in mapping.universe_numbers}))
        if any(not 1 <= universe <= MAX_UNIVERSE for universe in self.universe_numbers):
            raise ValueError('sACN universes must be between 1 and %d' % MAX_UNIVERSE)
        self.seen_universes = set()
        self.diagnostics = Counter()
        self.diagnostics_lock = threading.Lock()
        self.packets = 0
        self.last_packet = None
        self.error = None
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
            for universe in self.universe_numbers:
                self.receiver.register_listener(
                    'universe', self._on_packet, universe=universe)
                self.receiver.join_multicast(universe)
            self.receiver.start()
        except Exception:
            self.receiver.stop()
            raise
        logger.info('Listening on sACN UDP %d; universes=%s',
                    PORT, self.universe_numbers)
        self.debug_thread = None
        if logger.isEnabledFor(logging.DEBUG):
            self.debug_thread = threading.Thread(
                target=self._debug_loop, name='sacn-debug', daemon=True)
            self.debug_thread.start()

    def _on_packet(self, packet):
        if packet.dmxStartCode != 0:
            self._reject('unsupported_start_code')
            return
        mapped = [(mapping, mapping.map(packet.universe, packet.dmxData))
                  for mapping in self.mappings
                  if packet.universe in mapping.universe_indices]
        if not mapped:
            self._reject('outside_universe_range')
            return
        sync_address = packet.syncAddr
        with self.sync_lock:
            if sync_address != self.sync_address:
                self._switch_sync_address(sync_address)

            if sync_address == 0:
                accepted = self._deliver(mapped, packet.universe, packet.dmxData)
            elif sync_address != self.joined_sync_address:
                self._reject('sync_join_error')
                accepted = self._deliver(mapped, packet.universe, packet.dmxData)
            else:
                now = time.monotonic()
                active = (self.sync_seen and self.sync_last_packet is not None and
                          now - self.sync_last_packet < NETWORK_DATA_LOSS_TIMEOUT)
                self.sync_force = packet.option_ForceSync
                if active or (self.sync_seen and not packet.option_ForceSync):
                    # Keep only the newest packet for each data universe. The
                    # next matching sync packet publishes all pending universes.
                    for mapping, change in mapped:
                        self.pending[(mapping, packet.universe)] = change
                    accepted = True
                else:
                    for mapping, _change in mapped:
                        self.pending.pop((mapping, packet.universe), None)
                    accepted = self._deliver(mapped, packet.universe, packet.dmxData)
        if accepted:
            self._record('accepted', packet=True)
        if logger.isEnabledFor(logging.DEBUG):
            self._log_packet(packet, accepted)

    def _switch_sync_address(self, sync_address):
        """Clear the sink and switch the single synchronization stream."""
        old_address = self.joined_sync_address
        self.pending.clear()
        self.sync_seen = False
        self.sync_last_packet = None
        self.sync_force = False
        self.sync_sequence = None
        self.sync_address = sync_address
        self.joined_sync_address = None
        for mapping in self.mappings:
            mapping.clear()
        if old_address is not None:
            self.receiver.leave_multicast(old_address)
        if sync_address != 0:
            try:
                # The sync universe uses the same E1.31 multicast mapping as a
                # data universe. Join it on the library's shared socket.
                self.receiver.join_multicast(sync_address)
                self.joined_sync_address = sync_address
            except OSError as error:
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
            changes = {}
            for (mapping, _universe), change in self.pending.items():
                changes.setdefault(mapping, []).append(change)
            self.pending.clear()
            for mapping in self.mappings:
                if mapping in changes:
                    mapping.deliver_batch(changes[mapping])
                    self._record('sync_published')
            self._record('sync')

    def _debug_report(self):
        now = time.monotonic()
        if now < self.next_debug:
            return
        self.next_debug = now + 1.0
        logger.debug('RX totals=%s; observed universes (up to 32)=%s; last datagram: %s',
                     dict(self.diagnostics),
                     sorted(self.seen_universes), self.last_datagram)

    def _record(self, reason, packet=False, amount=1):
        with self.diagnostics_lock:
            self.diagnostics[reason] += amount
            if packet:
                self.packets += 1
                self.last_packet = time.monotonic()

    def status(self):
        with self.diagnostics_lock:
            age = None if self.last_packet is None else time.monotonic() - self.last_packet
            return {'packets': self.packets, 'age': age, 'error': self.error,
                    'universes': len(self.universe_numbers)}

    def _deliver(self, mapped, universe, data):
        accepted = True
        for mapping, _change in mapped:
            accepted = mapping.deliver(universe, data) and accepted
        return accepted

    def _reject(self, reason):
        self._record(reason)
        return False

    def close(self):
        self.stopped.set()
        self.receiver.stop()
        if self.debug_thread is not None:
            self.debug_thread.join()


def validate_config(channel_count, start_universe, channels_per_universe=510,
                    start_address=1):
    count = ChannelMapping.required_universes(
        channel_count, channels_per_universe, start_address)
    if type(start_universe) is not int or not 1 <= start_universe <= MAX_UNIVERSE - count + 1:
        raise ValueError('sACN universe range must fit within 1 to %d' % MAX_UNIVERSE)
    return count
