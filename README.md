# WineBox

A wine cellar management application with OCR label scanning.

## Features

- **Label Scanning**: Upload wine label images for automatic text extraction via AI
- **Wine Autocomplete**: Search 100K+ wines from the [X-Wines dataset](https://github.com/rogerioxavier/X-Wines) with community ratings
- **Inventory Tracking**: Check-in and check-out bottles with full history
- **Smart Parsing**: Automatically identifies vintage, grape variety, region, and more
- **Search**: Find wines by any criteria
- **Web Interface**: Simple, mobile-friendly interface

## Quick Start

### Prerequisites

- Python 3.11+
- MongoDB 7.0+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (optional fallback)

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

# Start MongoDB (using Docker)
docker run -d -p 27017:27017 --name mongodb mongo:7

# Install Tesseract OCR (optional)
# macOS:
brew install tesseract

# Ubuntu/Debian:
sudo apt-get install tesseract-ocr
```

### Configuration

WineBox uses TOML configuration files:

```bash
# Copy example configuration
cp config/config.toml.example config.toml
cp config/secrets.env.example secrets.env

# Edit secrets.env with your API keys
nano secrets.env
```

See the [Configuration Guide](https://winebox.readthedocs.io/configuration.html) for full details.

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

## Configuration

WineBox uses a TOML-based configuration system with separate secrets management:

| File | Purpose |
|------|---------|
| `config.toml` | Main configuration (server, database, features) |
| `secrets.env` | Sensitive credentials (API keys) |

### Configuration Locations

Files are searched in priority order:

1. `./config.toml` - Project root (development)
2. `~/.config/winebox/config.toml` - User config
3. `/etc/winebox/config.toml` - System config (production)

### Example config.toml

```toml
[server]
host = "127.0.0.1"
port = 8000
debug = false

[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox"

[ocr]
use_claude_vision = true

[email]
backend = "console"
```

### Example secrets.env

```bash
WINEBOX_SECRET_KEY=your-secret-key-here
WINEBOX_ANTHROPIC_API_KEY=sk-ant-api03-...
```

Environment variables can override any configuration value.

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
| `/api/xwines/search` | GET | Autocomplete wine search |
| `/api/xwines/wines/{id}` | GET | X-Wines wine details |
| `/api/xwines/stats` | GET | Dataset statistics |

See `/docs` for interactive API documentation.

## Data Storage

### Database

WineBox uses MongoDB for data storage. Configure the connection in `config.toml`:

```toml
[database]
mongodb_url = "mongodb://localhost:27017"
mongodb_database = "winebox"
```

### Images

Wine label images are stored in the `data/images/` directory by default.

| Item | Default Location | Config Key |
|------|------------------|------------|
| Database | MongoDB `winebox` | `database.mongodb_database` |
| Images | `data/images/` | `storage.data_dir` |

**Note:** Back up your MongoDB database and images directory regularly.

## X-Wines Dataset

WineBox integrates the [X-Wines dataset](https://github.com/rogerioxavier/X-Wines) for wine autocomplete, providing suggestions from 100,646 wines with 21 million community ratings.

### Installing the Dataset

```bash
# Option 1: Test dataset (100 wines, for development)
uv run python -m scripts.import_xwines --version test

# Option 2: Full dataset (100K+ wines, for production)
# First, download from Google Drive
uv pip install gdown
mkdir -p data/xwines
uv run gdown --folder "https://drive.google.com/drive/folders/1LqguJNV-aKh1PuWMVx5ELA61LPfGfuu_?usp=sharing" -O data/xwines/
cp data/xwines/X-Wines_Official_Repository/last/XWines_Full_*.csv data/xwines/

# Then import
uv run python -m scripts.import_xwines --version full
```

The autocomplete appears when typing in the Wine Name field during check-in.

## Label Scanning

WineBox uses AI-powered label scanning to extract wine information from photos.

### Claude Vision (Recommended)

For best results, configure Claude Vision by adding your API key to `secrets.env`:

```bash
WINEBOX_ANTHROPIC_API_KEY=your-api-key
```

Claude Vision provides intelligent label analysis that:
- Handles decorative and artistic fonts
- Understands wine-specific terminology
- Extracts structured data (winery, vintage, grape variety, region, etc.)
- Works with curved or angled text

### Tesseract OCR (Fallback)

If no Anthropic API key is configured, WineBox falls back to Tesseract OCR:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr
```

To force Tesseract only (save API costs during development):

```toml
# config.toml
[ocr]
use_claude_vision = false
```

## Authentication

WineBox requires authentication for all API endpoints (except `/health`).

### Creating Users

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

## Deployment

WineBox includes deployment scripts for Digital Ocean:

```bash
# Initial server setup
uv run python -m invoke deploy-setup --host YOUR_DROPLET_IP

# Deploy to production
uv run python -m invoke deploy
```

See the [Deployment Guide](https://winebox.readthedocs.io/deployment.html) for full instructions.

## Development

### Running Tests

```bash
# Run all tests
invoke test

# With verbose output
invoke test --verbose

# With coverage
invoke test --coverage

# Run without Claude Vision (save API costs)
WINEBOX_USE_CLAUDE_VISION=false invoke test
```

### Project Structure

```
winebox/
├── winebox/          # Application package
│   ├── main.py       # FastAPI app
│   ├── config/       # Configuration module
│   ├── models/       # MongoDB/Beanie models
│   ├── schemas/      # API schemas
│   ├── routers/      # API endpoints
│   ├── services/     # Business logic
│   └── static/       # Web interface
├── config/           # Configuration templates
├── deploy/           # Deployment module
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
- **MongoDB**: Document database
- **Beanie**: MongoDB ODM
- **fastapi-users**: Authentication
- **Tesseract/Claude Vision**: OCR engines
- **Vanilla JS**: Frontend (no frameworks)

## License

MIT License
