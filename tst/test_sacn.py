from types import SimpleNamespace
from unittest import mock

import pytest

import fbmserve
import sacn_receiver
import queue


def test_sacn_configuration_uses_one_based_universes():
    assert sacn_receiver.validate_config(16, 1) == 2
    with pytest.raises(ValueError):
        sacn_receiver.validate_config(16, 0)
    with pytest.raises(ValueError):
        sacn_receiver.validate_config(64, 63999)


def test_receiver_subscribes_to_configured_universes_and_stops():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver') as factory:
        receiver = sacn_receiver.Receiver(16, 20)
    library_receiver = factory.return_value
    assert library_receiver.register_listener.call_count == 2
    library_receiver.join_multicast.assert_any_call(20)
    library_receiver.join_multicast.assert_any_call(21)
    library_receiver.start.assert_called_once_with()
    receiver.close()
    library_receiver.stop.assert_called_once_with()


def test_received_slots_update_matrix_buffer_and_ignore_other_start_codes():
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        receiver = sacn_receiver.Receiver(16, 1, start_address=4)
    try:
        receiver._on_packet(SimpleNamespace(
            universe=1, dmxStartCode=0, dmxData=tuple([0, 0, 0, 10, 20, 30])))
        receiver._on_packet(SimpleNamespace(
            universe=1, dmxStartCode=1, dmxData=tuple([99] * 512)))
        pixels, status = receiver.snapshot()
        assert pixels[:3] == bytes([10, 20, 30])
        assert status['packets'] == 1
        assert receiver.diagnostics['unsupported_start_code'] == 1
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
    receiver.snapshot.return_value = (pixels, {'error': None, 'packets': 1})
    with mock.patch.object(sacn_receiver, 'Receiver', return_value=receiver) as factory:
        renderer.render()
    factory.assert_called_once_with(16, 100, channels_per_universe=510,
                                    start_address=1)
    renderer.network_quad.setRGB.assert_called_once_with(pixels, 16, 16)
    renderer.network_quad.render.assert_called_once_with()
    renderer.close()


def test_debug_logs_received_universe_and_buffer(caplog):
    with mock.patch.object(sacn_receiver.sacn, 'sACNreceiver'):
        with caplog.at_level('DEBUG', logger='sacn_receiver'):
            receiver = sacn_receiver.Receiver(16, 7)
            try:
                receiver._on_packet(SimpleNamespace(
                    universe=7, dmxStartCode=0, sourceName='controller',
                    dmxData=tuple([12, 34, 56] + [0] * 509)))
            finally:
                receiver.close()
    assert 'universe=7' in caplog.text
    assert 'controller' in caplog.text
    assert 'buffer nonzero=3/768' in caplog.text
