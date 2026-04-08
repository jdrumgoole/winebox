# WineBox Project Guidelines

## UX Philosophy
- The target user is a **non-technical wine consumer**, not a developer or power user.
- All UI language, flows, and terminology must be approachable and jargon-free.
- Avoid exposing technical concepts (batch IDs, collection fields, API errors) in the UI.
- Prefer guided wizards over forms with many fields. Break complex tasks into clear steps.
- Use wine-world language: "cellar", "bottle", "case", "label" — not "record", "entry", "document", "import batch".
- When in doubt, optimise for simplicity over flexibility.
- **Never display naked numbers in the UI.** Every number must have a label or unit that explains what it represents. For example, show "3.8 (245 ratings)" not "3.8 (245)"; show "14.5% ABV" not "14.5%". A non-technical user should never have to guess what a number means.
- **When renaming UI elements, update the code to match.** If a button label changes from "Check In" to "Record Wine", rename the corresponding HTML IDs, CSS classes, JS functions, API endpoints, and test references too. The codebase must reflect what the user sees on screen — stale names like `checkin-form` for a "Record Wine" feature create confusion and maintenance burden.

## Backups
- **All database backups must go to S3**, never just `/tmp/` on a droplet. Use `scripts/mongodb_backup.py` with the `--profile winebox_backup` flag.
- Example: `uv run python scripts/mongodb_backup.py --profile winebox_backup backup "mongodb+srv://...@shared.2t22cum.mongodb.net/winebox"`
- S3 bucket is configured via `WINEBOX_S3_BUCKET` env var. AWS credentials use the `winebox_backup` profile.
- Always back up the production database before any deployment or data migration.

## Local Development Server
- When starting a local server for testing or previews, use the OAT database and disable email verification:
  `source .env && WINEBOX_AUTH_EMAIL_VERIFICATION_REQUIRED=false WINEBOX_DATABASE=winebox-oat WINEBOX_SECRET_KEY="$WINEBOX_SECRET_KEY" WINEBOX_MONGODB_URL="$WINEBOX_MONGODB_URL" uv run uvicorn winebox.main:app --host 127.0.0.1 --port 8899`
- You MUST explicitly pass `WINEBOX_MONGODB_URL` — `source .env` makes it available in the shell but `uv run` does not automatically forward it to the Python process
- The email verification env var is `WINEBOX_AUTH_EMAIL_VERIFICATION_REQUIRED` (not `WINEBOX_EMAIL_VERIFICATION_REQUIRED`)
- Always use `WINEBOX_DATABASE=winebox-oat` for local development — never use production or invented database names
- Pass `WINEBOX_SECRET_KEY` from `.env` so JWT tokens work correctly

## Scripts
- Always write Python scripts instead of bash/shell scripts
- All scripts should be in the `scripts/` or `deploy/` directories

## Testing
- When running tests, use `WINEBOX_USE_CLAUDE_VISION=false` to use Tesseract only and keep costs down
- Example: `WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/`
- Production test credentials are available via `WINEBOX_TEST_USER` and `WINEBOX_TEST_PASSWORD` environment variables in `.env`. This user has been validated and can be used to log in to production for testing.
- **Treat skipped tests as failures.** Do not use `pytest.skip()` or `pytest.mark.skipif` to hide broken tests. Tests must either pass or fail — skipping masks regressions. If a test cannot run because a resource is unavailable, fix the test infrastructure so the resource is available, or remove the test entirely if the feature is no longer supported.
- **All tests must be designed from the start to run in parallel.** Use per-worker users, isolated data, and fresh browser contexts. Avoid shared mutable state, fixed ports, shared databases, or any resources that cause conflicts when tests run concurrently via pytest-xdist. E2E tests use `--dist loadfile` so same-file tests share a worker, but different files run in parallel.

## Development Approach
- Use Test-Driven Development (TDD) for all new components
- Write tests first, then implement the code to make the tests pass
- Each new feature or component should have corresponding tests written before implementation
- Run tests frequently during development to catch regressions early
- **Prefer calling real functions over mocking them.** Only mock when truly necessary (e.g. no API key available, destructive side effects, or isolating a specific failure mode). Skip tests with `pytest.mark.skipif` when a required resource (API key, database, etc.) is unavailable rather than building elaborate mock scaffolding.


## Security Guidelines

### Authentication & Authorization
- All protected endpoints MUST use `RequireAuth` or `RequireAdmin` dependencies
- Admin pages should require server-side auth, not just client-side JS checks
- When changing passwords, invalidate all existing tokens for that user
- Use constant-time comparison for authentication to prevent timing attacks

### Secrets Management
- ALL API keys and secrets MUST be in `secrets.env`, never in code or config files
- Secrets are synced to production via `deploy/common.py:sync_secrets()`
- Required secrets: `WINEBOX_SECRET_KEY`, `WINEBOX_MONGODB_URL`, `WINEBOX_ANTHROPIC_API_KEY`, `WINEBOX_POSTHOG_API_KEY`, AWS credentials
- Never log secrets or include them in error messages
- **NEVER hardcode credentials, connection strings, passwords, API keys, or tokens in source code** — not in scripts, tests, config files, or anywhere that gets committed to git. Always read them from environment variables or `secrets.env`. This includes one-off scripts, data generation scripts, and migration scripts. If a script needs a credential, require it via an environment variable and fail with a clear error if it is not set.

