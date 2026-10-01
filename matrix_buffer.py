"""Protocol-neutral RGB matrix channel buffer shared by network receivers."""
from collections import Counter
import threading
import time


def universe_count(size, channels_per_universe, start_address):
    if type(size) is not int or size not in (16, 32, 64):
        raise ValueError('Matrix size must be 16, 32 or 64')
    if type(channels_per_universe) is not int or channels_per_universe not in (510, 512):
        raise ValueError('Channels per universe must be 510 or 512')
    if type(start_address) is not int or not 1 <= start_address <= channels_per_universe:
        raise ValueError('Start address must be within the selected universe channel range')
    first_capacity = channels_per_universe - start_address + 1
    remaining = max(0, size * size * 3 - first_capacity)
    return 1 + (remaining + channels_per_universe - 1) // channels_per_universe


class PixelBuffer:
    """Channel sink mapping complete DMX slot arrays to RGB pixels.

    Receivers pass untrimmed channels, starting at slot 1, and own sync timing.
    begin_sync/publish_sync/end_sync stage Art-Net updates; sACN publishes
    (universe, channels) batches atomically. clear discards visible and staged
    values. Reception counters include staged packets, not just published ones.
    """
    def __init__(self, size, start_universe, channels_per_universe, start_address):
        self.universes = universe_count(size, channels_per_universe, start_address)
        self.channels_per_universe = channels_per_universe
        self.start_address = start_address
        self.size = size
        self.start_universe = start_universe
        self.pixels = bytearray(size * size * 3)
        self.staging_pixels = None
        self.lock = threading.Lock()
        self.packets = 0
        self.last_packet = None
        self.error = None
        self.diagnostics = Counter()

    def clear(self):
        with self.lock:
            self.pixels[:] = bytes(len(self.pixels))
            self.staging_pixels = None

    def begin_sync(self):
        with self.lock:
            self.staging_pixels = bytearray(self.pixels)

    def publish_sync(self):
        with self.lock:
            self.pixels[:] = self.staging_pixels

    def end_sync(self):
        with self.lock:
            self.staging_pixels = None

    def update_channels(self, universe, data, channel_offset=None, record_packet=True):
        """Apply slot values from one universe; partial packets preserve pixels."""
        if not self.start_universe <= universe < self.start_universe + self.universes:
            return self._reject('outside_universe_range')
        if channel_offset is None:
            channel_offset = self.start_address - 1 if universe == self.start_universe else 0
        index = universe - self.start_universe
        first_capacity = self.channels_per_universe - self.start_address + 1
        offset = first_capacity + (index - 1) * self.channels_per_universe if index else 0
        capacity = first_capacity if index == 0 else self.channels_per_universe
        count = min(max(0, len(data) - channel_offset), capacity, len(self.pixels) - offset)
        with self.lock:
            target = self._target_buffer_locked()
            target[offset:offset + count] = data[channel_offset:channel_offset + count]
            if record_packet:
                self.packets += 1
                self.diagnostics['accepted'] += 1
                self.last_packet = time.monotonic()
        return True

    def update_channels_batch(self, changes):
        """Apply several universe updates under one lock for frame sync."""
        with self.lock:
            for universe, data in changes:
                channel_offset = self.start_address - 1 if universe == self.start_universe else 0
                if not self.start_universe <= universe < self.start_universe + self.universes:
                    continue
                index = universe - self.start_universe
                first_capacity = self.channels_per_universe - self.start_address + 1
                offset = first_capacity + (index - 1) * self.channels_per_universe if index else 0
                capacity = first_capacity if index == 0 else self.channels_per_universe
                count = min(max(0, len(data) - channel_offset), capacity,
                            len(self.pixels) - offset)
                self.pixels[offset:offset + count] = data[channel_offset:channel_offset + count]

    def mark_packet_received(self, reason='accepted'):
        with self.lock:
            self.packets += 1
            self.diagnostics[reason] += 1
            self.last_packet = time.monotonic()

    def _target_buffer_locked(self):
        return self.pixels if self.staging_pixels is None else self.staging_pixels

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

def validate_config(size, start_universe, channels_per_universe=510, start_address=1,
                    protocol='artnet'):
    count = universe_count(size, channels_per_universe, start_address)
    if protocol not in ('artnet', 'sacn'):
        raise ValueError('Unknown matrix protocol')
    minimum, maximum = (1, 63999) if protocol == 'sacn' else (0, 32767)
    if type(start_universe) is not int or not minimum <= start_universe <= maximum - count + 1:
        raise ValueError('Matrix universe range must fit within %s universes %d to %d' %
                         (protocol, minimum, maximum))
    return count
