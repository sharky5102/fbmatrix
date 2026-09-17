"""Pure-Python reference encoder for the WS2811 optical calibration pattern."""

import math


PROTOCOL_VERSION = 1
PREAMBLE = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1)
SYMBOL_PERIOD_SECONDS = 0.1
STRING_ID_BITS = 5
PIXEL_ID_BITS = 10
CRC_BITS = 8
HEADER_BITS = 2 + STRING_ID_BITS + PIXEL_ID_BITS
PAYLOAD_BITS = HEADER_BITS + CRC_BITS
PACKET_SLOTS = len(PREAMBLE) + PAYLOAD_BITS * 2
MAX_STRING_ID = (1 << STRING_ID_BITS) - 1
MAX_PIXEL_INDEX = 999  # Physical installations currently use at most 1000 LEDs/string.


def _validate_field(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('%s must be an integer' % name)
    if value < 0 or value > maximum:
        raise ValueError('%s must be between 0 and %d' % (name, maximum))


def _bits(value, width):
    return tuple((value >> shift) & 1 for shift in range(width - 1, -1, -1))


def crc8_bits(bits):
    """CRC-8/ATM over an MSB-first bit sequence, initialized to zero."""
    crc = 0
    for bit in bits:
        if bit not in (0, 1):
            raise ValueError('CRC input must contain only bits')
        feedback = ((crc >> 7) & 1) ^ bit
        crc = (crc << 1) & 0xff
        if feedback:
            crc ^= 0x07
    return crc


def payload_bits(string_id, pixel_index, version=PROTOCOL_VERSION):
    """Return version, string ID, pixel index, and CRC bits in wire order."""
    _validate_field(version, 'version', 3)
    _validate_field(string_id, 'string ID', MAX_STRING_ID)
    _validate_field(pixel_index, 'pixel index', MAX_PIXEL_INDEX)
    header = (_bits(version, 2) + _bits(string_id, STRING_ID_BITS)
              + _bits(pixel_index, PIXEL_ID_BITS))
    return header + _bits(crc8_bits(header), CRC_BITS)


def packet_bits(string_id, pixel_index, version=PROTOCOL_VERSION):
    """Return the 66 optical slots: fixed preamble then Manchester payload."""
    payload = payload_bits(string_id, pixel_index, version)
    manchester = tuple(bit for value in payload for bit in (value, 1 - value))
    return PREAMBLE + manchester


def symbol_bit(string_id, pixel_index, elapsed_seconds,
               version=PROTOCOL_VERSION,
               symbol_period=SYMBOL_PERIOD_SECONDS):
    """Return the optical red/blue bit at elapsed controller time."""
    if (not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError('elapsed time must be a finite non-negative number')
    if (not isinstance(symbol_period, (int, float))
            or not math.isfinite(symbol_period) or symbol_period <= 0):
        raise ValueError('symbol period must be a finite positive number')
    slot = int(math.floor(elapsed_seconds / symbol_period)) % PACKET_SLOTS
    return packet_bits(string_id, pixel_index, version)[slot]


def rgb_for_bit(bit):
    """Return linear RGB: green stays on; red or blue carries the data bit."""
    if bit not in (0, 1):
        raise ValueError('optical bit must be 0 or 1')
    return (1.0, 1.0, 0.0) if bit else (0.0, 1.0, 1.0)
