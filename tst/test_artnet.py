import json
import queue
import socket
import struct
import time
from unittest import mock

import pytest

import artnet
import fbmserve


def packet(universe=0, data=b"\x01\x02\x03\x04", opcode=0x5000):
    return (b"Art-Net\0" + struct.pack("<H", opcode) + b"\0\x0e\0\0"
            + struct.pack("<H", universe) + struct.pack(">H", len(data)) + data)


@pytest.mark.parametrize("size,count", [(16, 2), (32, 7), (64, 25)])
def test_universe_mapping(size, count):
    buffer = artnet.PixelBuffer(size, 256)
    assert buffer.universes == count
    assert buffer.update(packet(256, bytes([11]) * 512))
    assert buffer.update(packet(257, bytes([22]) * 512))
    pixels, stats = buffer.snapshot()
    assert pixels[:510] == bytes([11]) * 510
    assert pixels[510:min(1020, len(pixels))] == bytes([22]) * min(510, len(pixels)-510)
    assert len(pixels) == size * size * 3
    assert stats['packets'] == 2
    assert buffer.update(packet(256 + count - 1, bytes([33]) * 512))
    assert buffer.snapshot()[0][-3:] == bytes([33]) * 3


@pytest.mark.parametrize("bad", [b"", packet()[:17], packet()[:-1],
    packet(data=b"abc"), packet(data=b""), packet(data=bytes(514)),
    packet(opcode=0x5200), packet(2), packet(32768),
    b"Bad-Net\0" + packet()[8:], packet()[:10] + b"\0\x0d" + packet()[12:]])
def test_invalid_packets_do_not_change_pixels(bad):
    buffer = artnet.PixelBuffer()
    assert not buffer.update(bad)
    assert buffer.snapshot()[0] == bytes(16 * 16 * 3)
    assert buffer.packets == 0


def test_partial_updates_preserve_other_channels_and_universes():
    buffer = artnet.PixelBuffer()
    buffer.update(packet(0, bytes([9]) * 510))
    buffer.update(packet(1, bytes([8]) * 258))
    buffer.update(packet(0, b"\x01\x02"))
    pixels, _ = buffer.snapshot()
    assert pixels[:4] == b"\x01\x02\x09\x09"
    assert pixels[510:] == bytes([8]) * 258


def test_udp_receiver_and_shutdown():
    receiver = artnet.Receiver(port=0, host='127.0.0.1')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(packet(), receiver.socket.getsockname())
        deadline = time.monotonic() + 2
        while receiver.snapshot()[1]['packets'] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert receiver.snapshot()[0][:4] == b"\x01\x02\x03\x04"
    finally:
        receiver.close()
    assert not receiver.thread.is_alive()
    assert receiver.socket.fileno() == -1


def test_renderer_uploads_once_per_frame_and_reconfigures():
    state = fbmserve.AppState('solid', input_mode='network_matrix')
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    receiver = mock.Mock()
    receiver.snapshot.return_value = (bytes(768), {'error': None})
    with mock.patch.object(artnet, 'Receiver', return_value=receiver) as factory:
        renderer.render()
        renderer.render()
        factory.assert_called_once_with(16, 0, channels_per_universe=510)
        assert renderer.network_quad.setRGB.call_count == 2
        assert renderer.network_quad.render.call_count == 2
        state.update(matrix_size=32, matrix_start_universe=10)
        renderer.render()
        factory.assert_called_with(32, 10, channels_per_universe=510)
        assert receiver.close.call_count == 1
        state.update(input_mode='ndi')
        renderer.render()
        assert receiver.close.call_count == 2
    renderer.close()


def test_bind_error_reported_and_retried():
    state = fbmserve.AppState('solid', input_mode='network_matrix')
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    with mock.patch.object(artnet, 'Receiver', side_effect=OSError('Port in use')) as factory:
        renderer.render()
        renderer.render()
    assert factory.call_count == 2
    assert 'Port in use' in state.error


