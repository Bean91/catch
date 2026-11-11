import pytest

from catch.analytics.samples_codec import (
    pack_int32_delta, pack_scaled, pack_uint32, unpack_int32_delta, unpack_scaled, unpack_uint32,
)


def test_int32_delta_roundtrip_with_missing():
    vals = [450000000, 450000010, None, 450000050, -730000000, None, None, 5]
    assert unpack_int32_delta(pack_int32_delta(vals), len(vals)) == vals


def test_int32_delta_empty_blob_is_all_missing():
    assert unpack_int32_delta(None, 3) == [None, None, None]


def test_scaled_roundtrip_speed_and_altitude():
    speeds = [0.0, 2.646, None, 5.37]
    out = unpack_scaled(pack_scaled(speeds, 100), 4, 100)
    assert out[0] == 0.0 and out[1] == 2.65 and out[2] is None and out[3] == 5.37
    alts = [-12.3, 0.0, 154.7, None]
    out = unpack_scaled(pack_scaled(alts, 10, offset=500), 4, 10, offset=500)
    assert out[0] == pytest.approx(-12.3) and out[2] == pytest.approx(154.7) and out[3] is None


def test_uint32_roundtrip():
    vals = [0, 7, None, 4_000_000]
    assert unpack_uint32(pack_uint32(vals), 4) == vals
