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
