# User Guide

This guide walks you through using WineBox to manage your wine cellar.

## Dashboard Overview

When you log in, the **Dashboard** shows you:

- **Total Bottles** - All bottles currently in your cellar
- **Unique Wines** - Number of different wines
- **Wines Tracked** - Total wines you've ever recorded

Below the statistics, you'll see breakdowns by country, grape variety, and vintage, plus your recent activity.

## Checking In Wine

Adding wine to your cellar is easy with WineBox's AI-powered label scanning.

### Step-by-Step

1. **Click Check In** in the navigation menu
2. **Upload the front label photo** (required)
   - Click "Choose file" or drag and drop an image
   - Supported formats: JPG, PNG, GIF, WebP
3. **Wait for scanning** - the form populates automatically
   - A notification tells you which scanner was used (Claude Vision or Tesseract OCR)
4. **Upload back label** (optional) - adds more details
5. **Use autocomplete** (optional)
   - Type at least 2 characters in the Wine Name field
   - Select a wine to auto-fill winery, country, and ABV
6. **Review the details** - edit anything that looks incorrect
7. **Set quantity** - how many bottles you're adding
8. **Add notes** (optional) - where you bought it, price, occasion
9. **Click Check In Wine**
10. **Confirm** in the dialog that appears

### What Gets Detected

The AI scanner looks for:
- Wine name
- Vintage year
- Winery/producer
- Grape variety
- Region and country
- Alcohol percentage
- Classification (Grand Cru, DOCG, etc.)

### Using Wine Autocomplete

The autocomplete feature searches over 100,000 wines from the X-Wines dataset:

- Start typing a wine name (minimum 2 characters)
- Results show wine name, winery, type, country, and community ratings
- Use arrow keys to navigate, Enter to select
- Selecting a wine fills in: name, winery, country, and ABV

**Note**: Autocomplete requires the X-Wines database to be installed. See the "For Developers" section below for setup instructions.

## Viewing Your Cellar

The **Cellar** page displays all your wines as cards.

### Filters

Use the dropdown to show:
- **All Wines** - everything you've tracked
- **In Stock Only** - wines with bottles available
- **Out of Stock** - wines you've finished

### Quick Search

Type in the search box to filter by name or winery.

### Wine Cards

Each card shows:
- Label image
- Wine name and vintage
- Region and country
- Current bottle count
- **Check Out** button

Click anywhere on the card to see full details.

## Wine Details

Clicking a wine opens the detail modal showing:

- **Label image** - the photo you uploaded
- **Full wine info** - name, vintage, region, country, alcohol %
- **Stock status** - how many bottles you have
- **Raw label text** - expand to see what the scanner detected
- **Transaction history** - every check-in and check-out
- **Actions** - Check Out and Delete buttons

## Checking Out Wine

Remove bottles when you drink or sell them:

1. Go to the **Cellar** page
2. Find the wine (use search if needed)
3. Click **Check Out** on the card, or open details first
4. Enter the quantity to remove
5. Add notes (optional) - occasion, tasting notes, who you shared it with
6. Click **Check Out**

The transaction is recorded in your history.

## Searching Your Cellar

The **Search** page offers advanced filtering beyond the cellar's quick search.

### Available Filters

| Filter | Description |
|--------|-------------|
| Text Search | Searches name, winery, region, and label text |
| Vintage | Filter by year |
| Grape Variety | e.g., "Cabernet", "Merlot" |
| Winery | Filter by producer |
| Region | e.g., "Napa Valley", "Bordeaux" |
| Country | e.g., "France", "Italy" |
| Wine Type | Red, White, Rosé, Sparkling, Fortified, Dessert |
| Price Tier | Budget through Ultra Premium |
| In Stock Only | Only wines with bottles available |

### Search Tips

- Partial matches work: "Cab" finds "Cabernet Sauvignon"
- Searches are case-insensitive
- Combine multiple filters for precise results
- Click **Clear** to reset all filters

## Transaction History

The **History** page shows a chronological log of all activity.

### What's Recorded

- **Check In** (green "IN" badge) - bottles added
- **Check Out** (red "OUT" badge) - bottles removed

Each entry shows:
- Transaction type
- Wine name and vintage
- Quantity
- Date and time

