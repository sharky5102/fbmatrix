import dataclasses
import json
from unittest import mock

import pytest

import fbmserve


def test_state_preserves_selected_ndi_source():
    state = fbmserve.AppState('solid', input_mode='ndi', ndi_source='PC (OBS)')
    assert state.snapshot()['ndi_source'] == 'PC (OBS)'


def test_state_preserves_supersample():
    state = fbmserve.AppState('solid', supersample=4.5)
    assert state.snapshot()['supersample'] == 4.5


def test_state_file_persists_user_settings(tmp_path):
    filename = tmp_path / 'state.json'
    state = fbmserve.AppState('solid', state_file=filename)
    state.update(input_mode='ndi', ndi_source='PC (OBS)', brightness=0.4)

    saved = fbmserve.load_state_file(filename, {'solid'}, {'default'})
    assert saved['input_mode'] == 'ndi'
    assert saved['ndi_source'] == 'PC (OBS)'
    assert saved['brightness'] == 0.4
    assert 'error' not in json.loads(filename.read_text())
    assert 'ndi_status' not in json.loads(filename.read_text())


def test_state_file_syncs_contents_and_parent_directory(tmp_path, monkeypatch):
    events = []
    real_fsync = fbmserve.os.fsync
    real_replace = fbmserve.os.replace

    def fsync(fd):
        events.append('file-fsync')
        real_fsync(fd)

    def replace(source, destination):
        events.append('replace')
        real_replace(source, destination)

    monkeypatch.setattr(fbmserve.os, 'fsync', fsync)
    monkeypatch.setattr(fbmserve.os, 'replace', replace)
    monkeypatch.setattr(fbmserve, 'fsync_directory',
                        lambda directory: events.append('directory-fsync'))
    fbmserve.AppState('solid', state_file=tmp_path / 'state.json')

    assert events == ['file-fsync', 'replace', 'directory-fsync']


def test_fsync_directory_opens_syncs_and_closes_directory():
    with mock.patch.object(fbmserve.os, 'O_DIRECTORY', 0x10000, create=True), \
            mock.patch.object(fbmserve.os, 'open', return_value=42) as open_mock, \
            mock.patch.object(fbmserve.os, 'fsync') as fsync_mock, \
            mock.patch.object(fbmserve.os, 'close') as close_mock:
        fbmserve.fsync_directory('/state')

    open_mock.assert_called_once_with(
        '/state', fbmserve.os.O_RDONLY | 0x10000)
    fsync_mock.assert_called_once_with(42)
    close_mock.assert_called_once_with(42)


def test_app_state_round_trips_every_persisted_field(tmp_path):
    first_filename = tmp_path / 'first.json'
    first = fbmserve.AppState(
        'plasma', color1=[0.2, 0.4, 0.8], color2=[1, 0, 0],
        color3=[0, 0, 0], brightness=0.4, autoplay=True,
        autoplay_interval=17.5, autoplay_effects=['solid', 'plasma'],
        input_mode='ndi', ndi_source='Studio (Camera)',
        led_effect='sparkle', supersample=6.5, state_file=first_filename)
    first.update(error='temporary', ndi_status={'frames': 12})

    saved = fbmserve.load_state_file(
        first_filename, {'solid', 'plasma'}, {'default', 'sparkle'})
    second_filename = tmp_path / 'second.json'
    second = fbmserve.AppState(**saved, state_file=second_filename)

    assert json.loads(second_filename.read_text()) == json.loads(
        first_filename.read_text())
    assert {key: second.snapshot()[key] for key in second.persisted_keys()} == saved
    assert second.snapshot()['error'] is None
    assert second.snapshot()['ndi_status'] == {}


def test_app_state_persists_layout_but_keeps_it_out_of_public_snapshot(tmp_path):
    filename = tmp_path / 'state.json'
    layout = [[[0, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 1]]]
    state = fbmserve.AppState('solid', layout=layout, state_file=filename)

    assert 'layout' not in state.snapshot()
    assert state.layout_snapshot() == [
        [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
         (1.0, 0.0, 0.0, 1.0, 0.0, 1.0)]]
    assert json.loads(filename.read_text())['layout'] == layout

    saved = fbmserve.load_state_file(filename, {'solid'}, {'default'})
    restored = fbmserve.AppState(**saved)
    assert restored.layout_snapshot() == state.layout_snapshot()


def test_app_state_layout_updates_are_validated_persisted_and_copied(tmp_path):
    filename = tmp_path / 'state.json'
    state = fbmserve.AppState('solid', state_file=filename)
    layout = [[[0, 0, 0, 1, 0, 0]]]

    state.update(layout=layout)
    layout[0][0][0] = 99
    returned = state.layout_snapshot()
    returned[0][0] = (99, 0, 0, 1, 0, 0)

    assert state.layout_snapshot() == [[(0.0, 0.0, 0.0, 1.0, 0.0, 0.0)]]
    assert json.loads(filename.read_text())['layout'] == [
        [[0.0, 0.0, 0.0, 1.0, 0.0, 0.0]]]
    with pytest.raises(RuntimeError, match='must be \\[x, y, z'):
        fbmserve.AppState('solid', layout=[[[0, 0, 0]]])


def test_every_app_state_field_has_a_serialization_policy(tmp_path):
    transient = {
        item.name for item in dataclasses.fields(fbmserve.AppState)
        if not item.metadata.get('persist', True)
    }
    assert transient == {'error', 'ndi_status', 'matrix_status',
                         'network_control_status', 'state_file', 'lock'}

    filename = tmp_path / 'state.json'
    state = fbmserve.AppState('solid', state_file=filename)
    assert set(json.loads(filename.read_text())) == set(state.persisted_keys())


def test_corrupt_state_file_is_ignored(tmp_path):
    filename = tmp_path / 'state.json'
    filename.write_text('{not json')
    assert fbmserve.load_state_file(filename, {'solid'}, {'default'}) is None
