"""

Tests for the pure EBML/WebM byte helpers in audio.recordings.

"""

import pytest

from audio.recordings import (
    WEBM_INFO_ID,
    WEBM_SEGMENT_ID,
    encode_ebml_size,
    expand_webm_segment_size,
    find_ebml_element,
    read_ebml_size,
    read_ebml_size_metadata,
)


def test_ebml_size_round_trip():
    for size_len in range(1, 9):
        encoded = encode_ebml_size(42, size_len)
        assert encoded is not None
        value, read_len, unknown = read_ebml_size_metadata(bytearray(encoded), 0)
        assert value == 42
        assert read_len == size_len
        assert unknown is False


def test_encode_ebml_size_rejects_overflow():
    assert encode_ebml_size((1 << 7) - 1, 1) is None
    assert encode_ebml_size(0, 0) is None
    assert encode_ebml_size(0, 9) is None


def test_read_ebml_size_rejects_unknown():
    with pytest.raises(ValueError):
        read_ebml_size(bytearray(b"\xff"), 0)


def test_read_ebml_size_metadata_missing():
    with pytest.raises(ValueError):
        read_ebml_size_metadata(bytearray(), 0)


def test_find_ebml_element_walks_boundaries():
    info_payload = bytes.fromhex("448988")
    info = WEBM_INFO_ID + encode_ebml_size(len(info_payload), 2) + info_payload
    segment = WEBM_SEGMENT_ID + encode_ebml_size(len(info), 8) + info
    data = bytearray(segment)

    segment_bounds = find_ebml_element(
        data, int.from_bytes(WEBM_SEGMENT_ID, "big"), 0, len(data)
    )
    assert segment_bounds is not None

    info_bounds = find_ebml_element(
        data, int.from_bytes(WEBM_INFO_ID, "big"), segment_bounds[1], segment_bounds[2]
    )
    assert info_bounds is not None
    assert not info_bounds[3]

    assert find_ebml_element(data, 0xDEAD, 0, len(data)) is None


def test_expand_webm_segment_size():
    info = WEBM_INFO_ID + encode_ebml_size(0, 8) + b"\x00"
    segment = WEBM_SEGMENT_ID + encode_ebml_size(len(info), 8) + info
    data = bytearray(segment)

    assert expand_webm_segment_size(data, 5) is True
    new_size, size_len, unknown = read_ebml_size_metadata(data, len(WEBM_SEGMENT_ID))
    assert new_size == len(info) + 5
