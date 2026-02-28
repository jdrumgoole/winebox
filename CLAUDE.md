# WineBox Project Guidelines

## Scripts
- Always write Python scripts instead of bash/shell scripts
- All scripts should be in the `scripts/` or `deploy/` directories

## Testing
- When running tests, use `WINEBOX_USE_CLAUDE_VISION=false` to use Tesseract only and keep costs down
- Example: `WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/`

## Development Approach
- Use Test-Driven Development (TDD) for all new components
- Write tests first, then implement the code to make the tests pass
- Each new feature or component should have corresponding tests written before implementation
- Run tests frequently during development to catch regressions early

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
- Use the pattern: `Wine.find(Wine.owner_id == current_user.id, ...)`
- Admin endpoints that access all users' data must verify `RequireAdmin`

### Datetime Handling
- Always use `datetime.now(timezone.utc)` (timezone-aware)
- Never use deprecated `datetime.utcnow()` (timezone-naive)

### Static Files & Caching
- Add cache-busting version parameters to JS/CSS files: `app.js?v=0.5.22`
- No inline scripts - use external JS files for CSP compliance
- Admin-related static files should have short cache times

## Releases & Deployment

Single command handles everything:

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

GitHub Actions only publishes to PyPI (no auto-deploy to production).

- Never install from git directly on the server. Always build the package first and install from PyPI.
- **Never reuse a version number that has been published to PyPI.** Always increment the version for every new build. PyPI is immutable — once a version is uploaded, its contents cannot be changed. If you need to fix something in a released version, bump the version and publish again.
- After every deployment, flush all web caches to ensure users see the latest build
- Browser caches can serve stale static files (HTML, JS, CSS) even after server updates
- When taking screenshots of deployed apps, use cache-busting query parameters (e.g., `?v=0.5.0`) or clear browser cache first
