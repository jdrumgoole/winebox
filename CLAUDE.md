# WineBox Project Guidelines

## Scripts
- Always write Python scripts instead of bash/shell scripts
- All scripts should be in the `scripts/` or `deploy/` directories

## Testing
- When running tests, use `WINEBOX_USE_CLAUDE_VISION=false` to use Tesseract only and keep costs down
- Example: `WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/`
