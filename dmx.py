"""Minimal Linux DMX512 receiver using termios PARMRK break detection."""

import array
import fcntl
import os
import struct
import termios
import time


# Linux termios2 definitions. Python's termios module does not expose 250000
# baud on Raspberry Pi OS, so BOTHER is required to request the exact DMX rate.
# There is no maintained Python termios2 binding that also preserves PARMRK;
# pyserial implements arbitrary Linux baud rates with these same private
# ioctls and clears PARMRK while configuring a port. Keeping the small ioctl
# implementation here avoids that dependency and the need to undo its setup.
_TCGETS2 = 0x802C542A
_TCSETS2 = 0x402C542B
_CBAUD = 0x100F
_BOTHER = 0x1000
_TERMIOS2_FORMAT = "=IIIIB19BII"
_TERMIOS2_SIZE = struct.calcsize(_TERMIOS2_FORMAT)


class _ParmrkDecoder:
    """Decode PARMRK escapes while retaining state across read boundaries."""

    NORMAL = 0
    AFTER_FF = 1
    AFTER_FF_00 = 2

    def __init__(self):
        self.state = self.NORMAL

    def feed(self, chunk):
        for byte in chunk:
            if self.state == self.NORMAL:
                if byte == 0xFF:
                    self.state = self.AFTER_FF
                else:
                    yield "data", byte
            elif self.state == self.AFTER_FF:
                if byte == 0xFF:
                    self.state = self.NORMAL
                    yield "data", 0xFF
                elif byte == 0x00:
                    self.state = self.AFTER_FF_00
                else:
                    self.state = self.NORMAL
                    yield "data", 0xFF
                    yield "data", byte
            else:
                self.state = self.NORMAL
                if byte == 0x00:
                    yield "break", None
                else:
                    yield "error", byte


def _configure_dmx(fd):
    attrs = termios.tcgetattr(fd)
    attrs[0] = termios.PARMRK | termios.INPCK
    attrs[1] = 0
    attrs[2] = termios.CS8 | termios.CSTOPB | termios.CREAD | termios.CLOCAL
    attrs[3] = 0
    attrs[4] = termios.B38400  # Replaced with BOTHER below.
    attrs[5] = termios.B38400
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSAFLUSH, attrs)

    buf = array.array("B", bytes(_TERMIOS2_SIZE))
    fcntl.ioctl(fd, _TCGETS2, buf, True)
    values = list(struct.unpack(_TERMIOS2_FORMAT, buf.tobytes()))
    values[2] = (values[2] & ~_CBAUD) | _BOTHER
    values[-2] = 250000
    values[-1] = 250000
    buf[:] = array.array("B", struct.pack(_TERMIOS2_FORMAT, *values))
    fcntl.ioctl(fd, _TCSETS2, buf)


class DMXReceiver:
    """Receive DMX frames from a Linux TTY.

    ``read_dmx_frame()`` drains the currently available input and returns the
    newest complete frame as bytes: byte 0 is the start code and the remaining
    bytes are channel slots. It returns None if no complete frame is available.
    """

    def __init__(self, tty_path):
        self._fd = os.open(tty_path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            _configure_dmx(self._fd)
            time.sleep(0.5)
            termios.tcflush(self._fd, termios.TCIFLUSH)
        except BaseException:
            os.close(self._fd)
            self._fd = -1
            raise
        self._decoder = _ParmrkDecoder()
        self._frame = None

    def _consume(self, chunk):
        latest = None
        for kind, value in self._decoder.feed(chunk):
            if kind == "break":
                if self._frame is not None:
                    latest = bytes(self._frame)
                self._frame = bytearray()
            elif kind == "data" and self._frame is not None:
                self._frame.append(value)
        return latest

    def read_dmx_frame(self):
        """Drain queued input and return its newest complete frame, or None."""
        latest = None
        while True:
            try:
                chunk = os.read(self._fd, 4096)
            except BlockingIOError:
                return latest
            if not chunk:
                # With VMIN=0, an empty TTY read can also mean "no data now".
                return latest
            completed = self._consume(chunk)
            if completed is not None:
                latest = completed

    def close(self):
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
