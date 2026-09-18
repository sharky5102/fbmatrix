import csv

import numpy as np
import pytest

import calibration_protocol as protocol


def test_loads_generated_codebook_and_uint32_preserves_words():
    words = protocol.load_codebook()
    assert len(words) == 8192
    assert len(set(words)) == len(words)
    packed = np.asarray(words, dtype=np.uint32)
    assert all(int(value) == word for value, word in zip(packed, words))


def test_emits_msb_first_and_repeats_after_one_codeword():
    word = int('101100000000000000001', 2)
    for slot in range(protocol.CODEWORD_BITS):
        time = (slot + 0.5) * protocol.SYMBOL_PERIOD_SECONDS
        bit = (word >> (protocol.CODEWORD_BITS - slot - 1)) & 1
        assert protocol.symbol_bit(word, time) == bit
        assert protocol.symbol_bit(
            word, time + protocol.CODEWORD_BITS * protocol.SYMBOL_PERIOD_SECONDS
        ) == bit


def test_rgb_uses_red_for_one_and_blue_for_zero():
    assert protocol.rgb_for_bit(0) == (0.0, 0.0, 1.0)
    assert protocol.rgb_for_bit(1) == (1.0, 0.0, 0.0)


@pytest.mark.parametrize('value', [-1, 1 << protocol.CODEWORD_BITS, True])
def test_rejects_invalid_codeword(value):
    with pytest.raises(ValueError):
        protocol.symbol_bit(value, 0.0)


def test_codebook_rejects_mismatched_hex_and_bits(tmp_path):
    path = tmp_path / 'codebook.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(('led_id', 'hex', 'bits'))
        writer.writerow((0, '0x000001', '000000000000000000010'))
    with pytest.raises(ValueError, match='disagree'):
        protocol.load_codebook(path)
