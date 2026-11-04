from __future__ import annotations

import json
from pathlib import Path

import pytest

from catch.sync.usda_client import parse_usda_branded_food

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "usda"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def test_parses_branded_food_by_exact_gtin_match():
    result = parse_usda_branded_food(_load("search_branded_cheddar.json"), "828653282457")
    assert result["source"] == "usda"
    assert result["name"] == "Cheddar Cheese"  # shouty description title-cased
    assert result["brand"] == "AMISH CLASSICS"
    assert result["serving_size"] == 28.0
    assert result["serving_unit"] == "g"
    assert result["kcal_100g"] == 432
    assert result["protein_100g"] == 25.0
    assert result["fat_100g"] == pytest.approx(35.71)
    assert result["carbs_100g"] == pytest.approx(3.57)
    assert result["fiber_100g"] == 0
    assert result["sugar_100g"] == 0
    # nutrientNumber 307 is already MG — no unit conversion needed, unlike Open Food Facts.
    assert result["sodium_100g"] == 643


def test_picks_the_exact_gtin_match_out_of_several_results():
    result = parse_usda_branded_food(_load("search_branded_multiple_results.json"), "828653282457")
    assert result["kcal_100g"] == 432  # not the 400-kcal decoy with a different gtinUpc


def test_normalizes_leading_zero_before_matching():
    # A 12-digit UPC-A scan vs. USDA's 13-digit EAN-13-form gtinUpc (or vice versa).
    result = parse_usda_branded_food(_load("search_branded_cheddar.json"), "0828653282457")
    assert result is not None
    assert result["kcal_100g"] == 432


def test_no_gtin_match_returns_none():
    result = parse_usda_branded_food(_load("search_branded_cheddar.json"), "999999999999")
    assert result is None


def test_empty_search_results_returns_none():
    assert parse_usda_branded_food(_load("search_no_match.json"), "828653282457") is None
    assert parse_usda_branded_food({}, "828653282457") is None
