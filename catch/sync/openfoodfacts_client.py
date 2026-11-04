from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("catch.nutrition.off")

BASE_URL = "https://world.openfoodfacts.org"
# OFF asks every app to identify itself — docs/nutrition-endpoints.md.
USER_AGENT = "Catch/1.0 (ben1kiev@gmail.com)"
_FIELDS = "product_name,brands,serving_size,serving_quantity,nutrition_data_per,nutriments"
_SEARCH_FIELDS = "code,product_name,brands,serving_size,serving_quantity,nutrition_data_per,nutriments"

# In-process rate limiter + negative cache (session 13, Part B). A single uvicorn worker
# (CLAUDE.md's Pi constraint) makes sharing this as plain module state safe — no DB table or
# Redis needed, and it resets harmlessly on restart. 15 req/min/IP is OFF's own documented
# limit for product reads (docs/nutrition-endpoints.md); negative-caching a miss for 24h
# means repeat scans of the same unknown barcode never themselves burn the limit.
_MAX_CALLS_PER_MINUTE = 15
_MISS_TTL_S = 24 * 3600
_call_times: list[float] = []
_miss_cache: dict[str, float] = {}

# A *separate* budget for search.pl — OFF's docs state "10 req/min/IP for all search queries
# (GET /api/v*/search or GET /cgi/search.pl)" as its own limit category, distinct from the
# 15/min product-read limit above, and explicitly warn "don't use it for a search-as-you-type
# feature, you would be blocked very quickly" (docs/nutrition-endpoints.md). This app's search
# box is debounced (250ms, frontend) rather than firing per keystroke, and silently skips (not
# raises) when this budget is spent for the minute — same fail-open shape as the barcode
# limiter above, so a burst of typing degrades to "no OFF results this call," never an error.
_SEARCH_MAX_CALLS_PER_MINUTE = 10
_search_call_times: list[float] = []


def _rate_limit_ok(call_times: list[float], max_per_minute: int) -> bool:
    now = time.monotonic()
    while call_times and now - call_times[0] > 60:
        call_times.pop(0)
    if len(call_times) >= max_per_minute:
        return False
    call_times.append(now)
    return True


def _is_known_miss(barcode: str) -> bool:
    ts = _miss_cache.get(barcode)
    return ts is not None and time.monotonic() - ts < _MISS_TTL_S


def _record_miss(barcode: str) -> None:
    _miss_cache[barcode] = time.monotonic()


