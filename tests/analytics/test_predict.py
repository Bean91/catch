from __future__ import annotations

import pytest

from catch.analytics.predict import predict_2k


def test_predict_2k_from_a_single_6k_piece():
    # Paul's law: +5s/500m per doubling of distance. 6000m is 3x 2000m (log2(3)=1.585),
    # so 2k pace = 110.0 - 5*log2(3) = 102.08 (~1:42.1), matching the task's own hand-check.
    result = predict_2k([{"distance_m": 6000, "pace_s_per_500": 110.0, "label": "6k TT"}])
    assert result["value"] == pytest.approx(102.08, abs=0.05)
    assert result["band"] == "low"
    assert len(result["components"]) == 1


def test_predict_2k_with_no_pieces():
    result = predict_2k([])
    assert result["value"] is None
    assert result["band"] == "insufficient_data"
    assert result["components"] == []


def test_predict_2k_band_improves_with_more_consistent_pieces():
    # 5k@108.0 -> 108 - 5*log2(2.5) = 101.39; 6k@110.0 -> 102.08; 10k@114.0 -> 114-5*log2(5) =
    # 102.39. Spread is exactly 1.0s (<=2.0) over 3 pieces -> "high", mean value ~101.95.
    pieces = [
        {"distance_m": 5000, "pace_s_per_500": 108.0, "label": "a"},
        {"distance_m": 6000, "pace_s_per_500": 110.0, "label": "b"},
        {"distance_m": 10000, "pace_s_per_500": 114.0, "label": "c"},
    ]
    result = predict_2k(pieces)
    assert result["band"] == "high"
    assert len(result["components"]) == 3
    assert result["value"] == pytest.approx(101.95, abs=0.05)
    assert result["range"][0] <= result["value"] <= result["range"][1]
