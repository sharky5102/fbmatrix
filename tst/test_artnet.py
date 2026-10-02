import json
import queue
import socket
import struct
import time
from unittest import mock

import pytest

import artnet
from matrix_buffer import PixelBuffer
from channel_mapping import ChannelMapping
from fbmserve import validate_matrix_config as validate_config
import fbmserve


def matrix_mapping(size=16, start_universe=0, channels_per_universe=510,
                   start_address=1, sink=None):
    sink = sink or PixelBuffer(size)
    return ChannelMapping(sink.channel_count, channels_per_universe, start_universe,
                          start_address, sink)


def matrix_input(size=16, start_universe=0, channels_per_universe=510, start_address=1):
    return artnet.ArtDmxInput([matrix_mapping(size, start_universe,
                                              channels_per_universe, start_address)])


def matrix_replies(ip, size, start, channels, address, targeted_range=None, node_name='fbmserve'):
    count = validate_config(size, start, channels, address)
    description = '%s %dx%d u%d %dch/univ addr%d' % (node_name, size, size, start, channels, address)
    return artnet.build_poll_replies(ip, start, count, targeted_range, node_name, description)


def sync_packet(aux=b"\0\0"):
    return b"Art-Net\0" + struct.pack("<H", artnet.OP_SYNC) + b"\0\x0e" + aux


def packet(universe=0, data=b"\x01\x02\x03\x04", opcode=0x5000):
    return (b"Art-Net\0" + struct.pack("<H", opcode) + b"\0\x0e\0\0"
            + struct.pack("<H", universe) + struct.pack(">H", len(data)) + data)


@pytest.mark.parametrize("size,count", [(16, 2), (32, 7), (64, 25)])
def test_universe_mapping(size, count):
    buffer = matrix_input(size, 256)
    assert buffer.mappings[0].universes == count
    assert buffer.update(packet(256, bytes([11]) * 512))
    assert buffer.update(packet(257, bytes([22]) * 512))
    pixels = buffer.mappings[0].sink.snapshot()
    stats = buffer.status()
    assert pixels[:510] == bytes([11]) * 510
    assert pixels[510:min(1020, len(pixels))] == bytes([22]) * min(510, len(pixels)-510)
    assert len(pixels) == size * size * 3
    assert stats['packets'] == 2
    assert buffer.update(packet(256 + count - 1, bytes([33]) * 512))
    assert buffer.mappings[0].sink.snapshot()[-3:] == bytes([33]) * 3


@pytest.mark.parametrize("bad", [b"", packet()[:17], packet()[:-1],
    packet(data=b"abc"), packet(data=b""), packet(data=bytes(514)),
    packet(opcode=0x5300), packet(2), packet(32768),
    b"Bad-Net\0" + packet()[8:], packet()[:10] + b"\0\x0d" + packet()[12:]])
def test_invalid_packets_do_not_change_pixels(bad):
    buffer = matrix_input()
    assert not buffer.update(bad)
    assert buffer.mappings[0].sink.snapshot() == bytes(16 * 16 * 3)
    assert buffer.packets == 0


def test_partial_updates_preserve_other_channels_and_universes():
    buffer = matrix_input()
    buffer.update(packet(0, bytes([9]) * 510))
    buffer.update(packet(1, bytes([8]) * 258))
    buffer.update(packet(0, b"\x01\x02"))
    pixels = buffer.mappings[0].sink.snapshot()
    assert pixels[:4] == b"\x01\x02\x09\x09"
    assert pixels[510:] == bytes([8]) * 258


def test_udp_receiver_and_shutdown():
    receiver = artnet.Receiver([matrix_mapping(16, 0, 510, 1)], port=0, host='127.0.0.1')
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(packet(), receiver.socket.getsockname())
        deadline = time.monotonic() + 2
        while receiver.status()['packets'] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert receiver.mappings[0].sink.snapshot()[:4] == b"\x01\x02\x03\x04"
    finally:
        receiver.close()
    assert not receiver.thread.is_alive()
    assert receiver.socket.fileno() == -1


