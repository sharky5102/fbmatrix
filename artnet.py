"""ArtDmx input: RGB pixels in top-left row order, with 510/512-channel packing.

Wire format: https://art-net.org.uk/downloads/art-net.pdf (ArtDmx).
Art-Net transports DMX channel values; their interpretation as RGB pixels and
the selected channel packing are our matrix profile, not requirements of Art-Net.
"""
import logging
import ipaddress
import socket
import threading
import time
from matrix_buffer import PixelBuffer, universe_count

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
PIXELS_PER_UNIVERSE = 170
RGB_CHANNELS_PER_UNIVERSE = PIXELS_PER_UNIVERSE * 3


def validate_config(size, start_universe, channels_per_universe=510, start_address=1):
    count = universe_count(size, channels_per_universe, start_address)
    if type(start_universe) is not int or not 0 <= start_universe <= 32768 - count:
        raise ValueError('Matrix universe range must fit within 0 to 32767')
    return count


def validate_node_name(name):
    if (not isinstance(name, str) or not name or len(name) > 31 or
            not name.isascii() or any(ord(char) < 32 or ord(char) > 126 for char in name)):
        raise ValueError('Advertised name must be 1 to 31 printable ASCII characters')
    return name


def poll_reply_groups(start_universe, universe_count):
    """Group input Port-Addresses into replies of at most four ports.

    NetSwitch and SubSwitch are shared by all ports in one ArtPollReply, so a
    group must also end at each 16-universe Sub-Net boundary.
    """
    end = start_universe + universe_count
    groups = []
    address = start_universe
    while address < end:
        subnet_end = (address // 16 + 1) * 16
        group_end = min(end, subnet_end, address + ART_POLL_REPLY_PORT_LIMIT)
        groups.append(list(range(address, group_end)))
        address = group_end
    return groups


def build_poll_replies(ip_address, size, start_universe, channels_per_universe,
                       start_address, targeted_range=None, node_name='fbmserve'):
    """Build one ArtPollReply per advertised group of up to four universes."""
    count = validate_config(size, start_universe, channels_per_universe, start_address)
    node_name = validate_node_name(node_name)
    addresses = range(start_universe, start_universe + count)
    if targeted_range is not None:
        bottom, top = targeted_range
        if not any(bottom <= address <= top for address in addresses):
            return []

    ip_bytes = ipaddress.IPv4Address(ip_address).packed
    short_name = b'fbmserve'[:17].ljust(18, b'\0')
    long_name = ('%s %dx%d u%d %dch/univ addr%d' %
                 (node_name, size, size, start_universe,
                  channels_per_universe, start_address)).encode('ascii').ljust(64, b'\0')
    packets = []
    for group_index, group in enumerate(poll_reply_groups(start_universe, count), start=1):
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
        # The matrix consumes ArtDmx and presents the received image, so it is
        # an Art-Net output port (bit 7), rather than a DMX input port (bit 6).
        reply[174:178] = bytes([0x80] * len(group)) + bytes(4 - len(group))
        reply[190:194] = bytes(address & 0x0f for address in group) + bytes(4 - len(group))
        reply[200] = 0x02  # StMedia: Network Matrix acts as a media server.
        reply[207:211] = ip_bytes
        reply[211] = group_index  # BindIndex distinguishes this multi-port node's replies.
        reply[212] = 0x08  # Supports the Art-Net 3/4 15-bit Port-Address.
        packets.append(bytes(reply))
    return packets


class ArtDmxBuffer(PixelBuffer):
    def __init__(self, size=16, start_universe=0, channels_per_universe=510,
                 start_address=1, node_name='fbmserve'):
        validate_config(size, start_universe, channels_per_universe, start_address)
        self.node_name = validate_node_name(node_name)
        super().__init__(size, start_universe, channels_per_universe, start_address)
        self.staging_pixels = None
        self.last_sync = None
        self.last_dmx_source = None

    def _target_buffer_locked(self):
        if self.last_sync is not None and time.monotonic() - self.last_sync < 4.0:
            return self.staging_pixels
        self.last_sync = None
        self.staging_pixels = None
        return self.pixels

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
            with self.lock:
                # Art-Net requires ArtSync to come from the most recent ArtDmx
                # sender. Ignore unrelated controllers on the same network.
                if self.last_dmx_source is not None and source != self.last_dmx_source:
                    self.diagnostics['sync_source_mismatch'] += 1
                    return False
                now = time.monotonic()
                if self.last_sync is None or now - self.last_sync >= 4.0:
                    self.staging_pixels = bytearray(self.pixels)
                else:
                    self.pixels, self.staging_pixels = self.staging_pixels, self.pixels
                    # Keep unchanged universes/pixels for the next partial frame.
                    self.staging_pixels[:] = self.pixels
                self.last_sync = now
                self.diagnostics['sync'] += 1
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
        if not self.start_universe <= universe < self.start_universe + self.universes:
            return self._reject('outside_universe_range')
        # 510 mode leaves channels 511/512 unused, keeping RGB pixels intact.
        # 512 mode packs all channels continuously, allowing pixels to span
        # universes (e.g. R/G at 511/512, B at channel 1). Clip the final universe to
        # the matrix size, and retain untouched channels on partial updates.
        channel_offset = self.start_address - 1 if universe == self.start_universe else 0
        accepted = self.update_channels(
            universe, packet[DMX_HEADER_SIZE:DMX_HEADER_SIZE + length],
            channel_offset=channel_offset)
        if accepted and source is not None:
            with self.lock:
                self.last_dmx_source = source
        return accepted

    def _reject(self, reason):
        with self.lock:
            self.diagnostics[reason] += 1
        return False

    def snapshot(self):
        with self.lock:
            age = None if self.last_packet is None else time.monotonic() - self.last_packet
            return bytes(self.pixels), {
                'packets': self.packets, 'age': age, 'error': self.error,
                'universes': self.universes,
            }


class Receiver(ArtDmxBuffer):
    def __init__(self, size=16, start_universe=0, host='0.0.0.0', port=PORT,
                 channels_per_universe=510, start_address=1, poll_broadcast=False,
                 node_name='fbmserve'):
        super().__init__(size, start_universe, channels_per_universe,
                         start_address, node_name)
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
        logger.debug('Listening on %s:%d; matrix=%dx%d; zero-based universes=%d..%d; start channel=%d; channel packing=%d',
                     *self.socket.getsockname(), size, size, start_universe,
                     start_universe + self.universes - 1, start_address, channels_per_universe)
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
                    with self.lock:
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
                node_ip, self.size, self.start_universe,
                self.channels_per_universe, self.start_address, targeted_range,
                self.node_name)
            destination = ('255.255.255.255' if self.poll_broadcast else sender[0], PORT)
            for reply in replies:
                self.socket.sendto(reply, destination)
        except OSError as error:
            with self.lock:
                self.error = str(error)
            self._reject('poll_reply_error')
            logger.warning('Unable to reply to ArtPoll from %s: %s', sender[0], error)
            return False
        self.diagnostics['poll'] += 1
        self.diagnostics['poll_replies'] += len(replies)
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
        pixels, status = self.snapshot()
        logger.debug('RX totals=%s; observed universes (up to 32)=%s; last datagram: %s; '
                     'buffer nonzero=%d/%d peak=%d last accepted age=%s',
                     dict(self.diagnostics), sorted(self.seen_universes), self.last_datagram,
                     sum(value != 0 for value in pixels), len(pixels), max(pixels),
                     None if status['age'] is None else round(status['age'], 2))

    def close(self):
        self.stopped.set()
        self.thread.join()
        self.socket.close()