### Filtering History

Use the dropdown to show:
- All transactions
- Check-ins only
- Check-outs only

## Tips for Best Results

### Taking Great Label Photos

For best AI scanning:

1. **Good lighting** - natural light or well-lit room
2. **Sharp focus** - ensure text is readable
3. **Full label** - capture the entire label
4. **Flat angle** - photograph straight-on, not at an angle
5. **High resolution** - more pixels = better accuracy

### AI Scanning Options

WineBox uses two scanning engines:

1. **Claude Vision AI** (recommended)
   - More accurate label interpretation
   - Requires Anthropic API key
   - Add to `secrets.env`: `WINEBOX_ANTHROPIC_API_KEY=your-key`
   - Or set in `config.toml`: `[ocr] use_claude_vision = true`

2. **Tesseract OCR** (fallback)
   - Works without API key
   - Basic text extraction
   - Install: `brew install tesseract` (macOS) or `apt-get install tesseract-ocr` (Linux)
   - To force Tesseract only: set `[ocr] use_claude_vision = false` in config.toml

### Keeping Your Cellar Organized

- Use consistent naming when editing wine names
- Always include vintage when known
- Use standard grape variety names (Cabernet Sauvignon, not "Cab")
- Include region and country for better searching
- Add notes about where you purchased wines

### Data Backup

Your cellar data is stored in MongoDB and the filesystem:

| Location | Contents |
|----------|----------|
| MongoDB `winebox` database | All wines, transactions, and users |
| `data/images/` | Label photos you've uploaded |

**Back up regularly** to preserve your collection records:

```bash
# Backup MongoDB
mongodump --db winebox --out backups/

# Backup images
tar -czf backups/images.tar.gz data/images/
```

---

# For Developers

This section covers development setup, testing, and API documentation for contributors.

## Project Structure

```
winebox/
├── winebox/              # Main application package
│   ├── main.py           # FastAPI application
│   ├── config/           # Configuration module
│   │   ├── schema.py     # Pydantic config models
│   │   ├── loader.py     # TOML loading logic
│   │   └── settings.py   # Global settings instance
│   ├── database.py       # MongoDB/Beanie setup
│   ├── models/           # Beanie document models
│   ├── schemas/          # Pydantic API schemas
│   ├── routers/          # API endpoints
│   ├── services/         # Business logic (OCR, etc.)
│   ├── auth/             # Authentication (fastapi-users)
│   └── static/           # Web interface (HTML, JS, CSS)
├── config/               # Configuration templates
│   ├── config.toml.example
│   └── secrets.env.example
├── deploy/               # Deployment module
│   ├── __init__.py       # Package exports
│   ├── common.py         # Shared utilities
│   ├── app.py            # Deploy application
│   ├── setup.py          # Initial server setup
│   ├── xwines.py         # Deploy X-Wines dataset
│   ├── winebox.service   # systemd service
│   └── nginx-winebox.conf # nginx config
├── scripts/              # Utility scripts
│   └── import_xwines.py  # X-Wines dataset importer
├── tests/                # Test suite
├── docs/                 # Sphinx documentation
├── data/                 # Images and local data
└── tasks.py              # Invoke tasks
```

## Development Setup

```bash
# Clone and install with uv
git clone https://github.com/jdrumgoole/winebox.git
cd winebox
uv sync --all-extras

# Start MongoDB (using Docker)
docker run -d -p 27017:27017 --name mongodb mongo:7

# Or install locally:
# macOS: brew tap mongodb/brew && brew install mongodb-community
# Ubuntu: see https://www.mongodb.com/docs/manual/tutorial/install-mongodb-on-ubuntu/

# Set up configuration
cp config/config.toml.example config.toml
cp config/secrets.env.example secrets.env

# Edit secrets.env and add your API key (optional)
# WINEBOX_ANTHROPIC_API_KEY=your-key

# Install Tesseract OCR fallback
brew install tesseract  # macOS
# or: sudo apt-get install tesseract-ocr  # Ubuntu/Debian

# Initialize database
uv run python -m invoke init-db

# Start development server with auto-reload
uv run python -m invoke start --reload
```

## Installing the X-Wines Database

