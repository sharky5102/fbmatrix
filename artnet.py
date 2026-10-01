"""Art-Net reception and discovery, independent of channel interpretation."""
import logging
from collections import Counter
import ipaddress
import socket
import threading
import time
from channel_mapping import ChannelMapping

logger = logging.getLogger(__name__)

PORT = 6454
ARTNET_ID = b'Art-Net\x00'
OP_DMX = 0x5000
OP_SYNC = 0x5200
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
MIN_PROTOCOL_VERSION = 14
DMX_HEADER_SIZE = 18
MAX_DMX_CHANNELS = 512
ART_POLL_REPLY_SIZE = 240
ART_POLL_REPLY_PORT_LIMIT = 4
ART_POLL_TARGETED = 0x20


def validate_node_name(name):
    if (not isinstance(name, str) or not name or len(name) > 31 or
            not name.isascii() or any(ord(char) < 32 or ord(char) > 126 for char in name)):
        raise ValueError('Advertised name must be 1 to 31 printable ASCII characters')
    return name


def poll_reply_groups(start_universe, universe_count=None):
    """Group input Port-Addresses into replies of at most four ports.

    NetSwitch and SubSwitch are shared by all ports in one ArtPollReply, so a
    group must also end at each 16-universe Sub-Net boundary.
    """
    groups = []
    addresses = (range(start_universe, start_universe + universe_count)
                 if universe_count is not None else sorted(set(start_universe)))
    group = []
    for address in addresses:
        if (group and (address != group[-1] + 1 or address // 16 != group[0] // 16 or
                       len(group) == ART_POLL_REPLY_PORT_LIMIT)):
            groups.append(group)
            group = []
        group.append(address)
    if group:
        groups.append(group)
    return groups


def build_poll_replies(ip_address, start_universe, count=None,
                       targeted_range=None, node_name='fbmserve', description=None):
    """Build one ArtPollReply per advertised group of up to four universes."""
    node_name = validate_node_name(node_name)
    addresses = (tuple(range(start_universe, start_universe + count))
                 if count is not None else tuple(sorted(set(start_universe))))
    if targeted_range is not None:
        bottom, top = targeted_range
        if not any(bottom <= address <= top for address in addresses):
            return []

    ip_bytes = ipaddress.IPv4Address(ip_address).packed
    short_name = b'fbmserve'[:17].ljust(18, b'\0')
    long_name = (description or node_name).encode('ascii')[:63].ljust(64, b'\0')
    packets = []
    for group_index, group in enumerate(poll_reply_groups(addresses), start=1):
        reply = bytearray(ART_POLL_REPLY_SIZE)
        reply[0:8] = ARTNET_ID
        reply[8:10] = OP_POLL_REPLY.to_bytes(2, 'little')
        reply[10:14] = ip_bytes
        reply[14:16] = PORT.to_bytes(2, 'little')
        reply[16:18] = MIN_PROTOCOL_VERSION.to_bytes(2, 'big')
        base = group[0]
        reply[18] = (base >> 8) & 0x7f  # NetSwitch: Port-Address bits 14..8
        reply[19] = (base >> 4) & 0x0f  # SubSwitch: Port-Address bits 7..4
        reply[26:44] = short_name
        reply[44:108] = long_name
        reply[108:172] = b'#0001 [0000] Network Matrix'.ljust(64, b'\0')
        reply[172:174] = len(group).to_bytes(2, 'big')
        # An ArtDmx consumer is an output port (bit 7).
        reply[174:178] = bytes([0x80] * len(group)) + bytes(4 - len(group))
        reply[190:194] = bytes(address & 0x0f for address in group) + bytes(4 - len(group))
        reply[200] = 0x02  # StMedia: Network Matrix acts as a media server.
        reply[207:211] = ip_bytes
        reply[211] = group_index  # BindIndex distinguishes this multi-port node's replies.
        reply[212] = 0x08  # Supports the Art-Net 3/4 15-bit Port-Address.
        packets.append(bytes(reply))
    return packets


