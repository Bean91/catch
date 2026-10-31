from __future__ import annotations

import pytest

from catch.analytics.load import ewma, training_load


def test_ewma_of_constant_series_stays_constant():
    assert ewma([50.0] * 10, window_days=7) == pytest.approx(50.0)


def test_ewma_responds_faster_with_a_shorter_window():
    series = [50.0] * 7 + [100.0] * 3
    short = ewma(series, window_days=7)
    long = ewma(series, window_days=42)
    assert short > long  # the shorter (acute) window reacts more to the recent jump


def test_training_load_ramp_up_lands_in_caution_band():
    daily_totals = [50.0] * 7 + [100.0] * 3
    result = training_load(daily_totals)
    components = result["components"][0]
    assert components["acute_7d"] == pytest.approx(78.9, abs=0.5)
    assert components["chronic_42d"] == pytest.approx(56.6, abs=0.5)
    assert result["value"] == pytest.approx(1.39, abs=0.02)
    assert result["band"] == "caution"


def test_training_load_bands():
    settings = {"load_acute_days": 7, "load_chronic_days": 42, "acr_bands": {"undertraining": 0.8, "optimal_high": 1.3, "caution_high": 1.5}}
    assert training_load([0.0], settings)["band"] == "insufficient_data"  # chronic == 0

    flat = [50.0] * 50
    assert training_load(flat, settings)["band"] == "optimal"  # acr == 1.0


def test_training_load_no_history():
    result = training_load([])
    assert result["value"] is None
    assert result["band"] == "insufficient_data"