def test_renderer_uploads_once_per_frame_and_reconfigures():
    state = fbmserve.AppState('solid', input_mode='network_matrix')
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    receiver = mock.Mock()
    receiver.status.return_value = {'error': None}
    receiver.mapping_status.return_value = {}
    with mock.patch.object(artnet, 'Receiver', return_value=receiver) as factory:
        renderer.render()
        renderer.render()
        factory.assert_called_once(); assert factory.call_args.kwargs['poll_broadcast'] is False; assert factory.call_args.args[0][0].sink is renderer.network_buffer
        assert renderer.network_quad.setRGB.call_count == 2
        assert renderer.network_quad.render.call_count == 2
        state.update(matrix_size=32, matrix_artnet={'port_address': 10})
        renderer.render()
        factory.assert_called_with(mock.ANY, poll_broadcast=False, node_name='fbmserve', description='fbmserve Network Control/Matrix'); assert factory.call_args.args[0][0].sink is renderer.network_buffer
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
        validate_config(size, start)


def test_state_migration_and_persistence(tmp_path):
    state = fbmserve.AppState('solid', matrix_size=64,
                              matrix_artnet={'port_address': 100})
    saved = {key: state.snapshot()[key] for key in state.persisted_keys()}
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(saved))
    assert fbmserve.load_state_file(path, {'solid'}, {'default'}) == saved
    saved['matrix_node_name'] = 'old saved name'
    del saved['matrix_channels_per_universe']
    del saved['matrix_size']
    del saved['matrix_artnet']
    path.write_text(json.dumps(saved))
    loaded = fbmserve.load_state_file(path, {'solid'}, {'default'})
    assert 'matrix_node_name' not in loaded
    assert loaded['matrix_channels_per_universe'] == 510
    assert loaded['matrix_size'] == 16
    assert loaded['matrix_artnet'] == {'port_address': 0}


def test_api_configuration():
    handler = object.__new__(fbmserve.RequestHandler)
    handler.server = mock.Mock(app_state=fbmserve.AppState('solid'))
    assert handler.normalize_state({'input_mode': 'network_matrix', 'matrix_size': 32}) == {
        'input_mode': 'network_matrix', 'matrix_size': 32,
        'matrix_artnet': {'port_address': 0}, 'matrix_sacn': {'universe': 1},
        'matrix_protocol': 'artnet',
        'matrix_channels_per_universe': 510, 'matrix_start_address': 1}
    with pytest.raises(ValueError):
        handler.normalize_state({'matrix_artnet': {'port_address': 32767}})


def test_diagnostic_rejection_reasons():
    buffer = matrix_input()
    buffer.update(packet(12))
    buffer.update(packet()[:-1])
    buffer.update(packet(opcode=0x5200))
    buffer.update(packet())
    assert buffer.diagnostics == {
        'outside_universe_range': 1, 'truncated_payload': 1,
        'sync': 1, 'accepted': 1,
    }


def test_debug_report_is_throttled_and_reports_counters(caplog):
    receiver = object.__new__(artnet.Receiver)
    artnet.ArtDmxInput.__init__(receiver, [matrix_mapping(16, 0, 510, 1)])
    receiver.next_debug = 0
    receiver.last_datagram = 'test sender'
    receiver.seen_universes = {0, 12}
    receiver.update(packet())
    with caplog.at_level('DEBUG', logger='artnet'):
        with mock.patch.object(artnet.time, 'monotonic', return_value=100):
            receiver._debug_report()
            receiver._debug_report()
        assert len(caplog.records) == 1
        assert "'accepted': 1" in caplog.text
        assert 'test sender' in caplog.text
        with mock.patch.object(artnet.time, 'monotonic', return_value=101):
            receiver._debug_report()
        assert len(caplog.records) == 2


