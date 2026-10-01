"""Protocol-neutral RGB matrix channel buffer shared by network receivers."""
from collections import Counter
import threading
import time


def channel_count(size):
    if type(size) is not int or size not in (16, 32, 64):
        raise ValueError('Matrix size must be 16, 32 or 64')
    return size * size * 3


class PixelBuffer:
    """RGB storage accepting sequential channel blobs at zero-based offsets.

    channel_count reports the required number of byte values. Universe packing,
    addressing, and packet trimming are receiver concerns. Batch writes publish atomically without counting packets
    again; those packets were counted when received and staged.
    """
    def __init__(self, size):
        self.channel_count = channel_count(size)
        self.size = size
        self.pixels = bytearray(self.channel_count)
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

    def write(self, offset, data):
        """Write a channel blob, preserving untouched bytes and clipping the end."""
        if type(offset) is not int or not 0 <= offset < self.channel_count:
            return self._reject('outside_buffer_range')
        self.write_batch([(offset, data)])
        with self.lock:
            self.packets += 1
            self.diagnostics['accepted'] += 1
            self.last_packet = time.monotonic()
        return True

    def write_batch(self, changes):
        """Publish (offset, data) blobs together under one lock."""
        with self.lock:
            target = self._target_buffer_locked()
            for offset, data in changes:
                if type(offset) is not int or not 0 <= offset < self.channel_count:
                    continue
                count = min(len(data), self.channel_count - offset)
                target[offset:offset + count] = data[:count]

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
            }
