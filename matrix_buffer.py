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
    def __init__(self, size, start_universe, channels_per_universe, start_address):
        self.universes = universe_count(size, channels_per_universe, start_address)
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

    def update_channels(self, universe, data, channel_offset=0):
        """Apply slot values from one universe; partial packets preserve pixels."""
        if not self.start_universe <= universe < self.start_universe + self.universes:
            return self._reject('outside_universe_range')
        index = universe - self.start_universe
        first_capacity = self.channels_per_universe - self.start_address + 1
        offset = first_capacity + (index - 1) * self.channels_per_universe if index else 0
        capacity = first_capacity if index == 0 else self.channels_per_universe
        count = min(max(0, len(data) - channel_offset), capacity, len(self.pixels) - offset)
        with self.lock:
            target = self._target_buffer_locked()
            target[offset:offset + count] = data[channel_offset:channel_offset + count]
            self.packets += 1
            self.diagnostics['accepted'] += 1
            self.last_packet = time.monotonic()
        return True

    def _target_buffer_locked(self):
        return self.pixels

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
