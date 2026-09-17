from dmx import DMXReceiver, _ParmrkDecoder


def test_parmrk_decoder_handles_split_markers_and_literal_ff():
    decoder = _ParmrkDecoder()
    assert list(decoder.feed(b"\xff")) == []
    assert list(decoder.feed(b"\x00")) == []
    assert list(decoder.feed(b"\x00\x00\xff")) == [
        ("break", None), ("data", 0)
    ]
    assert list(decoder.feed(b"\xff\x01")) == [
        ("data", 255), ("data", 1)
    ]


def test_parmrk_decoder_reports_errored_byte():
    decoder = _ParmrkDecoder()
    assert list(decoder.feed(b"\xff\x00\x7f")) == [("error", 0x7f)]


def test_receiver_keeps_latest_complete_buffered_frame():
    receiver = object.__new__(DMXReceiver)
    receiver._decoder = _ParmrkDecoder()
    receiver._frame = None
    break_marker = b"\xff\x00\x00"

    latest = receiver._consume(
        break_marker + b"\x00\x01" + break_marker + b"\x00\x02" + break_marker
    )

    assert latest == b"\x00\x02"


def test_read_returns_none_when_no_data_is_available(monkeypatch):
    receiver = object.__new__(DMXReceiver)
    receiver._fd = 123
    receiver._decoder = _ParmrkDecoder()
    receiver._frame = None

    def no_data(fd, size):
        raise BlockingIOError

    monkeypatch.setattr("dmx.os.read", no_data)
    assert receiver.read_dmx_frame() is None
