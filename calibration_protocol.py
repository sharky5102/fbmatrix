"""Codebook-backed optical LED calibration signal helpers."""

import csv
import math
import os


SYMBOL_PERIOD_SECONDS = 0.1
CODEWORD_BITS = 21
CODEBOOK_FILENAME = 'codebook.csv'


def load_codebook(path=None):
    """Load and validate the generated ``led_id,hex,bits`` codebook."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), CODEBOOK_FILENAME)
    codewords = []
    with open(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['led_id', 'hex', 'bits']:
            raise ValueError('codebook.csv must have led_id,hex,bits columns')
        for expected_id, row in enumerate(reader):
            try:
                led_id = int(row['led_id'])
                bits = row['bits'].strip()
                code = int(row['hex'], 16)
            except (TypeError, ValueError) as exc:
                raise ValueError('invalid codebook row %d' % (expected_id + 2)) from exc
            if led_id != expected_id:
                raise ValueError('codebook led_id values must be sequential from 0')
            if len(bits) != CODEWORD_BITS or any(bit not in '01' for bit in bits):
                raise ValueError('codebook words must contain exactly 21 binary digits')
            if code >= (1 << CODEWORD_BITS) or code < 0:
                raise ValueError('codebook hex value does not fit in 21 bits')
            if code != int(bits, 2):
                raise ValueError('codebook hex and bits columns disagree at led_id %d' % led_id)
            codewords.append(code)
    if not codewords:
        raise ValueError('codebook is empty')
    return tuple(codewords)


def symbol_bit(codeword, elapsed_seconds,
               symbol_period=SYMBOL_PERIOD_SECONDS):
    """Return the repeating, MSB-first codebook symbol at controller time."""
    if (isinstance(codeword, bool) or not isinstance(codeword, int)
            or codeword < 0 or codeword >= (1 << CODEWORD_BITS)):
        raise ValueError('codeword must be a 21-bit non-negative integer')
    if (not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError('elapsed time must be a finite non-negative number')
    if (not isinstance(symbol_period, (int, float))
            or not math.isfinite(symbol_period) or symbol_period <= 0):
        raise ValueError('symbol period must be a finite positive number')
    slot = int(math.floor(elapsed_seconds / symbol_period)) % CODEWORD_BITS
    return (codeword >> (CODEWORD_BITS - 1 - slot)) & 1


def rgb_for_bit(bit):
    """Return linear RGB: red represents 1 and blue represents 0."""
    if bit not in (0, 1):
        raise ValueError('optical symbol must be 0 or 1')
    return (1.0, 0.0, 0.0) if bit else (0.0, 0.0, 1.0)
