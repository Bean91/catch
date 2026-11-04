from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("catch.nutrition.usda")

BASE_URL = "https://api.nal.usda.gov"
SEARCH_PATH = "/fdc/v1/foods/search"

# nutrientNumber -> our per-100g field name. `/v1/foods/search` returns a flat foodNutrients
# list (nutrientId/nutrientName/nutrientNumber/unitName/value), values per 100g — confirmed
# by arithmetic against a real response, not stated explicitly anywhere in USDA's docs
# (docs/nutrition-endpoints.md). This is deliberately the *search* endpoint's shape, not
# `/v1/food/{fdcId}`'s nested `{nutrient: {...}, amount}` shape or its separate per-serving
# `labelNutrients` object — a real gotcha the docs confirmed live: the two endpoints disagree
# on shape, and only the detail endpoint even has `labelNutrients`.
_NUTRIENT_NUMBER_MAP = {
    "208": "kcal",
    "203": "protein",
    "204": "fat",
    "205": "carbs",
    "291": "fiber",
    "269": "sugar",
    "307": "sodium_mg",  # MG, USDA's native unit — matches this app's canonical sodium_100g unit.
}


def _normalize_digits(value: str | None) -> str:
    return (value or "").lstrip("0")


class UsdaClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=10.0)

    def lookup_barcode(self, barcode: str) -> dict | None:
        """No dedicated GTIN/UPC search param exists (confirmed against the live API docs) —
        barcode search is a plain `query=<barcode>` against `dataType=Branded`, then this
        filters results to an exact (leading-zero-normalized) `gtinUpc` match rather than
        trusting the first/best text-relevance hit, which can easily be a different product
        that merely mentions the digits somewhere."""
        if not self.api_key:
            return None
        try:
            resp = self.http.get(
                SEARCH_PATH,
                params={"api_key": self.api_key, "query": barcode, "dataType": "Branded", "pageSize": 25},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("USDA lookup failed for %s", barcode, exc_info=True)
            return None
        return parse_usda_branded_food(resp.json(), barcode)

    def search(self, query: str, page_size: int = 20) -> list[dict]:
        """Free-text search across every `dataType` (not just Branded — a whole food like
        "chicken breast" has no barcode but is exactly what a text search should surface),
        used for the Nutrition page's search box. Open Food Facts has no equivalent endpoint
        (see docs/nutrition-endpoints.md), so this is the only text-search source besides the
        local cache."""
        if not self.api_key:
            return []
        try:
            resp = self.http.get(SEARCH_PATH, params={"api_key": self.api_key, "query": query, "pageSize": page_size})
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("USDA search failed for %r", query, exc_info=True)
            return []
        return parse_usda_search_results(resp.json())


def _shouty_to_title(value: str | None) -> str | None:
    if not value:
        return value
    return value.title() if value.isupper() else value


def _food_dict_from_result(match: dict) -> dict:
    nutrients: dict[str, float] = {}
    for entry in match.get("foodNutrients") or []:
        key = _NUTRIENT_NUMBER_MAP.get(str(entry.get("nutrientNumber")))
        if key and entry.get("value") is not None:
            nutrients[key] = entry["value"]

    return {
        "source": "usda",
        "barcode": match.get("gtinUpc") or None,
        "name": _shouty_to_title(match.get("description")),
        "brand": match.get("brandName") or match.get("brandOwner"),
        "serving_size": match.get("servingSize"),
        "serving_unit": match.get("servingSizeUnit"),
        "kcal_100g": nutrients.get("kcal"),
        "protein_100g": nutrients.get("protein"),
        "carbs_100g": nutrients.get("carbs"),
        "fat_100g": nutrients.get("fat"),
        "fiber_100g": nutrients.get("fiber"),
        "sugar_100g": nutrients.get("sugar"),
        "sodium_100g": nutrients.get("sodium_mg"),
        "verified": False,
    }


def parse_usda_branded_food(data: dict, barcode: str) -> dict | None:
    """Pure (no I/O) — exercised directly by fixture tests. Matches on `gtinUpc`, not
    description-text relevance; a multi-result search with only one true barcode match must
    not silently pick the wrong product."""
    foods = (data or {}).get("foods") or []
    match = next((f for f in foods if _normalize_digits(f.get("gtinUpc")) == _normalize_digits(barcode)), None)
    if match is None:
        return None
    result = _food_dict_from_result(match)
    del result["barcode"]  # the caller already knows the barcode it searched for
    return result


def parse_usda_search_results(data: dict) -> list[dict]:
    """Pure (no I/O) — every result, unfiltered by `gtinUpc` (most won't have one)."""
    foods = (data or {}).get("foods") or []
    return [_food_dict_from_result(f) for f in foods]
