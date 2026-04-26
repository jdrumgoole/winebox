# WineBox MongoDB Schema Diagram

## Collection Relationships

```
                                    ┌────────────────────┐
                                    │       users        │
                                    │────────────────────│
                                    │ _id                │
                                    │ email              │
                                    │ hashed_password    │
                                    │ is_active          │
                                    │ is_verified        │
                                    │ is_superuser       │
                                    │ full_name          │
                                    │ tokens_invalidated_after │
                                    │ last_login         │
                                    │ created_at / updated_at  │
                                    └─────────┬──────────┘
                                              │ owner_id / cellar_id
       ┌──────────────────────┬───────────────┼───────────────┬──────────────────────┐
       │                      │               │               │                      │
       ▼                      ▼               ▼               ▼                      ▼
┌─────────────────┐  ┌───────────────────┐  ┌─────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ import_batches  │  │       wines       │  │   cellars   │  │  cellar_events   │  │  transactions    │
│─────────────────│  │───────────────────│  │ (CellarItem)│  │                  │  │  (DEPRECATED)    │
│ _id             │◄─│ import_batch_id   │  │─────────────│  │──────────────────│  │──────────────────│
│ owner_id        │  │ _id               │  │ _id         │  │ _id              │  │ _id              │
│ filename        │  │ owner_id          │  │ cellar_id ──┼──┤ cellar_id        │  │ owner_id         │
│ file_type       │  │ collection        │  │ item_type   │  │ cellar_item_id ──┤  │ wine_id          │
│ status          │  │   (cellar|met)    │  │   (case|    │  │ item_type        │  │ transaction_type │
│ column_mapping  │  │ name              │  │    bottle)  │  │ event_type       │  │   (ADDED|REMOVED)│
│ file_checksum   │  │ winery / vintage  │  │ wine        │  │   (added|drunk|  │  │ quantity         │
│ headers         │  │ grape_variety     │  │   {wine_id, │  │    sold|gifted|  │  │ removal_reason   │
│ row_count       │  │ region / country  │  │    name,    │  │    breakage|     │  │ tasting_notes    │
│ preview_rows    │  │ wine_type         │  │    winery,  │  │    other)        │  │ sale_price_usd   │
│ unmapped_       │  │ wine_subtype      │  │    vintage, │  │ quantity         │  │ gift_recipient   │
│   headers       │  │ classification    │  │    grape,   │  │ wine_id          │  │ removal_notes    │
│ wines_created   │  │ price_tier        │  │    country, │  │ owner_id         │  │ transaction_date │
│ rows_skipped    │  │ estimated_price_  │  │    region,  │  │ case_size_at_    │  │ created_at       │
│ skipped_rows_   │  │   low / _high     │  │    wine_    │  │   event          │  └──────────────────┘
│   detail        │  │ drink_window_     │  │    type,    │  │ provenance_at_   │  Read-projected to
│ errors          │  │   start / _end    │  │    estimated│  │   event          │  CellarEvent via
│ imported_at     │  │ producer_type     │  │    _price_* │  │ removal_reason   │  cellar_event_view
└────────┬────────┘  │ alcohol_percentage│  │    price_   │  │ removal_notes    │
         │           │ front/back_label_ │  │    tier}    │  │ notes            │
         │ batch_id  │   text + image    │  │ (immutable) │  │ tasting_notes    │
         ▼           │ inventory{qty,    │  │ quantity    │  │ sale_price       │
┌─────────────────┐  │   case_size}      │  │ case_size   │  │ sale_price_usd   │
│  raw_uploads    │  │ grape_blends[]    │  │ purchase_   │  │ buyer            │
│─────────────────│  │ scores[]          │  │   price     │  │ gift_recipient   │
│ _id             │  │ enriched_fields[] │  │ purchase_   │  │ import_batch_id  │
│ batch_id        │  │ xwines_id ──►     │  │   date      │  │ event_date       │
│ index           │  │ cellar_wine_id ──►│  │ provenance  │  │ created_at       │
│ row (dict)      │  │ added_to_cellar   │  │ import_     │  └──────────────────┘
│ uploaded_at     │  │ custom_fields {}  │  │   batch_id  │
│ created_at      │  │ custom_fields_text│  │ created_at  │
└─────────────────┘  │ purchase_date     │  │ updated_at  │
                     │ created_at /      │  └─────────────┘
                     │   updated_at      │
                     └───────────────────┘


═══════════════════════════════════════════════════════════════════
                          PRICING
═══════════════════════════════════════════════════════════════════

┌─────────────────────────────────┐    ┌────────────────────────────────┐
│         wine_prices             │    │     wine_prices_history        │
│─────────────────────────────────│    │────────────────────────────────│
│ _id                             │    │ _id                            │
│ wine_name                       │    │ wine_name                      │
│ vintage                         │    │ vintage                        │
│ wine_type                       │    │ wine_type                      │
│ prices[] (max 20, newest last) {│    │ timestamp                      │
│   timestamp                     │    │ source                         │
│   source                        │    │ price / currency               │
│   price / currency              │◄───│ owner_id ──► users (optional)  │
│   owner_id ──► users (optional) │    │ location {ShopLocation}        │
│   location {ShopLocation}       │    │ coordinates {GeoCoordinates}   │
│   coordinates {GeoCoordinates}  │    │ notes / photo_path             │
│   notes / photo_path            │    │ capture_type                   │
│   capture_type                  │    │ archived_at                    │
│ }                               │    └────────────────────────────────┘
│ created_at / updated_at         │     Overflow archive when prices[]
└─────────────────────────────────┘     exceeds 20 entries (global, not
                                        per-owner).


═══════════════════════════════════════════════════════════════════
                    REFERENCE DATA (read-only)
═══════════════════════════════════════════════════════════════════

┌──────────────┐  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│  wine_types  │  │grape_varieties │  │ classifications │  │     regions      │
│──────────────│  │────────────────│  │─────────────────│  │──────────────────│
│ _id          │  │ _id            │  │ _id             │  │ _id              │
│ type_id      │  │ name           │  │ name            │  │ name             │
│   (e.g.'red')│  │ color          │  │ display_name    │  │ display_name     │
│ name         │  │   (red|white)  │  │ country         │  │ level (0-3)      │
│ description  │  │ category       │  │ system          │  │ parent_id ──┐    │
└──────────────┘  │ origin_country │  │ level           │  │  (self-ref) │    │
                  └────────────────┘  └─────────────────┘  │ country     │    │
                                                           │ ancestors[] │    │
┌────────────────────────────┐    ┌──────────────────┐     │ path        │    │
│      xwines_wines          │    │ xwines_metadata  │     └─────────────┘    │
│────────────────────────────│    │──────────────────│        │               │
│ _id                        │    │ _id              │        └───────────────┘
│ xwines_id (unique)         │    │ key              │     Materialized path
│ name                       │    │ value            │     for tree queries.
│ wine_type                  │    │ updated_at       │     Levels:
│ elaborate                  │    └──────────────────┘       0=country
│ grapes / harmonize         │                               1=region
│ abv / body / acidity       │                               2=subregion
│ country_code / country     │                               3=appellation
│ region_id / region_name    │
│ winery_id / winery_name    │
│ website / vintages         │
│ avg_rating / rating_count  │
│ drinkability {Estimate}    │
└────────────────────────────┘


═══════════════════════════════════════════════════════════════════
                       AUTH / SECURITY
═══════════════════════════════════════════════════════════════════

┌──────────────────────┐  ┌──────────────────────┐
│   revoked_tokens     │  │   login_attempts     │
│──────────────────────│  │──────────────────────│
│ _id                  │  │ _id                  │
│ jti (unique)         │  │ email (lowercase)    │
│ revoked_at           │  │ attempted_at         │
│ expires_at (TTL)     │  │ ip_address           │
│ user_id              │  │ failed               │
│ reason               │  └──────────────────────┘
└──────────────────────┘   Lockout: 5 failures /
 TTL: until expires_at     15min → 15min lockout.
                           Cleaned > 24h old.
```

