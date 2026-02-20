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

## Releases
- Do NOT manually publish to PyPI - use GitHub Actions for publishing
- To make a release:
  1. Bump version in pyproject.toml and winebox/__init__.py
  2. Commit changes and push
  3. Create and push a git tag (e.g., `git tag -a v0.4.0 -m "message"`)
  4. Create a GitHub release with `gh release create`
  5. GitHub Actions will handle PyPI publishing automatically

## Deployment
- After every deployment, flush all web caches to ensure users see the latest build
- Browser caches can serve stale static files (HTML, JS, CSS) even after server updates
- When taking screenshots of deployed apps, use cache-busting query parameters (e.g., `?v=0.5.0`) or clear browser cache first
