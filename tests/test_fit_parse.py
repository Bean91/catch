from __future__ import annotations

import types
from datetime import datetime, timezone

from catch.sync.fit_parse import parse_fit

# Fake fitdecode frames rather than a committed real .fit file — a real one carries a
# user_profile/serial_number (PII), and fitdecode's public interface (frame.name,
# frame.get_field(name).value, frame.has_field(name)) is narrow enough to fake directly.


class FakeField:
    def __init__(self, value):
        self.value = value


class FakeDataMessage:
    def __init__(self, name: str, fields: dict):
        self.name = name
        self._fields = fields

    def get_field(self, name):
        if name not in self._fields:
            raise KeyError(name)
        return FakeField(self._fields[name])

    def has_field(self, name) -> bool:
        return name in self._fields


class FakeFitReader:
    def __init__(self, frames):
        self._frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._frames)


def _patch_fitdecode(monkeypatch, frames):
    fake_module = types.SimpleNamespace(FitReader=lambda path: FakeFitReader(frames), FitDataMessage=FakeDataMessage)
    monkeypatch.setattr("catch.sync.fit_parse.fitdecode", fake_module)


def _record(ts, hr=None, power=None, cadence=None):
    return FakeDataMessage("record", {"timestamp": ts, "heart_rate": hr, "power": power, "cadence": cadence})


T0 = datetime(2026, 1, 1, 7, 0, 0, tzinfo=timezone.utc)


def test_file_id_manufacturer_not_garmin_is_peloton_like(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("file_id", {"manufacturer": "peloton"}),
        _record(T0, hr=140, power=180, cadence=85),
        _record(datetime(2026, 1, 1, 7, 0, 1, tzinfo=timezone.utc), hr=142, power=185, cadence=86),
    ]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"irrelevant - fitdecode is faked")

    result = parse_fit(path)
    assert result.is_peloton_like is True
    assert result.hr[0] == 140
    assert result.power[1] == 185


def test_file_id_manufacturer_garmin_is_not_peloton_like(monkeypatch, tmp_path):
    frames = [FakeDataMessage("file_id", {"manufacturer": "garmin"}), _record(T0, hr=140)]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    assert parse_fit(path).is_peloton_like is False


def test_missing_file_id_manufacturer_is_not_peloton_like(monkeypatch, tmp_path):
    """A FIT file with no file_id message at all (shouldn't happen, but is_peloton_like must
    not default to True on missing data — that would false-positive on every malformed file)."""
    frames = [_record(T0, hr=140)]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    assert parse_fit(path).is_peloton_like is False


def test_hr_source_type_chest_strap_wins_over_wrist(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("file_id", {"manufacturer": "garmin"}),
        FakeDataMessage("device_info", {"local_device_type": "whr"}),
        FakeDataMessage("device_info", {"local_device_type": "heart_rate"}),
        _record(T0, hr=140),
    ]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    assert parse_fit(path).hr_source_type == "chest_strap"


def test_hr_source_type_wrist_when_no_chest_strap_present(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("file_id", {"manufacturer": "garmin"}),
        FakeDataMessage("device_info", {"local_device_type": "whr"}),
        _record(T0, hr=140),
    ]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    assert parse_fit(path).hr_source_type == "wrist"


def test_hr_source_type_none_when_undetermined(monkeypatch, tmp_path):
    frames = [FakeDataMessage("file_id", {"manufacturer": "garmin"}), _record(T0, hr=140)]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    assert parse_fit(path).hr_source_type is None


def test_resample_forward_fills_short_gaps_but_not_long_ones(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("file_id", {"manufacturer": "garmin"}),
        _record(T0, hr=140),
        _record(datetime(2026, 1, 1, 7, 0, 5, tzinfo=timezone.utc), hr=150),  # 5s gap -> forward-filled
        _record(datetime(2026, 1, 1, 7, 0, 25, tzinfo=timezone.utc), hr=160),  # 20s gap -> left as real dropout
    ]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    hr = parse_fit(path).hr
    assert hr[0] == 140
    assert hr[2] == 140  # within the 10s max-fill-gap, forward-filled from the t=0 reading
    assert hr[5] == 150
    assert hr[15] is None  # beyond the max-fill-gap from the t=5 reading — a real dropout
    assert hr[25] == 160


def test_laps_extracted_with_correct_offsets(monkeypatch, tmp_path):
    frames = [
        FakeDataMessage("file_id", {"manufacturer": "garmin"}),
        _record(T0, hr=140),
        _record(datetime(2026, 1, 1, 7, 2, 0, tzinfo=timezone.utc), hr=150),
        FakeDataMessage("lap", {"start_time": T0, "total_elapsed_time": 60.0}),
        FakeDataMessage("lap", {"start_time": datetime(2026, 1, 1, 7, 1, 0, tzinfo=timezone.utc), "total_elapsed_time": 60.0}),
    ]
    _patch_fitdecode(monkeypatch, frames)
    path = tmp_path / "x.fit"
    path.write_bytes(b"x")

    laps = parse_fit(path).laps
    assert laps == [{"offset_s": 0.0, "duration_s": 60.0}, {"offset_s": 60.0, "duration_s": 60.0}]


def test_parse_fit_returns_none_for_a_missing_file(tmp_path):
    assert parse_fit(tmp_path / "does-not-exist.fit") is None


def test_parse_fit_returns_none_on_a_malformed_file(monkeypatch, tmp_path):
    def _raise(path):
        raise ValueError("not a real FIT file")

    fake_module = types.SimpleNamespace(FitReader=_raise, FitDataMessage=FakeDataMessage)
    monkeypatch.setattr("catch.sync.fit_parse.fitdecode", fake_module)
    path = tmp_path / "x.fit"
    path.write_bytes(b"garbage")

    assert parse_fit(path) is None