@pytest.mark.parametrize('size,count', [(16, 2), (32, 6), (64, 24)])
def test_continuous_512_channel_packing(size, count):
    buffer = matrix_input(size, 10, channels_per_universe=512)
    expected = bytes(i % 251 for i in range(size * size * 3))
    assert buffer.mappings[0].universes == count
    # Reverse packet order also reconstructs pixels spanning two universes.
    for index in reversed(range(count)):
        data = expected[index * 512:(index + 1) * 512]
        assert buffer.update(packet(10 + index, data.ljust(512, b'\0')))
    assert buffer.mappings[0].sink.snapshot() == expected
    assert buffer.mappings[0].sink.snapshot()[510:513] == expected[510:513]
    assert not buffer.update(packet(10 + count))


@pytest.mark.parametrize('channels', [0, 511, 513, True, '512', 512.0])
def test_invalid_channel_packing(channels):
    with pytest.raises(ValueError):
        validate_config(16, 0, channels=channels)


def test_packing_changes_restart_receiver():
    state = fbmserve.AppState('solid', input_mode='network_matrix')
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    receiver = mock.Mock()
    receiver.status.return_value = {'error': None}
    receiver.mapping_status.return_value = {}
    with mock.patch.object(artnet, 'Receiver', return_value=receiver) as factory:
        renderer.render()
        state.update(matrix_channels_per_universe=512)
        renderer.render()
        receiver.close.assert_called_once()
        factory.assert_called_with(mock.ANY, poll_broadcast=False, node_name='fbmserve', description='fbmserve Network Control/Matrix'); assert factory.call_args.args[0][0].sink is renderer.network_buffer
    renderer.close()


@pytest.mark.parametrize('bad', [sync_packet()[:13], sync_packet()[:8] + b'badbad'])
def test_invalid_sync_packets_are_ignored(bad):
    buffer = matrix_input()
    assert not buffer.update(bad, source='10.0.0.1')
    assert buffer.last_sync is None
    assert buffer.mappings[0].sink.snapshot() == bytes(768)


def test_artsync_publishes_all_received_universes_together():
    buffer = matrix_input()
    source = '10.0.0.1'
    first = packet(0, bytes([10]) * 510)
    second = packet(1, bytes([20]) * 258)
    assert buffer.update(first, source)
    # Before the first ArtSync, DMX is applied immediately.
    assert buffer.mappings[0].sink.snapshot()[:510] == bytes([10]) * 510
    assert buffer.update(sync_packet(), source)
    assert buffer.update(packet(0, bytes([30]) * 510), source)
    assert buffer.update(packet(1, bytes([40]) * 258), source)
    # Neither universe is visible until the sync packet publishes the frame.
    visible = buffer.mappings[0].sink.snapshot()
    assert visible[:510] == bytes([10]) * 510
    assert visible[510:] == bytes([0]) * 258
    assert buffer.update(sync_packet(), source)
    visible = buffer.mappings[0].sink.snapshot()
    assert visible[:510] == bytes([30]) * 510
    assert visible[510:] == bytes([40]) * 258
    assert buffer.diagnostics['sync'] == 2


def test_artsync_partial_frame_preserves_unsent_universes():
    buffer = matrix_input()
    source = '10.0.0.1'
    buffer.update(packet(0, bytes([10]) * 510), source)
    buffer.update(packet(1, bytes([20]) * 258), source)
    buffer.update(sync_packet(), source)
    buffer.update(packet(0, bytes([30]) * 510), source)
    buffer.update(sync_packet(), source)
    buffer.update(packet(0, bytes([40]) * 510), source)
    buffer.update(sync_packet(), source)
    visible = buffer.mappings[0].sink.snapshot()
    assert visible[:510] == bytes([40]) * 510
    assert visible[510:] == bytes([20]) * 258