@pytest.mark.parametrize('size,start', [(17, 0), (True, 0), (16, -1), (64, 32744), (16, 1.5)])
def test_invalid_configuration(size, start):
    with pytest.raises(ValueError):
        artnet.validate_config(size, start)


def test_state_migration_and_persistence(tmp_path):
    state = fbmserve.AppState('solid', matrix_size=64, matrix_start_universe=100)
    saved = {key: state.snapshot()[key] for key in state.persisted_keys()}
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(saved))
    assert fbmserve.load_state_file(path, {'solid'}, {'default'}) == saved
    del saved['matrix_channels_per_universe']
    del saved['matrix_size']
    del saved['matrix_start_universe']
    path.write_text(json.dumps(saved))
    loaded = fbmserve.load_state_file(path, {'solid'}, {'default'})
    assert loaded['matrix_channels_per_universe'] == 510
    assert loaded['matrix_size'] == 16
    assert loaded['matrix_start_universe'] == 0


def test_api_configuration():
    handler = object.__new__(fbmserve.RequestHandler)
    handler.server = mock.Mock(app_state=fbmserve.AppState('solid'))
    assert handler.normalize_state({'input_mode': 'network_matrix', 'matrix_size': 32}) == {
        'input_mode': 'network_matrix', 'matrix_size': 32, 'matrix_start_universe': 0, 'matrix_channels_per_universe': 510}
    with pytest.raises(ValueError):
        handler.normalize_state({'matrix_start_universe': 32767})


def test_diagnostic_rejection_reasons():
    buffer = artnet.PixelBuffer()
    buffer.update(packet(12))
    buffer.update(packet()[:-1])
    buffer.update(packet(opcode=0x5200))
    buffer.update(packet())
    assert buffer.diagnostics == {
        'outside_universe_range': 1, 'truncated_payload': 1,
        'other_opcode': 1, 'accepted': 1,
    }


def test_debug_report_is_throttled_and_reports_buffer(caplog):
    receiver = object.__new__(artnet.Receiver)
    artnet.PixelBuffer.__init__(receiver)
    receiver.next_debug = 0
    receiver.last_datagram = 'test sender'
    receiver.seen_universes = {0, 12}
    receiver.update(packet())
    with caplog.at_level('DEBUG', logger='artnet'):
        with mock.patch.object(artnet.time, 'monotonic', return_value=100):
            receiver._debug_report()
            receiver._debug_report()
        assert len(caplog.records) == 1
        assert 'buffer nonzero=4/768 peak=4' in caplog.text
        assert 'test sender' in caplog.text
        with mock.patch.object(artnet.time, 'monotonic', return_value=101):
            receiver._debug_report()
        assert len(caplog.records) == 2


@pytest.mark.parametrize('size,count', [(16, 2), (32, 6), (64, 24)])
def test_continuous_512_channel_packing(size, count):
    buffer = artnet.PixelBuffer(size, 10, channels_per_universe=512)
    expected = bytes(i % 251 for i in range(size * size * 3))
    assert buffer.universes == count
    # Reverse packet order also reconstructs pixels spanning two universes.
    for index in reversed(range(count)):
        data = expected[index * 512:(index + 1) * 512]
        assert buffer.update(packet(10 + index, data.ljust(512, b'\0')))
    assert buffer.snapshot()[0] == expected
    assert buffer.snapshot()[0][510:513] == expected[510:513]
    assert not buffer.update(packet(10 + count))


@pytest.mark.parametrize('channels', [0, 511, 513, True, '512', 512.0])
def test_invalid_channel_packing(channels):
    with pytest.raises(ValueError):
        artnet.validate_config(16, 0, channels)


def test_packing_changes_restart_receiver():
    state = fbmserve.AppState('solid', input_mode='network_matrix')
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    receiver = mock.Mock()
    receiver.snapshot.return_value = (bytes(768), {'error': None})
    with mock.patch.object(artnet, 'Receiver', return_value=receiver) as factory:
        renderer.render()
        state.update(matrix_channels_per_universe=512)
        renderer.render()
        receiver.close.assert_called_once()
        factory.assert_called_with(16, 0, channels_per_universe=512)
    renderer.close()
