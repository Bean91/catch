# Open Food Facts + USDA FoodData Central — real endpoint inventory

Session 13, task Part B. Covers the two external nutrition data sources `catch/sync/
openfoodfacts_client.py` and `catch/sync/usda_client.py` actually call — nothing below is
invented; every field mapping was checked against a real fetched response or the sources'
live docs before being coded.

## Open Food Facts (barcode lookup only — see "No free-text search" below)

Base URL: `https://world.openfoodfacts.org`. No API key. OFF's own usage policy asks every
app to identify itself with a real `User-Agent`: this app sends
`Catch/1.0 (ben1kiev@gmail.com)`.

```
GET /api/v2/product/{barcode}.json?fields=product_name,brands,serving_size,serving_quantity,nutrition_data_per,nutriments
```

- `fields` is limited to exactly what this app uses — OFF's v2 product object is huge
  (images, languages, packaging, ingredient-analysis tags, …) and none of the rest is read.
- Response shape: `{"status": 1, "product": {...}}` on a hit; `status` is `0` (or the key is
  simply the product not being found) on a miss. Both a missing product and any other
  non-1 status are treated as "not found" — never raise on this, since a barcode scan is a
  fast interactive flow that should fall through to USDA, then manual entry.
- `product.nutriments` holds every macro, each normally as a `{key}_100g` value — but a
  product can instead (or additionally) report `{key}_serving`, scaled to the product's own
  `serving_quantity` (grams; OFF's docs call out that `nutrition_data_per` can be `"serving"`
  rather than `"100g"`). This app prefers `_100g` and derives it from `_serving` +
  `serving_quantity` only when `_100g` is absent.
- **Energy is reported in kJ** (`energy_100g`), not kcal, unless `energy-kcal_100g` is also
  present (OFF usually includes both). This app uses `energy-kcal_100g` directly when it
  exists and only converts the kJ figure (÷ 4.184) as a fallback.
- **`sodium_100g` is in grams**, not milligrams — this app's own canonical `sodium_100g`
  column stores milligrams (matching USDA's native unit, and standard nutrition-label
  convention), so every OFF sodium value is multiplied by 1000 on the way in.
- Rate limit: OFF's documented limit for product-read endpoints is **15 requests/minute per
  IP**. `OpenFoodFactsClient` enforces this itself with an in-process sliding window (a
  single uvicorn worker, per CLAUDE.md's Pi constraint, makes plain module-level state safe
  here — no DB table or Redis needed) and negative-caches a miss for 24h so repeat scans of
  the same unknown barcode never themselves burn the limit.

### No free-text search

OFF's v2 API has **no plain free-text search endpoint** — confirmed against OFF's own API
docs, not assumed. What exists is barcode-exact lookup (above) and a separate structured
search API (`/api/v2/search` or the Algolia-backed search-a-licious service) built around
faceted category/brand/nutrient filters, not a "type a few words, get ranked results" box.
Neither fits this app's search-as-you-type UI. Given this, OFF's contribution to the app
stays **barcode-scan lookup only**; all free-text search (`GET /api/nutrition/search`) goes
through USDA FoodData Central instead (below). This is a deliberate scope decision, not a
missing feature — if OFF ships a real free-text endpoint in the future, it would need its
own research pass before adding it here.

### Attribution

OFF's data is licensed under the Open Database License (ODbL) — this app credits it in the
nutrition UI with "Contains data from Open Food Facts, available under the Open Database
License," wherever an OFF-sourced food is shown.

## USDA FoodData Central

Base URL: `https://api.nal.usda.gov`. Needs `USDA_FDC_API_KEY` (`.env`) — get a free key at
https://fdc.nal.usda.gov/api-key-signup. Without a key configured, every USDA call is simply
skipped (barcode lookup falls through to manual entry; search returns only local-cache
results) — see `tests/conftest.py`'s `_no_live_usda_calls` autouse fixture, which forces this
path in the test suite so a real key in the dev `.env` never makes live calls during `pytest`.

```
GET /fdc/v1/foods/search?api_key={key}&query={q}&dataType=Branded&pageSize={n}
```

- Used for **both** barcode lookup and free-text search — there is no dedicated GTIN/UPC
  lookup endpoint (confirmed against the live API docs). Barcode lookup passes the barcode
  itself as `query` with `dataType=Branded`, then filters the result list to an exact,
  leading-zero-normalized `gtinUpc` match — never trusts the first/best text-relevance hit,
  which can easily be an unrelated product that happens to mention the same digits somewhere
  in its description. Free-text search (no `dataType` filter — a whole food like "chicken
  breast" has no barcode and no Branded entry, but is exactly what a search box should
  surface) takes every result as-is.
- **The search endpoint's `foodNutrients` shape differs from the detail endpoint's.**
  `/v1/foods/search` returns a flat list of `{nutrientId, nutrientName, nutrientNumber,
  unitName, value}` objects, values **per 100g** (confirmed by arithmetic against a real
  response — not stated explicitly anywhere in USDA's own docs). `/v1/food/{fdcId}` (the
  single-item detail endpoint — not currently called by this app) instead nests nutrients as
  `{nutrient: {...}, amount}` and additionally exposes a separate per-serving
  `labelNutrients` object that the search endpoint doesn't have at all. This app only uses
  the search endpoint, so only the flat per-100g shape applies; don't assume the detail
  endpoint's shape if `/v1/food/{fdcId}` is ever added later.
- Nutrient numbers mapped (by `nutrientNumber`, the standardized USDA code — stable across
  foods, unlike `nutrientId` which is a per-row database id):

  | `nutrientNumber` | Field |
  |---|---|
  | `208` | kcal |
  | `203` | protein (g) |
  | `204` | fat (g) |
  | `205` | carbs (g) |
  | `291` | fiber (g) |
  | `269` | sugar (g) |
  | `307` | sodium (**mg** — USDA's native unit, matches this app's canonical storage unit) |

- `servingSize`/`servingSizeUnit` on a Branded result give the product's labeled serving
  (e.g. `30` + `"g"`); not every result has one.
- `description` is frequently all-caps for Branded foods (e.g. `"CHOCOLATE CHIP GRANOLA
  BAR"`) — this app title-cases an all-caps description for display, but leaves a normally-
  cased one untouched (some brand names are legitimately mixed-case already).
- No documented rate limit beyond the default API key tier (1,000 requests/hour) — not
  separately throttled by this app the way OFF is, since that ceiling is far above any
  plausible single-user usage.

## Lookup order (task Part B.3)

`lookup_or_fetch_barcode` (`catch/sync/nutrition.py`): local `foods` cache (any source,
including a prior OFF/USDA hit or a manual entry) → Open Food Facts → USDA FoodData Central
(only if `USDA_FDC_API_KEY` is set) → `None` (the caller falls back to a manual-entry form
prefilled with the scanned barcode). A found external result is cached into `foods`
immediately, so a repeat scan of the same barcode never re-hits either API.

`search_foods`: local cache (ranked by recency/frequency of use in `food_logs`) first, then
USDA free-text results appended and cached, deduplicated against anything the local cache
already surfaced by barcode. OFF never participates in search (see above).