class OpenFoodFactsClient:
    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=10.0, headers={"User-Agent": USER_AGENT})

    def lookup_barcode(self, barcode: str) -> dict | None:
        """A `Food`-shaped dict (source="off") or None — a miss, a rate-limit skip, and a
        request failure all return None rather than raising. A barcode scan is a fast,
        interactive flow that should fall through to the next source (USDA, then manual
        entry) on any of these, never surface a stack trace to the scanning UI."""
        if _is_known_miss(barcode):
            return None
        if not _rate_limit_ok(_call_times, _MAX_CALLS_PER_MINUTE):
            logger.warning("Open Food Facts rate limit reached (15/min); skipping lookup for %s", barcode)
            return None
        try:
            resp = self.http.get(f"/api/v2/product/{barcode}.json", params={"fields": _FIELDS})
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Open Food Facts lookup failed for %s", barcode, exc_info=True)
            return None
        parsed = parse_off_product(resp.json())
        if parsed is None:
            _record_miss(barcode)
        return parsed

    def search(self, query: str, page_size: int = 10) -> list[dict]:
        """Task Part B.3's "text search across cache + both APIs" — OFF's only free-text
        search is the legacy `/cgi/search.pl` endpoint (confirmed live: it returns real
        ranked results; OFF's own current docs call v2/v3 structured-filter-only and point
        here for full text — docs/nutrition-endpoints.md). Its own documented limit (10/min/
        IP, distinct from product-read's 15/min) and explicit "don't use this for search-as-
        you-type" warning are why this fails open (empty list, never raises) when the budget
        is spent for the minute — the caller's debounce already keeps real call volume low,
        but a burst must degrade silently, not error the search box."""
        if not _rate_limit_ok(_search_call_times, _SEARCH_MAX_CALLS_PER_MINUTE):
            logger.warning("Open Food Facts search rate limit reached (10/min); skipping search for %r", query)
            return []
        try:
            resp = self.http.get(
                "/cgi/search.pl", params={"search_terms": query, "json": "1", "page_size": page_size, "fields": _SEARCH_FIELDS}
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Open Food Facts search failed for %r", query, exc_info=True)
            return []
        return parse_off_search_results(resp.json())


def _scale_serving_to_100g(value: float | None, serving_quantity: float | None) -> float | None:
    if value is None or not serving_quantity:
        return None
    return value / serving_quantity * 100


def _parse_off_product_fields(product: dict) -> dict:
    """Shared by `parse_off_product` (one `{"product": {...}}` object, the v2 product-read
    shape) and `parse_off_search_results` (a flat list of these same per-product objects,
    `/cgi/search.pl`'s shape — confirmed live to use identical nutriment key naming, e.g.
    `proteins_100g`/`energy-kcal_100g`, since both read from the same underlying product
    database). Every macro prefers the `_100g`-suffixed nutriment; when that's missing but a
    `_serving` value and a real `serving_quantity` (grams, or grams-equivalent for a liquid —
    same ml~=g approximation `catch.analytics.nutrition.grams_for_quantity` already makes)
    both exist, it's derived by scaling (task's "nutrition_data_per can be per serving" case).
    `energy_100g` is in **kJ**, not kcal — `energy-kcal_100g` is used directly when present,
    and the kJ field is only converted as a fallback. OFF's `sodium_100g` is in **grams**;
    this app's canonical `sodium_100g` storage is milligrams (matching USDA's native unit and
    common nutrition-label convention), so OFF's value is multiplied by 1000 here."""
    nutriments = product.get("nutriments") or {}
    serving_quantity = product.get("serving_quantity")

    def per_100g(key: str) -> float | None:
        value = nutriments.get(f"{key}_100g")
        if value is not None:
            return value
        return _scale_serving_to_100g(nutriments.get(f"{key}_serving"), serving_quantity)

    kcal = nutriments.get("energy-kcal_100g")
    if kcal is None:
        energy_kj = nutriments.get("energy_100g")
        kcal = energy_kj / 4.184 if energy_kj is not None else _scale_serving_to_100g(nutriments.get("energy-kcal_serving"), serving_quantity)

    sodium_g = per_100g("sodium")
    brands = product.get("brands")
    brand = brands.split(",")[0].strip() if brands else None

    return {
        "source": "off",
        "name": product.get("product_name") or None,
        "brand": brand or None,
        "serving_size": serving_quantity,
        "serving_unit": "g",
        "kcal_100g": kcal,
        "protein_100g": per_100g("proteins"),
        "carbs_100g": per_100g("carbohydrates"),
        "fat_100g": per_100g("fat"),
        "fiber_100g": per_100g("fiber"),
        "sugar_100g": per_100g("sugars"),
        "sodium_100g": sodium_g * 1000 if sodium_g is not None else None,
        "verified": False,
    }


def parse_off_product(data: dict) -> dict | None:
    """Pure (no I/O) — exercised directly by fixture tests. `status != 1` covers both "no
    code or invalid code" and any other non-found status OFF might return."""
    if not data or data.get("status") != 1:
        return None
    product = data.get("product") or {}
    return _parse_off_product_fields(product)


def parse_off_search_results(data: dict) -> list[dict]:
    """Pure (no I/O) — exercised directly by fixture tests. `/cgi/search.pl`'s response has
    no `status` wrapper — just a flat `products` list, each one with its own top-level `code`
    (barcode), confirmed live. A result with no name at all is dropped rather than surfaced as
    an unidentifiable search hit."""
    products = (data or {}).get("products") or []
    results = []
    for product in products:
        parsed = _parse_off_product_fields(product)
        if not parsed["name"]:
            continue
        parsed["barcode"] = product.get("code") or None
        results.append(parsed)
    return results