def test_artsync_from_other_controller_is_ignored():
    buffer = matrix_input()
    buffer.update(packet(0, bytes([1]) * 510), source='10.0.0.1')
    buffer.update(sync_packet(), source='10.0.0.1')
    buffer.update(packet(0, bytes([2]) * 510), source='10.0.0.1')
    assert not buffer.update(sync_packet(), source='10.0.0.2')
    assert buffer.mappings[0].sink.snapshot()[:510] == bytes([1]) * 510
    assert buffer.diagnostics['sync_source_mismatch'] == 1
    assert buffer.update(sync_packet(), source='10.0.0.1')
    assert buffer.mappings[0].sink.snapshot()[:510] == bytes([2]) * 510


def test_missing_artsync_for_four_seconds_returns_to_immediate_mode():
    buffer = matrix_input()
    source = '10.0.0.1'
    now = [0.0]
    with mock.patch.object(artnet.time, 'monotonic', side_effect=lambda: now[0]):
        buffer.update(packet(0, bytes([1]) * 510), source)
        buffer.update(sync_packet(), source)
        now[0] = 1.0
        buffer.update(packet(0, bytes([2]) * 510), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([1]) * 510
        now[0] = 4.999  # More than four seconds since the last ArtSync.
        buffer.update(packet(0, bytes([3]) * 510), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([3]) * 510
        assert buffer.last_sync is None
        assert buffer.mappings[0].sink.staging_pixels is None
        buffer.update(packet(0, bytes([4]) * 510), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([4]) * 510


def test_artsync_resumes_after_timeout_from_current_visible_frame():
    buffer = matrix_input()
    source = '10.0.0.1'
    now = [0.0]
    with mock.patch.object(artnet.time, 'monotonic', side_effect=lambda: now[0]):
        buffer.update(packet(0, bytes([1]) * 510), source)
        buffer.update(sync_packet(), source)
        now[0] = 1.0
        buffer.update(packet(0, bytes([2]) * 510), source)
        now[0] = 5.0
        buffer.update(packet(0, bytes([3]) * 510), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([3]) * 510
        # First sync after timeout restarts synchronization from visible pixels.
        buffer.update(sync_packet(), source)
        now[0] = 5.1
        buffer.update(packet(0, bytes([4]) * 510), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([3]) * 510
        buffer.update(sync_packet(), source)
        assert buffer.mappings[0].sink.snapshot()[:510] == bytes([4]) * 510


@pytest.mark.parametrize('start,count,expected', [
    (0, 2, [[0, 1]]),
    (12, 8, [[12, 13, 14, 15], [16, 17, 18, 19]]),
    (14, 25, [[14, 15], [16, 17, 18, 19], [20, 21, 22, 23],
              [24, 25, 26, 27], [28, 29, 30, 31], [32, 33, 34, 35],
              [36, 37, 38]]),
    (256, 1, [[256]]),
])
def test_poll_reply_groups_split_at_four_ports_and_subnet_boundaries(
        start, count, expected):
    assert artnet.poll_reply_groups(start, count) == expected


def poll_reply_address(reply, port_index):
    base = (reply[18] << 8) | (reply[19] << 4)
    return base | reply[190 + port_index]


def test_poll_reply_advertises_universes_and_channel_configuration():
    replies = matrix_replies(
        '192.0.2.10', 64, 14, 512, 17)
    assert len(replies) == 7
    assert all(len(reply) == artnet.ART_POLL_REPLY_SIZE for reply in replies)
    assert all(reply[:8] == artnet.ARTNET_ID for reply in replies)
    assert all(int.from_bytes(reply[8:10], 'little') == artnet.OP_POLL_REPLY
               for reply in replies)
    assert all(reply[10:14] == b'\xc0\x00\x02\x0a' for reply in replies)
    assert all(int.from_bytes(reply[14:16], 'little') == artnet.PORT
               for reply in replies)
    assert all(int.from_bytes(reply[16:18], 'big') == artnet.MIN_PROTOCOL_VERSION
               for reply in replies)
    advertised = []
    for index, reply in enumerate(replies, start=1):
        num_ports = int.from_bytes(reply[172:174], 'big')
        assert 1 <= num_ports <= 4
        assert reply[174:174 + num_ports] == bytes([0x80]) * num_ports
        assert reply[211] == index
        assert reply[212] & 0x08
        assert reply[207:211] == b'\xc0\x00\x02\x0a'
        assert b'fbmserve 64x64 u14 512ch/univ addr17' in reply[44:108]
        advertised.extend(poll_reply_address(reply, i) for i in range(num_ports))
    count = validate_config(64, 14, 512, 17)
    assert advertised == list(range(14, 14 + count))


def test_poll_reply_net_and_subnet_switches_roll_over_correctly():
    # Port-Address 0x01ff is Net 1, Sub-Net 15, Universe 15. The next
    # address crosses into Net 2/Sub-Net 0 and must start another reply.
    replies = matrix_replies('192.0.2.1', 16, 0x01ff, 510, 1)
    assert len(replies) == 2
    assert int.from_bytes(replies[0][172:174], 'big') == 1
    assert replies[0][18] == 1
    assert replies[0][19] == 15
    assert poll_reply_address(replies[0], 0) == 0x01ff
    assert int.from_bytes(replies[1][172:174], 'big') == 1
    assert replies[1][18] == 2
    assert replies[1][19] == 0
    assert poll_reply_address(replies[1], 0) == 0x0200


def test_targeted_poll_only_replies_when_range_intersects_matrix():
    args = ('192.0.2.1', 32, 14, 510, 1)
    assert matrix_replies(*args, targeted_range=(0, 13)) == []
    assert matrix_replies(*args, targeted_range=(20, 20))
    assert matrix_replies(*args, targeted_range=(14, 14))


def test_receiver_answers_artpoll_with_unicast_poll_replies():
    receiver = object.__new__(artnet.Receiver)
    artnet.ArtDmxInput.__init__(receiver, [matrix_mapping(64, 14, 510, 1)])
    receiver.node_name = 'fbmserve'
    receiver.description = None
    receiver.socket = mock.Mock()
    receiver.poll_broadcast = False
    route = mock.MagicMock()
    route.__enter__.return_value.getsockname.return_value = ('192.0.2.5', 6454)
    poll = (b'Art-Net\0' + struct.pack('<H', artnet.OP_POLL)
            + struct.pack('>H', artnet.MIN_PROTOCOL_VERSION) + b'\0\0')
    with mock.patch.object(artnet.socket, 'socket', return_value=route) as make_socket:
        assert receiver.respond_to_poll(poll, ('192.0.2.20', 6454))
    make_socket.assert_called_once_with(artnet.socket.AF_INET, artnet.socket.SOCK_DGRAM)
    route.__enter__.return_value.connect.assert_called_once_with(('192.0.2.20', 6454))
    assert receiver.socket.sendto.call_count == 7
    assert all(call.args[1] == ('192.0.2.20', 6454)
               for call in receiver.socket.sendto.call_args_list)
    assert receiver.diagnostics['poll'] == 1
    assert receiver.diagnostics['poll_replies'] == 7


def test_receiver_respects_targeted_artpoll_and_rejects_short_requests():
    receiver = object.__new__(artnet.Receiver)
    artnet.ArtDmxInput.__init__(receiver, [matrix_mapping(16, 10, 510, 1)])
    receiver.node_name = 'fbmserve'
    receiver.description = None
    receiver.socket = mock.Mock()
    receiver.poll_broadcast = False
    route = mock.MagicMock()
    route.__enter__.return_value.getsockname.return_value = ('192.0.2.5', 6454)
    with mock.patch.object(artnet.socket, 'socket', return_value=route):
        short_poll = (b'Art-Net\0' + struct.pack('<H', artnet.OP_POLL)
                      + struct.pack('>H', 14) + b'\0\0')
        assert not receiver.respond_to_poll(short_poll[:13], ('192.0.2.20', 6454))
        targeted = bytearray(short_poll + bytes(4))
        targeted[12] = artnet.ART_POLL_TARGETED
        targeted[14:16] = (9).to_bytes(2, 'big')
        targeted[16:18] = (8).to_bytes(2, 'big')
        assert receiver.respond_to_poll(bytes(targeted), ('192.0.2.20', 6454))
    receiver.socket.sendto.assert_not_called()
    assert receiver.diagnostics['short_poll'] == 1
    assert receiver.diagnostics['poll_replies'] == 0



def test_broadcast_poll_reply_targets_limited_broadcast():
    receiver = object.__new__(artnet.Receiver)
    artnet.ArtDmxInput.__init__(receiver, [matrix_mapping(16, 0, 510, 1)])
    receiver.poll_broadcast = True
    receiver.node_name = 'fbmserve'
    receiver.description = None
    receiver.socket = mock.Mock()
    route = mock.MagicMock()
    route.__enter__.return_value.getsockname.return_value = ('192.0.2.5', 6454)
    poll = (b'Art-Net\0' + struct.pack('<H', artnet.OP_POLL)
            + struct.pack('>H', artnet.MIN_PROTOCOL_VERSION) + b'\0\0')
    with mock.patch.object(artnet.socket, 'socket', return_value=route):
        assert receiver.respond_to_poll(poll, ('127.0.0.1', 6454))
    receiver.socket.sendto.assert_called_once()
    assert receiver.socket.sendto.call_args.args[1] == ('255.255.255.255', 6454)


def test_broadcast_receiver_enables_udp_broadcast():
    receiver = artnet.Receiver([matrix_mapping(16, 0, 510, 1)], port=0, host='127.0.0.1', poll_broadcast=True)
    try:
        assert receiver.socket.getsockopt(
            socket.SOL_SOCKET, socket.SO_BROADCAST) == 1
    finally:
        receiver.close()


@pytest.mark.parametrize('name', ['', 'x' * 32, 'non-ascii-\u00e9', 'bad\nname'])
def test_invalid_advertised_node_name_is_rejected(name):
    with pytest.raises(ValueError):
        artnet.validate_node_name(name)


def test_poll_reply_uses_configured_node_name():
    reply = matrix_replies(
        '192.0.2.1', 16, 0, 510, 1, node_name='Studio Matrix')[0]
    assert reply[44:108].split(b'\0', 1)[0] == b'Studio Matrix 16x16 u0 510ch/univ addr1'


def test_receiver_delivers_untrimmed_channels_to_non_pixel_sink():
    sink = mock.MagicMock(channel_count=512)
    receiver = artnet.Receiver([matrix_mapping(16, 10, 512, sink=sink)], port=0, host='127.0.0.1')
    try:
        channels = bytes(range(256)) * 2
        assert receiver.update(packet(10, channels))
        sink.write.assert_called_once_with(0, channels)
        receiver.update(sync_packet())
        sink.begin_sync.assert_called_once_with()
        receiver.update(sync_packet())
        sink.publish_sync.assert_called_once_with()
    finally:
        receiver.close()


@pytest.mark.parametrize('packing', [510, 512])
def test_start_address_applies_only_to_first_universe(packing):
    receiver = matrix_input(16, 10, packing, 4)
    receiver.update(packet(10, bytes([9, 9, 9]) + bytes([1]) * 509))
    receiver.update(packet(11, bytes([2]) * 512))
    pixels = receiver.mappings[0].sink.snapshot()
    first_capacity = packing - 3
    assert pixels[:first_capacity] == bytes([1]) * first_capacity
    assert pixels[first_capacity:] == bytes([2]) * (768 - first_capacity)
