"""sACN Network Matrix receiver backed by the ``sacn`` PyPI package."""
import logging
import threading
import time

import sacn

from matrix_buffer import PixelBuffer, universe_count

logger = logging.getLogger(__name__)
PORT = 5568
MAX_UNIVERSE = 63999


def validate_config(size, start_universe, channels_per_universe=510, start_address=1):
    count = universe_count(size, channels_per_universe, start_address)
    if type(start_universe) is not int or not 1 <= start_universe <= MAX_UNIVERSE - count + 1:
        raise ValueError('Matrix universe range must fit within sACN universes 1 to 63999')
    return count


class Receiver(PixelBuffer):
    def __init__(self, size=16, start_universe=1, channels_per_universe=510,
                 start_address=1, bind_address='0.0.0.0'):
        validate_config(size, start_universe, channels_per_universe, start_address)
        super().__init__(size, start_universe, channels_per_universe, start_address)
        self.seen_universes = set()
        self.last_datagram = 'none'
        self.next_debug = 0.0
        self.stopped = threading.Event()
        self.receiver = sacn.sACNreceiver(bind_address=bind_address, bind_port=PORT)
        try:
            for universe in range(start_universe, start_universe + self.universes):
                self.receiver.register_listener(
                    'universe', self._on_packet, universe=universe)
                self.receiver.join_multicast(universe)
            self.receiver.start()
        except Exception:
            self.receiver.stop()
            raise
        logger.info('Listening on sACN UDP %d; matrix=%dx%d; universes=%d..%d; start channel=%d; packing=%d',
                    PORT, size, size, start_universe,
                    start_universe + self.universes - 1, start_address,
                    channels_per_universe)
        self.debug_thread = None
        if logger.isEnabledFor(logging.DEBUG):
            self.debug_thread = threading.Thread(
                target=self._debug_loop, name='sacn-debug', daemon=True)
            self.debug_thread.start()

    def _on_packet(self, packet):
        if packet.dmxStartCode != 0:
            self._reject('unsupported_start_code')
            accepted = False
        else:
            channel_offset = self.start_address - 1 if packet.universe == self.start_universe else 0
            accepted = self.update_channels(packet.universe, packet.dmxData, channel_offset)
        if logger.isEnabledFor(logging.DEBUG):
            data = packet.dmxData
            source = getattr(packet, 'sourceName', 'unknown')
            self.last_datagram = (
                'source=%r universe=%d start_code=0x%02x slots=%d nonzero=%d first12=%s accepted=%s' %
                (source, packet.universe, packet.dmxStartCode, len(data),
                 sum(value != 0 for value in data), list(data[:12]), accepted))
            if len(self.seen_universes) < 32:
                self.seen_universes.add(packet.universe)
            self._debug_report()

    def _debug_loop(self):
        while not self.stopped.wait(0.25):
            self._debug_report()

    def _debug_report(self):
        now = time.monotonic()
        if now < self.next_debug:
            return
        self.next_debug = now + 1.0
        pixels, status = self.snapshot()
        logger.debug('RX totals=%s; observed universes (up to 32)=%s; last datagram: %s; '
                     'buffer nonzero=%d/%d peak=%d last accepted age=%s',
                     dict(self.diagnostics), sorted(self.seen_universes)[:32],
                     self.last_datagram, sum(value != 0 for value in pixels),
                     len(pixels), max(pixels),
                     None if status['age'] is None else round(status['age'], 2))

    def close(self):
        self.stopped.set()
        self.receiver.stop()
        if self.debug_thread is not None:
            self.debug_thread.join()
