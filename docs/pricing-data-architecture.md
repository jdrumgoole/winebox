# Wine Pricing Data Architecture

WineBox estimates retail prices for wines using a multi-source pipeline that
combines real market data with AI estimation. This document describes every
data source, MongoDB collection, and script involved.

## Data Sources

### 1. X-Wines Dataset (Reference Wine Catalogue)

- **Origin:** [github.com/rogerioxavier/X-Wines](https://github.com/rogerioxavier/X-Wines)
- **Size:** 100,646 wines with 21M+ community ratings
- **Import script:** `deploy/import_xwines_mongo.py`
- **Collection:** `xwines_wines`
- **Fields used:** name, winery_name, wine_type, grapes, ABV, country, region_name, vintages, avg_rating, rating_count

This is the reference wine catalogue. Every wine in the autocomplete, every
enrichment lookup, and every price annotation starts here. The `vintages`
field (a string like `"[2020, 2019, 2018]"`) drives per-vintage pricing.

### 2. Kaggle/Vivino Wine Prices (Real Market Data)

- **Origin:** [kaggle.com/datasets/budnyak/wine-rating-and-price](https://www.kaggle.com/datasets/budnyak/wine-rating-and-price)
- **Size:** 13,830 wines with actual retail prices from Vivino
- **Import script:** `scripts/import_kaggle_prices.py`
- **Collection:** `kaggle_wine_prices`
- **Fields:** name, winery, country, region, wine_type, rating, rating_count, price_usd, vintage
- **Price range:** $3.15 - $3,410.79 (median $15.95)

This is ground truth pricing data. The annotation script matches X-Wines
entries against this dataset by winery name and wine name. Wines with a
direct match get real Vivino prices (no LLM needed). Wines without a direct
match get Kaggle prices from the same winery/region injected as context into
the LLM prompt.

### 3. Claude Haiku API (AI Price Estimation)

- **Service:** Anthropic Claude `claude-haiku-4-5-20251001`
- **Used by:** `scripts/annotate_xwines_prices.py`
- **Purpose:** Estimates US retail prices for wines that lack real market data
- **Input:** Wine name, winery, region, grape, vintage, rating, plus Kaggle reference prices when available
- **Output:** price_low_usd, price_high_usd, price_tier, confidence, note

The LLM is the fallback for the ~81% of wines not directly matched in the
Kaggle dataset. Its accuracy improves when Kaggle reference prices from the
same winery or region are included in the prompt.

### 4. Brave Search API (Price Validation)

- **Service:** [Brave Search API](https://brave.com/search/api/)
- **Used by:** `scripts/validate_xwines_prices.py`
- **Purpose:** Spot-checks estimated prices against live retail data
- **Sources queried:** Wine-Searcher, Wine.com, Total Wine, Vivino
- **Not in the serving path** -- validation only

## MongoDB Collections

### `xwines_wines` -- Reference Wine Catalogue

| Field | Type | Description |
|-------|------|-------------|
| `xwines_id` | int | Unique wine identifier |
| `name` | string | Wine name |
| `winery_name` | string | Producer/winery |
| `wine_type` | string | Red, White, Rose, Sparkling |
| `country` | string | Country of origin |
| `region_name` | string | Wine region |
| `grapes` | string | Grape varieties (stringified list) |
| `vintages` | string | Available vintages (stringified list) |
| `avg_rating` | float | Community average rating |
| `rating_count` | int | Number of ratings |

**Written by:** `deploy/import_xwines_mongo.py`
**Read by:** xwines router (search), enrichment service, annotation script

### `xwines_prices` -- Estimated Retail Prices

| Field | Type | Description |
|-------|------|-------------|
| `xwines_id` | int | Links to `xwines_wines.xwines_id` |
| `vintage` | int or null | Vintage year; null = base/fallback price |
| `price_low_usd` | float | Lower bound of estimated price |
| `price_high_usd` | float | Upper bound of estimated price |
| `price_tier` | string | budget / value / mid_range / premium / luxury / ultra_premium |
| `confidence` | string | high / medium / low |
| `note` | string | Pricing justification |
| `model` | string | `kaggle-vivino` or `claude-haiku-4-5-20251001` |
| `created_at` | datetime | When the price was generated |

**Indexes:**
- `(xwines_id, vintage)` unique -- one price per wine-vintage pair
- `(xwines_id)` non-unique -- fast lookups for "all prices for this wine"

**Written by:** `scripts/annotate_xwines_prices.py`
**Read by:** xwines router (search + detail), enrichment service (check-in + batch)

### `kaggle_wine_prices` -- Vivino Market Reference

| Field | Type | Description |
|-------|------|-------------|
| `name` / `name_lower` | string | Wine name (original + lowercase) |
| `winery` / `winery_lower` | string | Winery name (original + lowercase) |
| `country` | string | Country |
| `region` | string | Region |
| `wine_type` | string | red / white / rose / sparkling |
| `price_usd` | float | Actual Vivino retail price |
| `vintage` | int or null | Vintage year |
| `rating` | float | Vivino rating |

**Written by:** `scripts/import_kaggle_prices.py`
**Read by:** `scripts/annotate_xwines_prices.py` (matching + context)

### `xwines_price_validations` -- Validation Results

| Field | Type | Description |
|-------|------|-------------|
| `xwines_id` | int | Wine reference |
| `vintage` | int or null | Vintage |
| `estimated_low` / `estimated_high` | float | Our estimate |
| `search_price` | float | Actual web price found |
| `source` | string | wine-searcher / wine.com / totalwine / vivino |
| `status` | string | accurate / close / overestimated / underestimated / no_data |

**Written by:** `scripts/validate_xwines_prices.py`
**Read by:** `scripts/compare_pricing_models.py`, `--report` flag

### `xwines_metadata` -- Dataset Version Tracking

Stores key-value pairs: `version`, `import_date`, `rating_count`, `source`.

**Written by:** `deploy/import_xwines_mongo.py`
**Read by:** xwines router `/stats` endpoint

## Data Flow

```
                    IMPORT PHASE
                    ============

X-Wines GitHub CSVs ──→ deploy/import_xwines_mongo.py ──→ xwines_wines (100K wines)
                                                          xwines_metadata

Kaggle Vivino CSVs  ──→ scripts/import_kaggle_prices.py ──→ kaggle_wine_prices (14K prices)


                    ANNOTATION PHASE
                    ================

                    scripts/annotate_xwines_prices.py
                              │
                    ┌─────────┴─────────┐
                    │                   │
              Kaggle Match?        No Match
              (winery+name)             │
                    │              ┌────┴────┐
                    │              │         │
                    │         Has Kaggle   No context
                    │         context?         │
                    │              │           │
                    ▼              ▼           ▼
              Use Vivino      LLM + refs   LLM only
              price ±15%      in prompt    (fallback)
                    │              │           │
                    └──────────────┴───────────┘
                              │
                              ▼
                    xwines_prices collection
                    (one doc per wine-vintage pair)


                    VALIDATION PHASE
                    ================

xwines_prices ──→ scripts/validate_xwines_prices.py ──→ Brave Search API
                                                              │
                                                              ▼
                                                    xwines_price_validations
                                                    (accuracy report)


                    SERVING PHASE
                    =============

User searches wine ──→ xwines router /search
                              │
                              ├── Atlas Search on xwines_wines
                              ├── Price filter on xwines_prices (any vintage in range)
                              └── Batch price lookup (vintage=null for base prices)
                                        │
                                        ▼
                              Search results with price_low, price_high, price_tier

User checks in wine ──→ enrichment service
                              │
                              ├── Match xwines_wines by name
                              ├── Fill missing fields (winery, grape, region, etc.)
                              └── Price lookup: vintage-specific → base price fallback
                                        │
                                        ▼
                              Enriched wine with estimated_price_low/high
```

## Price Tiers

| Tier | Range | Description |
|------|-------|-------------|
| `budget` | < $15 | Everyday wines |
| `value` | $15 - $25 | Good value picks |
| `mid_range` | $25 - $50 | Quality wines |
| `premium` | $50 - $100 | Special occasion |
| `luxury` | $100 - $250 | Collector wines |
| `ultra_premium` | > $250 | Investment-grade |

## Scripts Reference

| Script | Purpose | Run Command |
|--------|---------|-------------|
| `deploy/import_xwines_mongo.py` | Import X-Wines dataset | `uv run python deploy/import_xwines_mongo.py` |
| `scripts/import_kaggle_prices.py` | Import Kaggle/Vivino prices | `uv run python scripts/import_kaggle_prices.py --path /tmp/wine-prices` |
| `scripts/annotate_xwines_prices.py` | Generate price estimates | `uv run python scripts/annotate_xwines_prices.py` |
| `scripts/validate_xwines_prices.py` | Validate prices via web search | `uv run python scripts/validate_xwines_prices.py --sample-size 50` |
| `scripts/compare_pricing_models.py` | Compare Haiku vs Sonnet accuracy | `uv run python scripts/compare_pricing_models.py` |

### Annotation Script Options

```bash
# Dry run to see what would be processed
uv run python scripts/annotate_xwines_prices.py --dry-run

# Annotate 100 wines (popular first)
uv run python scripts/annotate_xwines_prices.py --max-wines 100

# Check progress
uv run python scripts/annotate_xwines_prices.py --status

# Estimate remaining cost
uv run python scripts/annotate_xwines_prices.py --estimate-cost

# Filter by grape variety
uv run python scripts/annotate_xwines_prices.py --grape "Pinot Noir" --max-wines 500
```

## Accuracy

Based on validation of 50 randomly sampled prices against Brave Search:

- **57% acceptable** (in estimated range or within 30%)
- **29% accurate** (web price falls within estimated range)
- **37% underestimated** (mostly prestige wines: Burgundy Grand Cru, aged Port)
- **6% overestimated**
- Kaggle-matched prices are expected to be significantly more accurate since they use real Vivino data

The underestimation bias primarily affects luxury and ultra-premium wines where
the LLM lacks specific pricing knowledge. Budget and mid-range wines are
~70-80% accurate.
