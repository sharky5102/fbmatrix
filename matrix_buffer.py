"""Protocol-neutral RGB pixel storage written by network receivers."""
import threading
from channel_mapping import ChannelBufferBase


def channel_count(size):
    if type(size) is not int or size not in (16, 32, 64):
        raise ValueError('Matrix size must be 16, 32 or 64')
    return size * size * 3


class PixelBuffer(ChannelBufferBase):
    """RGB storage accepting sequential channel blobs at zero-based offsets.

    channel_count reports the required number of byte values. Universe packing,
    addressing, and packet trimming are receiver concerns.
    """
    def __init__(self, size):
        self.channel_count = channel_count(size)
        self.size = size
        self.pixels = bytearray(self.channel_count)
        self.staging_pixels = None
        self.lock = threading.Lock()

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

    def write_batch(self, changes):
        """Publish (offset, data) blobs together under one lock."""
        with self.lock:
            target = self._target_buffer_locked()
            for offset, data in changes:
                if type(offset) is not int or not 0 <= offset < self.channel_count:
                    continue
                count = min(len(data), self.channel_count - offset)
                target[offset:offset + count] = data[:count]

    def _target_buffer_locked(self):
        return self.pixels if self.staging_pixels is None else self.staging_pixels

    def snapshot(self):
        with self.lock:
            return bytes(self.pixels)


class ChannelBuffer(ChannelBufferBase):
    """Storage for sequential non-pixel channel data such as DMX controls."""
    def __init__(self, channel_count):
        if type(channel_count) is not int or channel_count <= 0:
            raise ValueError('Channel count must be a positive integer')
        self.channel_count = channel_count
        self.channels = bytearray(channel_count)
        self.lock = threading.Lock()

    def clear(self):
        with self.lock:
            self.channels[:] = bytes(self.channel_count)

    def write_batch(self, changes):
        with self.lock:
            for offset, data in changes:
                if type(offset) is not int or not 0 <= offset < self.channel_count:
                    continue
                count = min(len(data), self.channel_count - offset)
                self.channels[offset:offset + count] = data[:count]

    def snapshot(self):
        with self.lock:
            return bytes(self.channels)
