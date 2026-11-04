from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from catch.sync import openfoodfacts_client as off_module
from catch.sync.openfoodfacts_client import OpenFoodFactsClient, parse_off_product, parse_off_search_results

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "openfoodfacts"

# Captured at import time, before tests/conftest.py's autouse `_no_live_off_search_calls`
# fixture patches `OpenFoodFactsClient.search` for every test — this file's own tests about
# `.search()`'s real behavior (parsing, rate limiting) need the real implementation back.
_REAL_SEARCH = OpenFoodFactsClient.search


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture(autouse=True)
def _reset_off_rate_limit_state():
    """The client's rate limiters are module-level lists (by design — a single uvicorn worker
    makes this safe in production, see openfoodfacts_client.py) and would otherwise leak
    calls recorded by one test into the next test's budget."""
    off_module._call_times.clear()
    off_module._search_call_times.clear()
    off_module._miss_cache.clear()
    yield
    off_module._call_times.clear()
    off_module._search_call_times.clear()
    off_module._miss_cache.clear()


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


# --- Free-text search (`/cgi/search.pl` — session 13, Part B) --------------------------------


def test_parse_search_results_extracts_barcode_and_macros_per_product():
    results = parse_off_search_results(_load("search_banana.json"))
    # Third fixture product has no product_name and is dropped.
    assert len(results) == 2
    assert results[0]["barcode"] == "6111242102941"
    assert results[0]["name"] == "Yogurt Bnine BANANA"
    assert results[0]["brand"] == "Jaouda"
    assert results[0]["kcal_100g"] == 88.1
    assert results[0]["sodium_100g"] == 0
    assert results[1]["barcode"] == "3175681272941"
    assert results[1]["fiber_100g"] == pytest.approx(7.8)
    # OFF's sodium is in grams; canonical storage is milligrams.
    assert results[1]["sodium_100g"] == pytest.approx(144, abs=0.1)


def test_parse_search_results_handles_no_products_or_missing_data():
    assert parse_off_search_results({}) == []
    assert parse_off_search_results(None) == []
    assert parse_off_search_results({"products": []}) == []


def test_client_search_parses_a_real_response_shape(monkeypatch):
    monkeypatch.setattr(OpenFoodFactsClient, "search", _REAL_SEARCH)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cgi/search.pl"
        assert request.url.params["search_terms"] == "banana"
        return httpx.Response(200, json=_load("search_banana.json"))

    client = OpenFoodFactsClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url=off_module.BASE_URL))
    results = client.search("banana", page_size=2)
    assert len(results) == 2
    assert results[0]["name"] == "Yogurt Bnine BANANA"


def test_client_search_fails_open_on_http_error(monkeypatch):
    monkeypatch.setattr(OpenFoodFactsClient, "search", _REAL_SEARCH)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = OpenFoodFactsClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url=off_module.BASE_URL))
    assert client.search("anything") == []


def test_client_search_respects_its_own_10_per_minute_budget(monkeypatch):
    monkeypatch.setattr(OpenFoodFactsClient, "search", _REAL_SEARCH)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"products": []})

    client = OpenFoodFactsClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url=off_module.BASE_URL))
    for _ in range(10):
        client.search("x")
    assert len(calls) == 10
    # The 11th call this minute is skipped (fails open to []), not sent over the wire.
    assert client.search("x") == []
    assert len(calls) == 10


def test_barcode_and_search_budgets_are_independent(monkeypatch):
    """15/min for product-read (barcode lookup) is a different, separate budget from
    10/min for search.pl — exhausting one must not affect the other."""
    monkeypatch.setattr(OpenFoodFactsClient, "search", _REAL_SEARCH)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi/search.pl":
            return httpx.Response(200, json={"products": []})
        return httpx.Response(200, json={"status": 0})

    client = OpenFoodFactsClient(http=httpx.Client(transport=httpx.MockTransport(handler), base_url=off_module.BASE_URL))
    for _ in range(10):
        client.search("x")
    # Search budget is now spent, but barcode lookup's separate 15/min budget is untouched.
    assert client.lookup_barcode("0000000000000") is None  # a real miss (status 0), not a rate-limit skip
    assert len(off_module._call_times) == 1
