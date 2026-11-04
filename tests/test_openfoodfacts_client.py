from __future__ import annotations

import json
from pathlib import Path

import pytest

from catch.sync.openfoodfacts_client import parse_off_product

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "openfoodfacts"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def test_parses_per_100g_fields_preferring_kcal_over_kj():
    result = parse_off_product(_load("nutella_found.json"))
    assert result["source"] == "off"
    assert result["name"] == "Nutella"
    assert result["brand"] == "Ferrero"
    assert result["serving_size"] == 15
    assert result["serving_unit"] == "g"
    assert result["kcal_100g"] == 539  # energy-kcal_100g used directly, not energy_100g/4.184
    assert result["protein_100g"] == pytest.approx(6.3)
    assert result["carbs_100g"] == pytest.approx(57.5)
    assert result["fat_100g"] == pytest.approx(30.9)
    assert result["fiber_100g"] == 0
    assert result["sugar_100g"] == pytest.approx(56.3)
    # OFF reports sodium in grams (0.0428g/100g) — canonical storage is milligrams.
    assert result["sodium_100g"] == pytest.approx(42.8)
    assert result["verified"] is False


def test_falls_back_to_kj_conversion_when_kcal_field_absent():
    data = _load("nutella_found.json")
    del data["product"]["nutriments"]["energy-kcal_100g"]
    result = parse_off_product(data)
    # 2252 kJ / 4.184 ~= 538.2 kcal
    assert result["kcal_100g"] == pytest.approx(538.2, abs=0.1)


def test_derives_per_100g_from_serving_basis_when_100g_fields_missing():
    result = parse_off_product(_load("serving_basis_only.json"))
    # 140 kcal / 330 (serving_quantity) * 100 ~= 42.4 kcal/100g — matches real Coca-Cola data.
    assert result["kcal_100g"] == pytest.approx(42.42, abs=0.01)
    assert result["carbs_100g"] == pytest.approx(10.6, abs=0.01)
    assert result["fat_100g"] == 0
    assert result["sodium_100g"] == 0


def test_missing_fields_stay_none_not_zero_or_crash():
    result = parse_off_product(_load("sparse_fields.json"))
    assert result["kcal_100g"] == 380
    assert result["protein_100g"] == 30
    assert result["carbs_100g"] is None
    assert result["fat_100g"] is None
    assert result["fiber_100g"] is None
    assert result["sugar_100g"] is None
    assert result["sodium_100g"] is None
    assert result["brand"] is None
    assert result["serving_size"] is None


def test_status_zero_returns_none():
    assert parse_off_product(_load("not_found.json")) is None


def test_empty_or_missing_data_returns_none():
    assert parse_off_product({}) is None
    assert parse_off_product(None) is None