## Summary

| Category    | Collections                                                                              | Count |
|-------------|------------------------------------------------------------------------------------------|-------|
| Cellar      | wines, cellars, cellar_events                                                            | 3     |
| Legacy      | transactions (deprecated, read-only)                                                     | 1     |
| Import      | import_batches, raw_uploads                                                              | 2     |
| Pricing     | wine_prices, wine_prices_history                                                         | 2     |
| Reference   | wine_types, grape_varieties, regions, classifications, xwines_wines, xwines_metadata     | 6     |
| Auth        | users, revoked_tokens, login_attempts                                                    | 3     |
| **Total**   |                                                                                          | **17**|

## Key Design Patterns

- **Cases as first-class items.** A case and a loose bottle are both `CellarItem` documents in the `cellars` collection, distinguished by `item_type`. There is no separate `bottles` or `cases` collection.
- **Wine descriptor embedded in cellar items.** Each `CellarItem` embeds an `EmbeddedWine` snapshot (name, winery, vintage, grape, country, region, wine_type, price tier). The descriptor is immutable for the life of the physical item — no joins needed at read time.
- **Event log on physical items.** State changes (drunk, sold, gifted, breakage) are appended to `cellar_events`. The current cellar state is `CellarItem.quantity` minus consumption events; events are the audit trail.
- **`cellar_id` = `user._id`.** The cellar collection uses `cellar_id` as the owner reference. Same for `cellar_events`.
- **Transactions are deprecated.** No live code path inserts into `transactions`. The `/api/transactions` endpoint and CSV exports are projected from `cellar_events` via `winebox.services.cellar_event_view`. The collection and model survive only so historical rows still load and the demo cleanup script keeps working. Drop is a separate ticket.
- **Multi-tenancy.** All user-facing collections filter by `owner_id` (or `cellar_id` on cellar/cellar_events). Reference collections (wine_types, grape_varieties, regions, classifications, xwines_*) are global read-only.
- **Wine collection split.** A `Wine` is either `collection="cellar"` (owned) or `collection="met"` (encountered but not owned). A met wine that gets added to the cellar gets `cellar_wine_id` linking back, plus `added_to_cellar=True`.
- **Wine prices grouped by identity, capped per document.** `WinePrice` keys on (`wine_name`, `vintage`, `wine_type`) and holds up to 20 recent observations as embedded `PriceEntry` items. Older entries overflow to `wine_prices_history` (global, not per-owner) when the cap is exceeded.
- **Materialized path on regions.** `Region` has `level` (0=country, 1=region, 2=subregion, 3=appellation), `parent_id`, `ancestors[]`, and `path` for efficient tree queries.
- **TTL indexes.** `revoked_tokens` auto-expires via `expires_at`. `login_attempts` is cleaned manually past 24h via `cleanup_old_attempts`.
- **Token bulk-revocation.** `User.tokens_invalidated_after` is bumped on password change/reset; any JWT with `iat` earlier than that timestamp is treated as revoked without needing per-token entries in `revoked_tokens`.
- **Audit trail of imports.** `import_batches` tracks the upload/map/process workflow. `raw_uploads` preserves the original row dicts even after the parent batch is deleted.
