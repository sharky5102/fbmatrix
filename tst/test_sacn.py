from types import SimpleNamespace
from unittest import mock

import pytest

import fbmserve
import sacn_receiver
from matrix_buffer import PixelBuffer
from fbmserve import validate_matrix_config as validate_config


class FakeSyncSocket:
    def __init__(self, bind_address, bind_port, sync_callback, maintenance_callback):
        self.handler_proxy = SimpleNamespace(handler=None)
        self.sync_callback = sync_callback
        self.maintenance_callback = maintenance_callback


@pytest.fixture(autouse=True)
def fake_sync_socket(monkeypatch):
    monkeypatch.setattr(sacn_receiver, '_SyncAwareSocket', FakeSyncSocket)


def sync_packet(universe, sequence=1):
    packet = bytearray(49)
    packet[:4] = b'\0\x10\0\0'
    packet[4:16] = b'ASC-E1.17\0\0\0'
    # Sync packets have 33 bytes in the Root Layer after the flags/length field.
    packet[16:18] = (0x7000 | 33).to_bytes(2, 'big')
    packet[18:22] = b'\0\0\0\x08'
    packet[22:38] = bytes(16)
    # The Framing Layer carries its vector and sequence/address fields (11 bytes).
    packet[38:40] = (0x7000 | 11).to_bytes(2, 'big')
    packet[40:44] = b'\0\0\0\x01'
    packet[44] = sequence
    packet[45:47] = universe.to_bytes(2, 'big')
    return bytes(packet)


def data_packet(universe, sync_address, value, force_sync=False):
    return SimpleNamespace(
        universe=universe, syncAddr=sync_address, dmxStartCode=0,
        option_ForceSync=force_sync, sourceName='test source',
        dmxData=tuple([value] * 512))
import queue


def test_sacn_configuration_uses_one_based_universes():
    assert validate_config(16, 1, protocol='sacn') == 2
    with pytest.raises(ValueError):
        validate_config(16, 0, protocol='sacn')
    with pytest.raises(ValueError):
        validate_config(64, 63999, protocol='sacn')


def test_parse_sacn_sync_packet():
    parsed = sacn_receiver.parse_sync_packet(sync_packet(23))
    assert parsed.syncAddr == 23
    assert parsed.sequence == 1
    assert sacn_receiver.parse_sync_packet(sync_packet(0)) is None
    assert sacn_receiver.parse_sync_packet(sync_packet(23)[:48]) is None
    invalid = bytearray(sync_packet(23))
    invalid[:4] = b'bad!'
    assert sacn_receiver.parse_sync_packet(invalid) is None


def test_sync_proxy_intercepts_sync_and_forwards_packets_to_library_handler():
    sync_callback = mock.Mock()
    maintenance_callback = mock.Mock()
    proxy = sacn_receiver._ReceiverHandlerProxy(sync_callback, maintenance_callback)
    proxy.handler = mock.Mock()
    packet = sync_packet(23)

    proxy.on_data(packet, 12.5)

    sync_callback.assert_called_once_with(23, 1)
    maintenance_callback.assert_called_once_with()
    proxy.handler.on_data.assert_called_once_with(packet, 12.5)


def test_receiver_subscribes_to_configured_universes_and_stops():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver') as factory:
        receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=20, start_address=1)
    library_receiver = factory.return_value
    assert library_receiver.register_listener.call_count == 2
    library_receiver.join_multicast.assert_any_call(20)
    library_receiver.join_multicast.assert_any_call(21)
    library_receiver.start.assert_called_once_with()
    receiver.close()
    library_receiver.stop.assert_called_once_with()


def test_received_slots_update_matrix_buffer_and_ignore_other_start_codes():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=1, start_address=4)
    try:
        receiver._on_packet(SimpleNamespace(
            universe=1, dmxStartCode=0, syncAddr=0, option_ForceSync=False,
            dmxData=tuple([0, 0, 0, 10, 20, 30])))
        receiver._on_packet(SimpleNamespace(
            universe=1, dmxStartCode=1, syncAddr=0, option_ForceSync=False,
            dmxData=tuple([99] * 512)))
        pixels, status = receiver.buffer.snapshot()
        assert pixels[:3] == bytes([10, 20, 30])
        assert status['packets'] == 1
        assert receiver.buffer.diagnostics['unsupported_start_code'] == 1
    finally:
        receiver.close()


def test_sync_address_holds_data_until_matching_sync_packet():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=10, start_address=1)
    try:
        receiver._on_packet(data_packet(10, 100, 10))
        assert receiver.buffer.snapshot()[0][0] == 10  # No sync stream has started yet.
        receiver._on_sync(100, 1)
        receiver._on_packet(data_packet(10, 100, 20))
        assert receiver.buffer.snapshot()[0][0] == 10
        receiver._on_sync(100, 2)
        assert receiver.buffer.snapshot()[0][0] == 20
    finally:
        receiver.close()