class ArtDmxInput:
    """Decode ArtDmx/ArtSync and route packets through a channel mapping."""
    def __init__(self, mappings):
        if not mappings:
            raise ValueError('At least one channel mapping is required')
        self.mappings = mappings
        self.universe_numbers = tuple(sorted({universe for mapping in self.mappings
                                              for universe in mapping.universe_numbers}))
        if any(not 0 <= universe <= 32767 for universe in self.universe_numbers):
            raise ValueError('Art-Net Port-Addresses must be between 0 and 32767')
        self.last_sync = None
        self.last_dmx_source = None
        self.diagnostics = Counter()
        self.diagnostics_lock = threading.Lock()
        self.packets = 0
        self.last_packet = None
        self.error = None

    def update(self, packet, source=None):
        # ArtDmx's fixed header (byte offsets, end exclusive):
        #   0:8   ID: ASCII "Art-Net" followed by a NUL
        #   8:10  OpCode: 0x5000 for ArtDmx, LITTLE endian
        #  10:12  ProtVer: protocol revision, BIG endian (minimum 14)
        #  12     Sequence: 1..255, or 0 to disable sequencing
        #  13     Physical: originating physical input port
        #  14:16  Port-Address: SubUni byte then Net byte, LITTLE endian
        #  16:18  Length: number of DMX channel bytes, BIG endian
        #  18:    Data: channel 1 onward, with no DMX start-code byte
        # The mixed byte order is intentional in the Art-Net specification.
        if len(packet) < 12:
            return self._reject('short_header')
        identifier = packet[:8]
        opcode = int.from_bytes(packet[8:10], 'little')
        version = int.from_bytes(packet[10:12], 'big')
        if identifier != ARTNET_ID:
            return self._reject('invalid_id')
        if opcode not in (OP_DMX, OP_SYNC):
            return self._reject('other_opcode')
        if version < MIN_PROTOCOL_VERSION:
            return self._reject('old_version')
        if opcode == OP_SYNC:
            # ArtSync is ID + opcode + protocol version + two auxiliary bytes.
            if len(packet) < 14:
                return self._reject('short_sync')
            if self.last_dmx_source is not None and source != self.last_dmx_source:
                return self._reject('sync_source_mismatch')
            now = time.monotonic()
            if self.last_sync is None or now - self.last_sync >= 4.0:
                for mapping in self.mappings:
                    mapping.begin_sync()
            else:
                for mapping in self.mappings:
                    mapping.publish_sync()
            self.last_sync = now
            self._record('sync')
            return True
        if opcode != OP_DMX:
            return self._reject('other_opcode')
        if len(packet) < DMX_HEADER_SIZE:
            return self._reject('short_header')
        # Apply packets in arrival order, ignoring Sequence and Physical.
        # ArtDmx is applied immediately until the first ArtSync arrives.
        # Port-Address packs Net (7 bits), Sub-Net (4) and Universe (4) into
        # a zero-based 15-bit address. The configured range rejects bit 15.
        universe = int.from_bytes(packet[14:16], 'little')
        length = int.from_bytes(packet[16:18], 'big')
        # ArtDmx requires an even length of 2..512. Reject truncated data;
        # any bytes beyond the declared length are not channel values.
        if not 2 <= length <= MAX_DMX_CHANNELS or length % 2:
            return self._reject('invalid_length')
        if len(packet) < DMX_HEADER_SIZE + length:
            return self._reject('truncated_payload')
        data = packet[DMX_HEADER_SIZE:DMX_HEADER_SIZE + length]
        if self.last_sync is not None and time.monotonic() - self.last_sync >= 4.0:
            self.last_sync = None
            for mapping in self.mappings:
                mapping.end_sync()
        matching = [mapping for mapping in self.mappings
                    if universe in mapping.universe_indices]
        if not matching:
            return self._reject('outside_universe_range')
        accepted_results = [mapping.deliver(universe, data) for mapping in matching]
        accepted = all(accepted_results)
        if accepted:
            self._record('accepted', packet=True)
        if accepted and source is not None:
            self.last_dmx_source = source
        return accepted

    def _reject(self, reason):
        self._record(reason)
        return False

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


