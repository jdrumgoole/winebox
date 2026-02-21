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
- After every deployment, flush all web caches to ensure users see the latest build
- Browser caches can serve stale static files (HTML, JS, CSS) even after server updates
- When taking screenshots of deployed apps, use cache-busting query parameters (e.g., `?v=0.5.0`) or clear browser cache first