The wine autocomplete feature requires the X-Wines dataset. This is only available when running from source.

### Test Dataset (Development)

For development with 100 sample wines:

```bash
uv run python -m scripts.import_xwines --version test
```

### Full Dataset (100K+ Wines)

For the complete database with community ratings:

```bash
# Install download tool
uv pip install gdown

# Download dataset from Google Drive
mkdir -p data/xwines
uv run gdown --folder "https://drive.google.com/drive/folders/1LqguJNV-aKh1PuWMVx5ELA61LPfGfuu_?usp=sharing" -O data/xwines/

# Copy files to expected location
cp data/xwines/X-Wines_Official_Repository/last/XWines_Full_100K_wines.csv data/xwines/
cp data/xwines/X-Wines_Official_Repository/last/XWines_Full_21M_ratings.csv data/xwines/

# Import (takes a few minutes)
uv run python -m scripts.import_xwines --version full --force
```

### Verify Import

```bash
curl http://localhost:8000/api/xwines/stats
```

You should see `wine_count: 100646` for the full dataset.

## Running Tests

```bash
# Run all tests
uv run python -m invoke test

# Run only unit tests (fast, no server required)
uv run python -m invoke test-unit

# Run only E2E tests (requires running server)
uv run python -m invoke test-e2e

# Run with verbose output
uv run python -m invoke test --verbose

# Run with coverage
uv run python -m invoke test --coverage
```

**Note**: E2E tests use Playwright for browser automation. Install browsers with:
```bash
uv run playwright install
```

## Invoke Tasks Reference

### Server Management

```bash
uv run python -m invoke start              # Start foreground
uv run python -m invoke start --reload     # Start with auto-reload
uv run python -m invoke start-background   # Start in background
uv run python -m invoke stop               # Stop server
uv run python -m invoke restart            # Restart server
uv run python -m invoke status             # Check status
uv run python -m invoke logs               # View logs
```

### Database Management

```bash
uv run python -m invoke init-db              # Initialize
uv run python -m invoke purge --force        # Delete all data
uv run python -m invoke purge-wines --force  # Delete wines only
```

### Database Migrations

```bash
uv run python -m scripts.migrations.runner status       # Show version
uv run python -m scripts.migrations.runner up           # Migrate to latest
uv run python -m scripts.migrations.runner down --to 0  # Revert
uv run python -m scripts.migrations.runner history      # Show history
```

### User Management (Development)

```bash
uv run python -m invoke add-user USERNAME --password PASS
uv run python -m invoke remove-user USERNAME --force
uv run python -m invoke list-users
uv run python -m invoke disable-user USERNAME
uv run python -m invoke enable-user USERNAME
uv run python -m invoke passwd USERNAME --password NEWPASS
```

### Documentation

```bash
uv run python -m invoke docs-build   # Build Sphinx docs
uv run python -m invoke docs-serve   # Build and serve locally
```

## API Reference

Full API documentation is available at http://localhost:8000/docs when the server is running.

### Authentication

All API endpoints (except `/health`) require JWT authentication.

```bash
# Get token
curl -X POST http://localhost:8000/api/auth/token \
  -d "username=myuser&password=mypass"

# Use token in requests
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/wines
```

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

### X-Wines Dataset

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/xwines/search?q=<query>` | Autocomplete wine search |
| GET | `/api/xwines/wines/{id}` | Get X-Wines wine details |
| GET | `/api/xwines/stats` | Dataset statistics |
| GET | `/api/xwines/types` | List wine types |
| GET | `/api/xwines/countries` | List countries |

### Example: Check In via API

```bash
curl -X POST http://localhost:8000/api/wines/checkin \
  -H "Authorization: Bearer <token>" \
  -F "front_label=@wine_front.jpg" \
  -F "back_label=@wine_back.jpg" \
  -F "name=Chateau Margaux" \
  -F "vintage=2016" \
  -F "quantity=6"
```

### Example: Search via API

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/search?country=France&wine_type=Red&in_stock=true"
```

## Building Documentation

```bash
# Build HTML docs
uv run python -m invoke docs-build

# Serve docs locally
uv run python -m invoke docs-serve
```

Documentation is built to `docs/_build/html/`.
