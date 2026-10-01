"""Receiver-side mapping from DMX universes to a sequential channel stream."""


class ChannelMapping:
    def __init__(self, channel_count, channels_per_universe, start_universe,
                 start_address, minimum_universe, maximum_universe):
        if type(channel_count) is not int or channel_count < 1:
            raise ValueError('Channel count must be a positive integer')
        if type(channels_per_universe) is not int or channels_per_universe not in (510, 512):
            raise ValueError('Channels per universe must be 510 or 512')
        if type(start_address) is not int or not 1 <= start_address <= channels_per_universe:
            raise ValueError('Start address must be within the selected channel range')
        self.channels_per_universe = channels_per_universe
        self.first_capacity = channels_per_universe - start_address + 1
        remaining = max(0, channel_count - self.first_capacity)
        self.universes = 1 + (remaining + channels_per_universe - 1) // channels_per_universe
        if (type(start_universe) is not int or
                not minimum_universe <= start_universe <= maximum_universe - self.universes + 1):
            raise ValueError('Universe range must fit within %d to %d' %
                             (minimum_universe, maximum_universe))
        self.start_universe = start_universe
        self.start_address = start_address
        self.channel_count = channel_count

    def map(self, universe, data):
        """Return (stream offset, trimmed bytes), or None outside the range."""
        index = universe - self.start_universe
        if not 0 <= index < self.universes:
            return None
        offset = self.first_capacity + (index - 1) * self.channels_per_universe if index else 0
        skip = self.start_address - 1 if index == 0 else 0
        capacity = self.first_capacity if index == 0 else self.channels_per_universe
        count = min(capacity, self.channel_count - offset)
        return offset, bytes(data[skip:skip + count])
