# WineBox Documentation

Welcome to WineBox, a wine cellar management application with OCR label scanning.

## Overview

WineBox helps you manage your wine collection by:

- **Scanning wine labels** using Claude Vision AI (with Tesseract OCR fallback) to automatically extract wine details
- **Tracking inventory** with check-in and check-out functionality
- **Searching your cellar** by vintage, grape variety, region, and more
- **Maintaining history** of all bottle movements

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd winebox

# Install dependencies
uv sync --all-extras

# Set up Claude Vision (recommended for better label scanning)
# Add your Anthropic API key to .env file:
echo "WINEBOX_ANTHROPIC_API_KEY=your-api-key-here" > .env

# Install Tesseract OCR as fallback (macOS)
brew install tesseract

# Install Tesseract OCR as fallback (Ubuntu/Debian)
sudo apt-get install tesseract-ocr
```

### Running the Server

```bash
# Start the server (development mode with auto-reload)
invoke start --reload

# Or start in background
invoke start-background

# Check server status
invoke status

# View logs
invoke logs

# Stop the server
invoke stop
```

### Accessing the Application

- **Web Interface**: http://localhost:8000/static/index.html
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Contents

```{toctree}
:maxdepth: 2
:caption: User Guide

user-guide
api-reference
```

## Features

### Check-In Process

1. Upload front label image (required) and back label (optional)
2. Claude Vision AI (or Tesseract OCR fallback) automatically analyzes the labels
3. Form fields are instantly populated with: wine name, vintage, winery, grape variety, region, country, alcohol %
4. Review and edit auto-detected values
5. Specify quantity of bottles
6. Wine is added to your cellar with a CHECK_IN transaction

### Check-Out Process

1. Select a wine from your cellar
2. Specify quantity to remove
3. Add optional notes (occasion, tasting notes)
4. Inventory is updated with a CHECK_OUT transaction

### Search Capabilities

- **Full-text search** across wine name, winery, region, and label text
- **Filter by** vintage, grape variety, winery, region, country
- **Date range** filters for check-in and check-out dates
- **Stock status** filter for in-stock or out-of-stock wines

## API Reference

The API provides the following endpoints:

### Wine Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/wines/checkin` | Add wine(s) to cellar |
| POST | `/api/wines/{id}/checkout` | Remove wine(s) from cellar |
| GET | `/api/wines` | List all wines |
| GET | `/api/wines/{id}` | Get wine details |
| PUT | `/api/wines/{id}` | Update wine metadata |
| DELETE | `/api/wines/{id}` | Delete wine |

### Cellar & History

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/cellar` | Current cellar inventory |
| GET | `/api/cellar/summary` | Summary statistics |
| GET | `/api/transactions` | Full transaction history |
| GET | `/api/transactions/{id}` | Single transaction |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/search` | Search wines by criteria |

## Development

### Running Tests

```bash
# Run all tests
invoke test

# Run with verbose output
invoke test --verbose

# Run with coverage
invoke test --coverage
```

### Building Documentation

```bash
# Build documentation
invoke docs-build

# Serve documentation locally
invoke docs-serve
```

### Project Structure

```
winebox/
├── winebox/          # Main application package
│   ├── main.py       # FastAPI application
│   ├── config.py     # Configuration settings
│   ├── database.py   # Database setup
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic schemas
│   ├── routers/      # API endpoints
│   ├── services/     # Business logic
│   └── static/       # Web interface
├── tests/            # Test suite
├── docs/             # Documentation
├── data/             # Database and images
└── tasks.py          # Invoke tasks
```

## License

MIT License