### Input Validation
- Always validate and limit user input length (especially search queries)
- Use Pydantic models for all API inputs
- Escape user input before regex compilation (`re.escape()`)
- Set timeouts on database queries to prevent DoS

### Rate Limiting
- All auth endpoints must have rate limits
- Admin endpoints should have stricter rate limits
- Search/expensive operations should be rate limited

### Data Isolation
- ALL database queries for user data MUST filter by `owner_id`
- Use the pattern: `Wine.find({"owner_id": current_user.id, ...})`
- Admin endpoints that access all users' data must verify `RequireAdmin`

### Datetime Handling
- Always use `datetime.now(timezone.utc)` (timezone-aware)
- Never use deprecated `datetime.utcnow()` (timezone-naive)

### Static Files & Caching
- Add cache-busting version parameters to JS/CSS files: `app.js?v=0.5.22`
- No inline scripts - use external JS files for CSP compliance
- Admin-related static files should have short cache times

## Releases & Deployment

There are two deployment environments:

### OAT (Pre-release Testing)
- **URL:** https://oat.winebox.app
- **Database:** `winebox-oat` (isolated from production)
- **Droplet:** `winebox-oat` (46.101.134.8, 1 worker due to small memory)
- **When the user says "make an OAT release"** or "deploy to OAT": run `invoke deploy-oat --release`

Deploy to OAT:

    invoke deploy-oat --release              # Bump version, publish to PyPI, deploy to OAT
    invoke deploy-oat                        # Latest version already on PyPI
    invoke deploy-oat --version 0.6.0        # Specific version already on PyPI

OAT management tasks:
- `invoke oat-setup` — Initial droplet setup
- `invoke oat-ssl` — Set up SSL certificates
- `invoke deploy-oat` — Deploy app to OAT
- `invoke oat-deploy-xwines` — Load X-Wines test data
- `invoke oat-status` — Check server health
- `invoke oat-logs` — View server logs
- `invoke test-e2e-oat` — Run E2E tests against OAT

### Production
- **URL:** https://booze.winebox.app
- **Database:** `winebox`
- **Droplet:** `winebox-production` (104.248.46.96)
- **When the user says "make a production release"** or "make a release" or "deploy": run `invoke deploy`

Full production release (tests, version bump, PyPI publish, deploy):

    invoke deploy

This will:
1. Run the full test suite (abort on failure)
2. Bump the patch version (use `--minor` or `--major` for bigger bumps)
3. Commit, tag, and push to GitHub
4. Create a GitHub release (triggers PyPI publish via GitHub Actions)
5. Wait for the new version to appear on PyPI
6. Deploy to the production server (install from PyPI, sync secrets, restart)

Options:
- `invoke deploy --version 0.6.0` — Use an explicit version instead of auto-bump
- `invoke deploy --minor` — Bump minor version (0.5.9 → 0.6.0)
- `invoke deploy --major` — Bump major version (0.5.9 → 1.0.0)
- `invoke deploy --dry-run` — Preview what would happen without making changes
- `invoke deploy --skip-tests` — Skip running the test suite
- `invoke deploy --no-secrets` — Skip syncing secrets to production

To re-deploy an existing version without making a new release:

    invoke deploy-only --version 0.5.8

### Post-Deployment Production Smoke Test
- **After EVERY production deploy**, run the production login smoke test:
  `uv run python -m pytest tests/test_production_login.py -v`
- This verifies health, login, and authenticated API access against https://booze.winebox.app
- Requires `WINEBOX_PROD_TEST_USER` and `WINEBOX_PROD_TEST_PASSWORD` in `.env`
- If this test fails after a deploy, the deploy has broken authentication — investigate immediately

### Deployment Rules (both environments)

GitHub Actions only publishes to PyPI (no auto-deploy to production).

- Never install from git directly on the server. Always build the package first and install from PyPI.
- **Never reuse a version number that has been published to PyPI.** Always increment the version for every new build. PyPI is immutable — once a version is uploaded, its contents cannot be changed. If you need to fix something in a released version, bump the version and publish again.
- **Always commit all code changes before deploying.** The deploy pipeline only auto-commits version bump files. Any uncommitted changes will be missing from the PyPI package and won't reach production. The deploy task enforces this with a dirty working tree check.
- After every deployment, flush all web caches to ensure users see the latest build
- Browser caches can serve stale static files (HTML, JS, CSS) even after server updates
- When taking screenshots of deployed apps, use cache-busting query parameters (e.g., `?v=0.5.0`) or clear browser cache first
- **Never modify server configuration piecemeal.** Do not SSH into the server to tweak nginx configs, systemd units, or other settings manually. All server configuration changes must go through a clean `invoke deploy` cycle so the full deployment pipeline runs and the server state matches the repo.
- **Never make a release while CI tests are failing.** Check `gh run list` for recent failures before any release. If CI is failing, diagnose and fix the failures first. Do not deploy with a broken CI pipeline — this includes both unit tests and E2E tests.
