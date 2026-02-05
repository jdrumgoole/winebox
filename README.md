# WineBox

A wine cellar management application with OCR label scanning.

## Features

- **Label Scanning**: Upload wine label images for automatic text extraction via OCR
- **Inventory Tracking**: Check-in and check-out bottles with full history
- **Smart Parsing**: Automatically identifies vintage, grape variety, region, and more
- **Search**: Find wines by any criteria
- **Web Interface**: Simple, mobile-friendly interface

## Quick Start

### Prerequisites

- Python 3.11+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)

### Installation

**From PyPI:**
```bash
pip install winebox
```

**From source:**
```bash
# Clone the repository
git clone https://github.com/jdrumgoole/winebox.git
cd winebox

# Install dependencies
uv sync --all-extras

# Install Tesseract OCR
# macOS:
brew install tesseract

# Ubuntu/Debian:
sudo apt-get install tesseract-ocr
```

### Running the Server

```bash
# Development mode with auto-reload
invoke start --reload

# Background mode
invoke start-background

# Check status
invoke status

# Stop server
invoke stop
```

### Access the Application

- **Web Interface**: http://localhost:8000/static/index.html
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Usage

### Check In Wine

1. Navigate to the Check In page
2. Upload front label image (required)
3. Optionally upload back label image
4. Review/edit auto-detected wine details
5. Set quantity and add notes
6. Click "Check In Wine"

### Check Out Wine

1. Go to the Cellar view
2. Click "Check Out" on a wine card
3. Enter quantity to remove
4. Add optional notes (tasting notes, occasion)
5. Confirm checkout

### Search

Use the Search page to find wines by:
- Text search (name, winery, region)
- Vintage year
- Grape variety
- Region or country
- Stock status

## API

Full REST API available at `/api`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/wines/checkin` | POST | Add wine to cellar |
| `/api/wines/{id}/checkout` | POST | Remove wine from cellar |
| `/api/wines` | GET | List all wines |
| `/api/wines/{id}` | GET | Get wine details |
| `/api/cellar` | GET | Current inventory |
| `/api/cellar/summary` | GET | Cellar statistics |
| `/api/transactions` | GET | Transaction history |
| `/api/search` | GET | Search wines |

See `/docs` for interactive API documentation.

## Data Storage

### Database

The SQLite database is stored at `data/winebox.db` by default. This can be configured via the `WINEBOX_DATABASE_URL` environment variable.

### Images

Wine label images are stored in the `data/images/` directory by default. Each image is saved with a UUID filename to avoid conflicts.

| Item | Default Location | Environment Variable |
|------|------------------|---------------------|
| Database | `data/winebox.db` | `WINEBOX_DATABASE_URL` |
| Images | `data/images/` | `WINEBOX_IMAGE_STORAGE_PATH` |

Images are served via the API at `/api/images/{filename}`.

**Note:** The `data/` directory is excluded from git (see `.gitignore`). Make sure to back up this directory to preserve your wine collection data.

## Label Scanning

WineBox uses AI-powered label scanning to extract wine information from photos.

### Claude Vision (Recommended)

For best results, configure Claude Vision by setting your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your-api-key
# or
export WINEBOX_ANTHROPIC_API_KEY=your-api-key
```

Claude Vision provides intelligent label analysis that:
- Handles decorative and artistic fonts
- Understands wine-specific terminology
- Extracts structured data (winery, vintage, grape variety, region, etc.)
- Works with curved or angled text

### Tesseract OCR (Fallback)

If no Anthropic API key is configured, WineBox falls back to Tesseract OCR. This requires Tesseract to be installed on your system:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr
```

## Authentication

WineBox requires authentication for all API endpoints (except `/health`).

### Creating Users

Use the `winebox-admin` command to manage users:

```bash
# Create an admin user
uv run winebox-admin add admin --email admin@example.com --admin --password yourpassword

# Create a regular user
uv run winebox-admin add username --email user@example.com --password yourpassword

# List all users
uv run winebox-admin list

# Disable/enable a user
uv run winebox-admin disable username
uv run winebox-admin enable username

# Change password
uv run winebox-admin passwd username --password newpassword

# Remove a user
uv run winebox-admin remove username
```

### Server Management

Use the `winebox-server` command to manage the server:

```bash
# Start server (foreground)
uv run winebox-server start --foreground

# Start server (background)
uv run winebox-server start

# Stop server
uv run winebox-server stop

# Restart server
uv run winebox-server restart

# Check status
uv run winebox-server status
```

### API Authentication

The API uses JWT bearer tokens. To authenticate:

1. POST to `/api/auth/token` with `username` and `password` (form-urlencoded)
2. Include the returned token in subsequent requests: `Authorization: Bearer <token>`

Tokens expire after 24 hours.

## Development

### Running Tests

```bash
# Run all tests
invoke test

# With verbose output
invoke test --verbose

# With coverage
invoke test --coverage
```

### Project Structure

```
winebox/
├── winebox/          # Application package
│   ├── main.py       # FastAPI app
│   ├── models/       # Database models
│   ├── schemas/      # API schemas
│   ├── routers/      # API endpoints
│   ├── services/     # Business logic
│   └── static/       # Web interface
├── tests/            # Test suite
├── docs/             # Documentation
└── tasks.py          # Build tasks
```

### Building Documentation

```bash
invoke docs-build
invoke docs-serve
```

## Tech Stack

- **FastAPI**: Web framework
- **SQLAlchemy**: ORM
- **SQLite**: Database
- **Tesseract**: OCR engine
- **Vanilla JS**: Frontend (no frameworks)

## License

MIT License
