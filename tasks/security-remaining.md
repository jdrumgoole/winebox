# Security Remediation Plan — items remaining after 2026-04-17 cheap-wins

This is the worked plan for the items in `docs/security-reports/2026-04-17.md`
that were *not* in the cheap-wins commit (`1919e8e`). Items #4, #11, #12, #15,
#20, #33 and the three CRITICALs are already fixed on `main`.

Group ordering reflects suggested execution order — biggest user-facing risk
first within each tier.

---

## Tier 1 — privacy / auth correctness (do next)

### A. Fix price tracker PII leak (Warning #5)
- **Files:** `winebox/routers/price_tracker.py`
- **Function:** `_entry_to_out` (lines 54–84) and its callers
  (`_wine_price_to_out`, `get_wine_price`, list endpoints).
- **Approach:** thread `current_user.id` into `_entry_to_out` so it can return
  the full record only when `entry.owner_id == current_user.id`. For other
  users' entries return `price`, `currency`, `timestamp`, `shop_name`,
  `country` only — drop `owner_id`, `coordinates`, `town_city`,
  `state_county`, `notes`, `photo_url`. Optional: fuzz coordinates to ~1 km
  for own-entries display if we ever expose them on a public map (out of
  scope here).
- **Tests:** add `test_price_tracker_entry_redacts_other_users` —
  user A creates an entry, user B fetches the same wine_price, asserts B sees
  `owner_id is None`, `coordinates is None`, `notes is None`, `photo_url is
  None`, but A still sees them all on their own entry.
- **Effort:** ~30 min including test.

### B. Full token invalidation on password change + reset (Warnings #6, #7)
- **Files:**
  - `winebox/routers/auth.py:170-178` (only revokes current session token)
  - `winebox/auth/users.py:90-94` (`on_after_reset_password` revokes nothing)
  - `winebox/cli/user_admin.py:172-185` (admin password reset revokes nothing)
- **Approach:** add a `revoke_all_user_tokens(user_id, reason)` helper to
  `winebox/services/auth.py` that bumps a per-user `tokens_invalidated_after`
  timestamp on the User document. Then `get_current_user` rejects any token
  whose `iat` (issued-at) is older than that timestamp.
  - This avoids enumerating every live `jti` (we only have the blacklist
    populated for explicit revocations).
  - Add `iat` to the JWT payload in `create_access_token` (currently only
    `exp` and `jti` — see `winebox/services/auth.py:46-57`).
  - Add `tokens_invalidated_after: datetime | None = None` to the User model.
  - In `get_current_user`, if `user.tokens_invalidated_after` is set and
    `payload['iat'] < user.tokens_invalidated_after`, return None.
  - Wire it into all three call sites (password change, reset, admin reset).
- **Tests:** for each of the three flows: log in, capture token, trigger the
  flow, assert the original token now returns 401 from `/api/auth/me`.
- **Effort:** ~2 hours.

### C. XSS audit + fix in app.js (Warning #8)
- **File:** `winebox/static/js/app.js`
- **Approach:** grep for every `innerHTML =` and `${` in template-string
  contexts that interpolate wine fields (`wine.name`, `wine.notes`,
  `wine.tags`, etc.) and `entry.shop_name` etc. Wrap with `escapeHtml()`.
  Pay special attention to attribute contexts like `alt="${wine.name}"` at
  line ~2561 (use `escapeAttr` if separate, else `escapeHtml`).
- **Verify:** add a Playwright e2e test that creates a wine with name
  `<img src=x onerror=alert(1)>` and asserts no alert fires on the cellar
  page, search results, activity feed, and detail view.
- **Effort:** ~1–2 hours including e2e.

---

## Tier 2 — DoS hardening (do this week)

### D. Rate limit fastapi-users auth endpoints (Warning #9)
- **File:** `winebox/routers/auth.py:42-65`
- **Issue:** `/login`, `/register`, `/forgot-password`, `/reset-password`,
  `/request-verify-token`, `/verify` only get the global 60/min limit.
- **Approach:** wrap each fastapi-users router in a thin local router whose
  endpoints `@limiter.limit(...)`-decorate the underlying handlers, **or**
  switch to `slowapi`'s middleware-style limit on path patterns. Suggested
  per-endpoint limits (match the custom `/api/auth/token` 30/min where
  applicable):
  - `/login`: 30/minute
  - `/register`: 10/minute, 50/hour (creation is expensive — argon2 hash)
  - `/forgot-password`, `/reset-password`: 5/minute, 20/hour
  - `/request-verify-token`, `/verify`: 5/minute, 30/hour
- **Tests:** for each, hammer 1 over the limit and assert 429.
- **Effort:** ~1 hour.

### E. Rate limit expensive endpoints (Warning #10)
- **Endpoints:** `/api/wines/scan`, `/api/wines/enrich`, `/api/search`,
  `/api/xwines/search`, `/api/xwines/export`, `/api/export/*`,
  `/api/import/upload`, `/api/demo/install`, `POST /api/prices`.
- **Approach:** apply per-user limits via slowapi. Suggested floors:
  - `scan`, `enrich`: 20/minute (Anthropic-bound, cost-bound)
  - `search`, `xwines/search`: 60/minute
  - `xwines/export`, `export/*`: 5/minute, 20/hour
  - `import/upload`, `demo/install`: 5/minute
  - `POST /api/prices`: 30/minute, 200/hour (mobile use case)
