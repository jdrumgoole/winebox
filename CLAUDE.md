# WineBox Project Guidelines

## Testing
- When running tests, use `WINEBOX_USE_CLAUDE_VISION=false` to use Tesseract only and keep costs down
- Example: `WINEBOX_USE_CLAUDE_VISION=false uv run python -m pytest tests/`
