# Open Food Facts + USDA FoodData Central — real endpoint inventory

Session 13, task Part B. Covers the two external nutrition data sources `catch/sync/
openfoodfacts_client.py` and `catch/sync/usda_client.py` actually call — nothing below is
invented; every field mapping was checked against a real fetched response or the sources'
live docs before being coded.

## Open Food Facts (barcode lookup + free-text search)

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

### Free-text search

**Correction, confirmed by actually fetching both the live endpoint and OFF's current docs**
(an earlier pass through this file wrongly concluded OFF has no free-text search at all —
it was checking only the v2 API's own surface and missed the legacy endpoint OFF's own docs
still point to): the only OFF-operated free-text search that exists today is the **legacy**
endpoint:

```
GET /cgi/search.pl?search_terms={query}&json=1&page_size={n}&fields=code,product_name,brands,serving_size,serving_quantity,nutrition_data_per,nutriments
```

- OFF's own current docs (`openfoodfacts.github.io/openfoodfacts-server/api/`) mark full-text
  search as **"⚠ Legacy `/cgi/search.pl` only"** for API v2 and **"❌ Not available"** for v3,
  and say plain-text search "is not available in the v2 server-side API" — v2's
  `/api/v2/search` is structured/filter-based only (categories, brands, nutrients), not a
  "type a few words" box. The docs point forward to a newer **Search-a-licious** service
  (`search.openfoodfacts.org`) as where full-text search "will be available," but as of this
  research pass that site serves only a browsing UI with no documented public API endpoint —
  nothing there to integrate against yet. So `/cgi/search.pl` is the real, working option
  today, legacy label notwithstanding; confirmed live with `search_terms=banana` returning a
  real ranked `products` array (`count: 12925`, 2 real yogurt/cookie results for page_size=2).
- `fields=` narrows the response but isn't a strict whitelist — some unrequested fields
  (`nutrition_data`, `nutrition_data_prepared_per`) came back anyway in a live check, and a
  field like `serving_quantity` is simply absent from a product's object when that product
  has none, rather than appearing as `null`. Parsing code must not assume every requested
  field key is present.
- Each result object has a top-level **`code`** field (the barcode) — confirmed live, e.g.
  `"code": "6111242102941"`. Unlike the v2 product-read endpoint's `{"status": 1, "product":
  {...}}` wrapper, `/cgi/search.pl`'s response is `{"count", "page", "page_count",
  "page_size", "skip", "products": [...]}` — a flat list, no `status` field, no per-item
  wrapper.
- The `nutriments` object inside each search result uses the **same key convention** as the
  v2 product-read endpoint (confirmed live: `energy-kcal_100g`, `proteins_100g`,
  `carbohydrates_100g`, `fat_100g`, `fiber_100g`, `sugars_100g`, `sodium_100g`, with `_serving`
  variants present only on some products) — the same per-100g/per-serving/kcal-vs-kJ/
  sodium-in-grams parsing logic above applies unchanged; `catch/sync/openfoodfacts_client.py`
  shares one `_parse_off_product_fields` helper between both endpoints rather than duplicating
  it.
- **Rate limit, and why this app makes it opt-in rather than a silent fallback**: OFF's docs
  state **10 requests/minute/IP for all search queries** (`GET /api/v*/search` or `GET
  /cgi/search.pl`) — a *separate*, tighter budget than product-read's 15/min above — and
  explicitly warn: *"don't use it for a search-as-you-type feature, you would be blocked very
  quickly."* A debounced search box is still search-as-you-type (the trigger is every
  keystroke pause, not an explicit action) — reducing the debounce doesn't change that, and
  `search_foods` would reach OFF on almost every query otherwise (local+USDA rarely fill a
  20-result page). So `catch/sync/nutrition.py::search_foods` takes an `include_off: bool =
  False` parameter: the plain debounced search box never passes it, and only reaches OFF when
  the athlete taps an explicit "Also search Open Food Facts" button for that specific query.
  The coach's `log_food` tool always passes `include_off=True` — one call per tool use, never
  as-you-type, exactly what OFF's warning is fine with — which is how "both APIs" stays
  genuinely satisfied without violating the as-you-type warning anywhere else.
  `OpenFoodFactsClient.search` still enforces its own 10/min window (independent of the
  barcode-lookup limiter) and fails open (returns `[]`, never raises) when it's spent for the
  minute, as a backstop even for opted-in calls. Every hit is still cached into `foods`
  immediately, same as a barcode hit.
- No API key required for search (same as barcode lookup — OFF's docs only ask for a real
  `User-Agent` on read operations).

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
USDA free-text results appended and cached, then — only when the caller passes
`include_off=True` — OFF's legacy free-text search last, deduplicated throughout against
anything already surfaced by barcode. The plain debounced search box never opts in; the
coach's `log_food` tool always does. See "Rate limit" above for why this is opt-in rather
than a silent fallback.