class Receiver(ArtDmxInput):
    def __init__(self, mapping,
                 host='0.0.0.0', port=PORT, poll_broadcast=False,
                 node_name='fbmserve', description=None):
        super().__init__(mapping)
        self.node_name = validate_node_name(node_name)
        self.description = description
        self.poll_broadcast = poll_broadcast
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.poll_broadcast:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.socket.bind((host, port))
            self.socket.settimeout(0.1)
        except OSError:
            self.socket.close()
            raise
        self.next_debug = 0.0
        self.last_datagram = 'none'
        self.seen_universes = set()
        logger.debug('Listening on %s:%d; universes=%s',
                     *self.socket.getsockname(), self.universe_numbers)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._receive, name='artnet', daemon=True)
        self.thread.start()

    def _receive(self):
        while not self.stopped.is_set():
            try:
                packet, sender = self.socket.recvfrom(65535)
            except socket.timeout:
                self._debug_report()
                continue
            except OSError as error:
                if not self.stopped.is_set():
                    self.error = str(error)
                return
            if (len(packet) >= 10 and packet[:8] == ARTNET_ID and
                    int.from_bytes(packet[8:10], 'little') == OP_POLL):
                accepted = self.respond_to_poll(packet, sender)
            else:
                accepted = self.update(packet, source=sender[0])
            if logger.isEnabledFor(logging.DEBUG):
                self.last_datagram = 'sender=%s:%d bytes=%d accepted=%s' % (*sender, len(packet), accepted)
                if len(packet) >= 10 and packet[:8] == ARTNET_ID:
                    opcode = int.from_bytes(packet[8:10], 'little')
                    self.last_datagram += ' opcode=0x%04x' % opcode
                    if opcode == OP_DMX and len(packet) >= DMX_HEADER_SIZE:
                        universe = int.from_bytes(packet[14:16], 'little')
                        length = int.from_bytes(packet[16:18], 'big')
                        if len(self.seen_universes) < 32:
                            self.seen_universes.add(universe)
                        data = packet[DMX_HEADER_SIZE:DMX_HEADER_SIZE + length]
                        self.last_datagram += ' universe=%d length=%d nonzero=%d first12=%s' % (
                            universe, length, sum(value != 0 for value in data), list(data[:12]))
                    elif opcode == OP_SYNC:
                        self.last_datagram += ' ArtSync'
                    elif opcode == OP_POLL:
                        self.last_datagram += ' ArtPoll'
                self._debug_report()

    def respond_to_poll(self, packet, sender):
        """Reply directly to a controller's ArtPoll with our universe ports."""
        if len(packet) < 14:
            self._reject('short_poll')
            return False
        version = int.from_bytes(packet[10:12], 'big')
        if version < MIN_PROTOCOL_VERSION:
            self._reject('old_version')
            return False
        targeted_range = None
        if packet[12] & ART_POLL_TARGETED:
            if len(packet) < 18:
                self._reject('short_targeted_poll')
                return False
            top = int.from_bytes(packet[14:16], 'big')
            bottom = int.from_bytes(packet[16:18], 'big')
            targeted_range = (bottom, top)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((sender[0], PORT))
                node_ip = route.getsockname()[0]
            replies = build_poll_replies(
                node_ip, self.universe_numbers,
                targeted_range=targeted_range, node_name=self.node_name,
                description=self.description)
            destination = ('255.255.255.255' if self.poll_broadcast else sender[0], PORT)
            for reply in replies:
                self.socket.sendto(reply, destination)
        except OSError as error:
            self.error = str(error)
            self._reject('poll_reply_error')
            logger.warning('Unable to reply to ArtPoll from %s: %s', sender[0], error)
            return False
        self._record('poll')
        if replies:
            self._record('poll_replies', amount=len(replies))
        logger.debug('Replied to ArtPoll from %s with %d ArtPollReply packet(s) via %s',
                     sender[0], len(replies), 'broadcast' if self.poll_broadcast else 'unicast')
        return True

    def _debug_report(self):
        if not logger.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if now < self.next_debug:
            return
        self.next_debug = now + 1.0
        logger.debug('RX totals=%s; observed universes (up to 32)=%s; last datagram: %s',
                     dict(self.diagnostics),
                     sorted(self.seen_universes), self.last_datagram)

    def close(self):
        self.stopped.set()
        self.thread.join()
        self.socket.close()


def validate_config(channel_count, start_universe, channels_per_universe=510,
                    start_address=1):
    count = ChannelMapping.required_universes(
        channel_count, channels_per_universe, start_address)
    if type(start_universe) is not int or not 0 <= start_universe <= 32768 - count:
        raise ValueError('Art-Net universe range must fit within 0 to 32767')
    return count