def test_force_sync_controls_behavior_after_sync_timeout():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=10, start_address=1)
    try:
        receiver._on_packet(data_packet(10, 101, 10, force_sync=False))
        receiver._on_sync(101, 1)
        receiver._on_packet(data_packet(10, 101, 20, force_sync=False))
        receiver.sync_last_packet -= sacn_receiver.NETWORK_DATA_LOSS_TIMEOUT + 0.1
        receiver._expire_sync_streams()
        receiver._on_packet(data_packet(10, 101, 30, force_sync=False))
        assert receiver.buffer.snapshot()[0][0] == 10
        receiver._on_sync(101, 2)
        assert receiver.buffer.snapshot()[0][0] == 30

        receiver._on_packet(data_packet(10, 101, 40, force_sync=True))
        receiver._on_sync(101, 3)
        receiver._on_packet(data_packet(10, 101, 50, force_sync=True))
        receiver.sync_last_packet -= sacn_receiver.NETWORK_DATA_LOSS_TIMEOUT + 0.1
        receiver._expire_sync_streams()
        receiver._on_packet(data_packet(10, 101, 60, force_sync=True))
        assert receiver.buffer.snapshot()[0][0] == 60
    finally:
        receiver.close()


def test_switching_sync_universe_clears_matrix_and_discards_old_pending_data():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver') as factory:
        receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=10, start_address=1)
    try:
        receiver._on_packet(data_packet(10, 100, 10))
        receiver._on_packet(data_packet(11, 100, 20))
        receiver._on_sync(100, 1)
        receiver._on_packet(data_packet(10, 100, 30))
        receiver._on_packet(data_packet(11, 100, 40))
        assert receiver.buffer.snapshot()[0][0] == 10

        receiver._on_packet(data_packet(10, 200, 50))
        pixels, _status = receiver.buffer.snapshot()
        assert receiver.sync_address == 200
        assert receiver.pending == {}
        assert pixels[:3] == bytes([50, 50, 50])
        assert pixels[510:513] == bytes(3)
        assert factory.return_value.leave_multicast.call_args_list[-1].args == (100,)

        # A late packet from the previous sync universe cannot publish anything.
        receiver._on_sync(100, 2)
        assert receiver.buffer.snapshot()[0][510:513] == bytes(3)
    finally:
        receiver.close()


def test_protocol_settings_are_nested_and_independent():
    state = fbmserve.AppState('solid', matrix_artnet={'port_address': 123},
                              matrix_sacn={'universe': 456})
    assert state.snapshot()['matrix_artnet'] == {'port_address': 123}
    assert state.snapshot()['matrix_sacn'] == {'universe': 456}
    handler = object.__new__(fbmserve.RequestHandler)
    handler.server = mock.Mock(app_state=state)
    assert handler.normalize_state({'matrix_protocol': 'sacn'}) == {
        'matrix_protocol': 'sacn', 'matrix_size': 16,
        'matrix_artnet': {'port_address': 123}, 'matrix_sacn': {'universe': 456},
        'matrix_channels_per_universe': 510, 'matrix_start_address': 1,
    }


def test_renderer_selects_sacn_receiver_and_blits_shared_buffer():
    state = fbmserve.AppState('solid', input_mode='network_matrix',
                              matrix_protocol='sacn',
                              matrix_sacn={'universe': 100})
    renderer = fbmserve.InputRenderer('', [], 32, 32, state, queue.Queue())
    renderer.network_quad = mock.Mock()
    receiver = mock.Mock()
    pixels = bytes([7] * (16 * 16 * 3))
    def make_receiver(buffer, **kwargs):
        buffer.write(0, bytes([7] * 510))
        buffer.write(510, bytes([7] * 258))
        return receiver

    with mock.patch.object(sacn_receiver, 'Receiver', side_effect=make_receiver) as factory:
        renderer.render()
    factory.assert_called_once_with(renderer.network_buffer, start_universe=100, channels_per_universe=510, start_address=1)
    renderer.network_quad.setRGB.assert_called_once_with(pixels, 16, 16)
    renderer.network_quad.render.assert_called_once_with()
    renderer.close()


def test_debug_logs_received_universe_and_counters(caplog):
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        with caplog.at_level('DEBUG', logger='sacn_receiver'):
            receiver = sacn_receiver.Receiver(PixelBuffer(16), start_universe=7, start_address=1)
            try:
                receiver._on_packet(SimpleNamespace(
                    universe=7, dmxStartCode=0, sourceName='controller',
                    syncAddr=0, option_ForceSync=False,
                    dmxData=tuple([12, 34, 56] + [0] * 509)))
            finally:
                receiver.close()
    assert 'universe=7' in caplog.text
    assert 'controller' in caplog.text
    assert "'accepted': 1" in caplog.text


def test_receiver_delivers_untrimmed_channels_to_non_pixel_sink():
    sink = mock.MagicMock(channel_count=512, channels_per_universe=512)
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        receiver = sacn_receiver.Receiver(sink, start_universe=10, channels_per_universe=512)
    try:
        data = data_packet(10, 100, 17)
        receiver._on_packet(data)
        sink.write.assert_called_once_with(0, bytes(data.dmxData))
        receiver._on_sync(100, 1)
        receiver._on_packet(data)
        receiver._on_sync(100, 2)
        sink.write_batch.assert_called_once_with([(0, bytes(data.dmxData))])
    finally:
        receiver.close()
