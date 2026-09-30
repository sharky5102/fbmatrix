"""ArtDmx input: RGB pixels in top-left row order, with 510/512-channel packing.

Wire format: https://art-net.org.uk/downloads/art-net.pdf (ArtDmx).
Art-Net transports DMX channel values; their interpretation as RGB pixels and
the selected channel packing are our matrix profile, not requirements of Art-Net.
"""
import logging
import socket
from collections import Counter
import threading
import time

logger = logging.getLogger(__name__)

PORT = 6454
ARTNET_ID = b'Art-Net\x00'
OP_DMX = 0x5000
MIN_PROTOCOL_VERSION = 14
DMX_HEADER_SIZE = 18
MAX_DMX_CHANNELS = 512
PIXELS_PER_UNIVERSE = 170
RGB_CHANNELS_PER_UNIVERSE = PIXELS_PER_UNIVERSE * 3


def validate_config(size, start_universe, channels_per_universe=510, start_address=1):
    if type(size) is not int or size not in (16, 32, 64):
        raise ValueError('Matrix size must be 16, 32 or 64')
    if type(channels_per_universe) is not int or channels_per_universe not in (510, 512):
        raise ValueError('Channels per universe must be 510 or 512')
    if (type(start_address) is not int or
            not 1 <= start_address <= channels_per_universe):
        raise ValueError('Start address must be within the selected universe channel range')
    first_capacity = channels_per_universe - start_address + 1
    if first_capacity <= 0:
        raise ValueError('Start address is beyond the selected universe channel range')
    remaining = max(0, size * size * 3 - first_capacity)
    count = 1 + (remaining + channels_per_universe - 1) // channels_per_universe
    if type(start_universe) is not int or not 0 <= start_universe <= 32768 - count:
        raise ValueError('Matrix universe range must fit within 0 to 32767')
    return count


class PixelBuffer:
    def __init__(self, size=16, start_universe=0, channels_per_universe=510, start_address=1):
        self.universes = validate_config(size, start_universe, channels_per_universe, start_address)
        self.channels_per_universe = channels_per_universe
        self.start_address = start_address
        self.size = size
        self.start_universe = start_universe
        self.pixels = bytearray(size * size * 3)
        self.lock = threading.Lock()
        self.packets = 0
        self.last_packet = None
        self.error = None
        self.diagnostics = Counter()

    def update(self, packet):
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
        if len(packet) < DMX_HEADER_SIZE:
            return self._reject('short_header')
        identifier = packet[:8]
        opcode = int.from_bytes(packet[8:10], 'little')
        version = int.from_bytes(packet[10:12], 'big')
        if identifier != ARTNET_ID:
            return self._reject('invalid_id')
        if opcode != OP_DMX:
            return self._reject('other_opcode')
        if version < MIN_PROTOCOL_VERSION:
            return self._reject('old_version')
        # Apply packets in arrival order, ignoring Sequence and Physical.
        # Only ArtDmx reaches here; ArtSync and other opcodes are ignored.
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
        universe_offset = universe - self.start_universe
        first_capacity = self.channels_per_universe - self.start_address + 1
        offset = (first_capacity + (universe_offset - 1) * self.channels_per_universe
                  if universe_offset else 0)
        # 510 mode leaves channels 511/512 unused, keeping RGB pixels intact.
        # 512 mode packs all channels continuously, allowing pixels to span
        # universes (e.g. R/G at 511/512, B at channel 1). Clip the final universe to
        # the matrix size, and retain untouched channels on partial updates.
        channel_offset = self.start_address - 1 if universe_offset == 0 else 0
        capacity = first_capacity if universe_offset == 0 else self.channels_per_universe
        count = min(max(0, length - channel_offset), capacity, len(self.pixels) - offset)
        with self.lock:
            self.pixels[offset:offset + count] = packet[DMX_HEADER_SIZE + channel_offset:DMX_HEADER_SIZE + channel_offset + count]
            self.packets += 1
            self.diagnostics['accepted'] += 1
            self.last_packet = time.monotonic()
        return True

    def _reject(self, reason):
        self.diagnostics[reason] += 1
        return False

    def snapshot(self):
        with self.lock:
            age = None if self.last_packet is None else time.monotonic() - self.last_packet
            return bytes(self.pixels), {
                'packets': self.packets, 'age': age, 'error': self.error,
                'universes': self.universes,
            }


class Receiver(PixelBuffer):
    def __init__(self, size=16, start_universe=0, host='0.0.0.0', port=PORT,
                 channels_per_universe=510, start_address=1):
        super().__init__(size, start_universe, channels_per_universe, start_address)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
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
            accepted = self.update(packet)
            if logger.isEnabledFor(logging.DEBUG):
                self.last_datagram = 'sender=%s:%d bytes=%d accepted=%s' % (*sender, len(packet), accepted)
                if len(packet) >= DMX_HEADER_SIZE and packet[:8] == ARTNET_ID:
                    opcode = int.from_bytes(packet[8:10], 'little')
                    self.last_datagram += ' opcode=0x%04x' % opcode
                    if opcode == OP_DMX:
                        universe = int.from_bytes(packet[14:16], 'little')
                        length = int.from_bytes(packet[16:18], 'big')
                        if len(self.seen_universes) < 32:
                            self.seen_universes.add(universe)
                        data = packet[DMX_HEADER_SIZE:DMX_HEADER_SIZE + length]
                        self.last_datagram += ' universe=%d length=%d nonzero=%d first12=%s' % (
                            universe, length, sum(value != 0 for value in data), list(data[:12]))
                self._debug_report()

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
