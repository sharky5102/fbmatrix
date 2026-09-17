import pytest

import calibration_protocol as protocol


def test_crc8_atm_standard_check_value():
    bits = tuple(
        (byte >> shift) & 1
        for byte in b'123456789'
        for shift in range(7, -1, -1)
    )
    assert protocol.crc8_bits(bits) == 0xF4


def test_packet_shape_and_manchester_encoding():
    bits = protocol.packet_bits(string_id=3, pixel_index=742)
    assert len(bits) == 66
    assert bits[:16] == protocol.PREAMBLE
    encoded_payload = bits[16:]
    assert len(encoded_payload) == 50
    assert all(encoded_payload[i] != encoded_payload[i + 1]
               for i in range(0, 50, 2))
    assert protocol.payload_bits(3, 742)[:17] == (
        (0, 1) + (0, 0, 0, 1, 1) + (1, 0, 1, 1, 1, 0, 0, 1, 1, 0)
    )


def test_symbol_timing_repeats_without_an_external_trigger():
    bits = protocol.packet_bits(4, 917)
    for slot, bit in enumerate(bits):
        t = (slot + 0.25) * protocol.SYMBOL_PERIOD_SECONDS
        assert protocol.symbol_bit(4, 917, t) == bit
        assert protocol.symbol_bit(
            4, 917, t + protocol.PACKET_SLOTS * protocol.SYMBOL_PERIOD_SECONDS
        ) == bit


@pytest.mark.parametrize('string_id,pixel_index', [
    (-1, 0), (32, 0), (0, -1), (0, 1000), (0, 1024),
])
def test_rejects_ids_outside_current_system_limits(string_id, pixel_index):
    with pytest.raises(ValueError):
        protocol.packet_bits(string_id, pixel_index)


def test_green_tracking_component_is_constant_for_both_bits():
    assert protocol.rgb_for_bit(0) == (0.0, 1.0, 1.0)
    assert protocol.rgb_for_bit(1) == (1.0, 1.0, 0.0)
