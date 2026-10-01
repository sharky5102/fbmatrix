"""Receiver-side mapping from DMX universes to a sequential channel stream."""


class ChannelMapping:
    def __init__(self, channel_count, channels_per_universe, start_universe,
                 start_address, sink):
        if type(channel_count) is not int or channel_count < 1:
            raise ValueError('Channel count must be a positive integer')
        if type(channels_per_universe) is not int or channels_per_universe not in (510, 512):
            raise ValueError('Channels per universe must be 510 or 512')
        if type(start_address) is not int or not 1 <= start_address <= channels_per_universe:
            raise ValueError('Start address must be within the selected channel range')
        self.channels_per_universe = channels_per_universe
        self.first_capacity = channels_per_universe - start_address + 1
        required = self.required_universes(channel_count, channels_per_universe, start_address)
        if type(start_universe) is not int or not 0 <= start_universe <= 63999 - required + 1:
            raise ValueError('Universe range must fit within 0 to 63999')
        self.universe_numbers = tuple(range(start_universe, start_universe + required))
        self.universe_indices = {number: index for index, number in enumerate(self.universe_numbers)}
        self.universes = required
        self.start_universe = start_universe
        self.end_universe = start_universe + required - 1
        self.start_address = start_address
        self.channel_count = channel_count
        self.sink = sink

    @staticmethod
    def required_universes(channel_count, channels_per_universe, start_address):
        if type(channel_count) is not int or channel_count < 1:
            raise ValueError('Channel count must be a positive integer')
        if type(channels_per_universe) is not int or channels_per_universe not in (510, 512):
            raise ValueError('Channels per universe must be 510 or 512')
        if type(start_address) is not int or not 1 <= start_address <= channels_per_universe:
            raise ValueError('Start address must be within the selected channel range')
        first_capacity = channels_per_universe - start_address + 1
        remaining = max(0, channel_count - first_capacity)
        return 1 + (remaining + channels_per_universe - 1) // channels_per_universe

    def map(self, universe, data):
        """Return (stream offset, trimmed bytes), or None outside the range."""
        index = self.universe_indices.get(universe)
        if index is None:
            return None
        offset = self.first_capacity + (index - 1) * self.channels_per_universe if index else 0
        skip = self.start_address - 1 if index == 0 else 0
        capacity = self.first_capacity if index == 0 else self.channels_per_universe
        count = min(capacity, self.channel_count - offset)
        return offset, bytes(data[skip:skip + count])

    def deliver(self, universe, data):
        change = self.map(universe, data)
        return False if change is None else self.sink.write(*change)

    def deliver_batch(self, changes):
        self.sink.write_batch(changes)

    def begin_sync(self):
        self.sink.begin_sync()

    def publish_sync(self):
        self.sink.publish_sync()

    def end_sync(self):
        self.sink.end_sync()

    def clear(self):
        self.sink.clear()