- **Tests:** smoke test on `scan` and `import/upload`.
- **Effort:** ~1 hour.

### F. Bound `to_list` and `skip`/`limit` everywhere (Warnings #13, #14, Info #19, #22)
- **Files (skip/limit caps missing):**
  `winebox/routers/wines/crud.py:22`, `routers/search.py:41-42`,
  `routers/transactions.py:24-25`, `routers/cellar.py:23-24`,
  `routers/met.py:18`.
- **Files (unbounded `.to_list(length=None)`):**
  `routers/cellar.py:125, 172`, `routers/search.py:132, 157, 176`,
  `routers/bottles.py:73`, `routers/cases.py:195`,
  `routers/xwines.py:391-393`, `routers/export.py:57, 157`.
- **Approach:**
  - Add a shared `MAX_PAGE_SIZE = 200` constant; use `Query(default=N, le=MAX_PAGE_SIZE)`.
  - Replace every `.to_list(length=None)` with a paginated cursor + chunked
    streaming response for export endpoints, or hard cap to a sane batch.
  - For X-Wines regex search (`xwines.py:391-393`): rewrite to push `skip`
    and `limit` into the Mongo pipeline rather than slicing the materialised
    list.
- **Tests:** for each capped endpoint, assert 422 on `limit > MAX_PAGE_SIZE`.
- **Effort:** ~3–4 hours including export pagination work.

---

## Tier 3 — quick infosec polish (batch into one PR)

| Item | File / change | Effort |
|------|---------------|--------|
| #16 ObjectId try/except in price_tracker | `routers/price_tracker.py:247,267,304` — wrap in try/except, return 404 | 10 min |
| #17 `max_length` on price_tracker form fields | `routers/price_tracker.py:118-132` | 5 min |
| #18 Photo upload size check before read | `routers/price_tracker.py:168-170` — use `Content-Length` header or chunked read | 20 min |
| ~~#21 Auth gate on `/api/images/`~~ | DONE — `winebox/routers/images.py` replaces the StaticFiles mount with a `RequireAuth` router that verifies the requested filename is referenced by a wine the requester owns; 5 tests in `tests/test_image_serving.py`. | done |
| #23 Import file upload size limit | `routers/import_router.py:130` | 10 min |
| #24 Min password length 6 → 8 (NIST) | `winebox/auth/schemas.py:10`; align with admin path | 5 min |
| #25 Tighten `jinja2>=3.1.6` lower bound | `pyproject.toml` | 2 min |
| #26 Validate `collection` enum | `routers/wines/crud.py:32`, `routers/search.py:52` — use `Literal["red","white",...]` | 10 min |
| #28 Strip `owner_id` from export/import payloads | `routers/export.py:91`, `routers/import_router.py:766` | 15 min |
| #29 nginx `server_tokens off` | `deploy/nginx-winebox.conf`, `deploy/nginx-winebox-oat.conf` | 5 min |
| #30 Move inline script out of `og-preview.html` | `winebox/static/og-preview.html:132` | 10 min |
| #31 OAT nginx admin IP allow-list on `/admin` | `deploy/nginx-winebox-oat.conf` — same pattern as prod | 15 min |
| #32 Add timeouts to DigitalOcean API calls | `deploy/common.py` lines 142, 161, 191, 211, 222, 232, 242, 252, 268, 286 | 30 min |
| #34 Drop MongoDB hostname from admin info endpoint | `winebox/admin/routers/admin.py:35-42` | 5 min |
| #35 Playwright nav timeout in scrape script | `scripts/scrape_wine_prices.py` | 5 min |
| #36 Disable FastAPI auto-docs in production | `winebox/main.py:233` — `docs_url=None, redoc_url=None, openapi_url=None` when not in dev | 15 min |
| #37 HSTS on nginx static `location` blocks | `deploy/nginx-winebox.conf:179-184` | 10 min |
| #38 `max_length` on xwines/reference query params | `routers/xwines.py:472,475,476`, `routers/reference.py:62-64,116,119,295,296` | 15 min |
| #27 Path-traversal hardening in image_storage | `winebox/services/image_storage.py:177-208` — validate filename has no `..` or `/` even though UUIDs are used | 10 min |

**Total Tier 3 effort:** ~3–4 hours, single PR is reasonable.

---

## Suggested rollout

1. **PR 1 (Tier 1):** Items A + B + C — privacy and auth correctness, ~4 hours
   work, needs careful review. Touches user-visible behaviour
   (forced re-login on password change/reset).
2. **PR 2 (Tier 2):** Items D + E + F — DoS hardening. Mostly additive,
   safe to land together. ~5–6 hours.
3. **PR 3 (Tier 3):** All quick polish items batched. ~3–4 hours.

After all three land, run an OAT deploy and ask the security-review agent
for a fresh report — most items should drop off.

## Non-goals / explicitly deferred

- Migrating off `python-jose`'s `JTI` blacklist toward server-side session
  tokens — the new `tokens_invalidated_after` mechanism in (B) is enough.
- Switching JWT algorithm (HS256 → RS256/EdDSA) — not flagged.
- Auditing the admin app for the same DoS hardening — separate scope.
- Anything touching the deploy pipeline beyond nginx config tweaks.
