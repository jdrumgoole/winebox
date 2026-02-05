# User Guide

This guide walks you through using WineBox to manage your wine cellar.

## Getting Started

### First Time Setup

1. **Start the server**:
   ```bash
   invoke start --reload
   ```

2. **Open the web interface**:
   Navigate to http://localhost:8000/static/index.html in your browser.

3. **Explore the dashboard**:
   The dashboard shows your cellar summary and recent activity.

## Checking In Wine

The check-in process adds bottles to your cellar inventory.

### Using the Web Interface

1. Click **Check In** in the navigation menu
2. **Upload the front label image** (required):
   - Click the file input or drag and drop an image
   - Supported formats: JPG, PNG, GIF, WebP
   - Form fields are automatically populated as soon as the image is uploaded
3. **Upload the back label image** (optional):
   - Back labels often contain additional details
   - Scanning updates with information from both labels
4. **Review auto-detected values**:
   - Claude Vision AI (or Tesseract OCR fallback) extracts wine details
   - A toast notification shows which scanning engine was used
   - Edit any incorrect values as needed
   - View raw label text in the collapsible "Raw Label Text" section
5. **Set the quantity**:
   - Enter the number of bottles you're adding
6. **Add notes** (optional):
   - Where you purchased it, price, occasion, etc.
7. Click **Check In Wine**
8. **Review in confirmation dialog**:
   - A confirmation dialog appears with all editable fields
   - Make any final adjustments to wine details
   - View raw label text by expanding the "Raw Label Text" section
   - Click **Confirm** to save or **Cancel** to return to the form

### Using the API

```bash
curl -X POST http://localhost:8000/api/wines/checkin \
  -F "front_label=@wine_front.jpg" \
  -F "back_label=@wine_back.jpg" \
  -F "name=Chateau Margaux" \
  -F "vintage=2016" \
  -F "quantity=6"
```

## Checking Out Wine

Remove bottles from your cellar when you drink or sell them.

### Using the Web Interface

1. Go to **Cellar** view
2. Find the wine you want to check out
3. Click the **Check Out** button on the wine card
4. Enter the quantity to remove
5. Add optional notes (occasion, tasting notes)
6. Click **Check Out**

### Using the API

```bash
curl -X POST http://localhost:8000/api/wines/{wine_id}/checkout \
  -F "quantity=1" \
  -F "notes=Dinner party with friends"
```

## Viewing Your Cellar

### Cellar View

The Cellar page shows all wines currently in stock:

- **Filter**: Show all wines, in-stock only, or out-of-stock
- **Search**: Quick search by name, winery, or grape
- Click any wine card to see full details

### Wine Details

Clicking a wine card shows:

- Full wine information
- Label images
- OCR-extracted text
- Complete transaction history
- Check-out and delete options

## Searching Your Cellar

The Search page provides advanced filtering:

### Available Filters

- **Text Search**: Search across name, winery, region, and label text
- **Vintage**: Filter by year
- **Grape Variety**: e.g., "Cabernet", "Merlot"
- **Winery**: Filter by producer
- **Region**: e.g., "Napa Valley", "Bordeaux"
- **Country**: e.g., "France", "Italy"
- **In Stock Only**: Only show wines with bottles available

### Search Tips

- Partial matches work: "Cab" matches "Cabernet Sauvignon"
- Searches are case-insensitive
- Combine filters for precise results

## Transaction History

View all check-ins and check-outs:

1. Go to **History** in the navigation
2. Use the filter to show:
   - All transactions
   - Check-ins only
   - Check-outs only

Each transaction shows:
- Transaction type (In/Out)
- Wine name and vintage
- Quantity
- Date and time

## Dashboard

The Dashboard provides an overview of your cellar:

### Statistics

- **Total Bottles**: Sum of all bottles in stock
- **Unique Wines**: Number of different wines
- **Wines Tracked**: Total wines ever recorded

### Breakdowns

- **By Country**: Bottle count per country
- **By Grape Variety**: Distribution by grape
- **By Vintage**: Distribution by year

### Recent Activity

Shows the last 10 transactions with quick details.

## Tips and Best Practices

### Taking Good Label Photos

For best scanning results with Claude Vision:

1. **Good lighting**: Natural light or well-lit room
2. **Flat surface**: Lay the bottle on its side or hold label flat
3. **Focus**: Ensure text is sharp and readable
4. **Full label**: Capture the entire label in frame
5. **High resolution**: Higher resolution improves accuracy

Claude Vision provides intelligent label analysis that understands wine label context. If the Anthropic API key is not configured, the app falls back to Tesseract OCR.

### Organizing Your Cellar

- Use consistent naming when editing wine names
- Always include vintage when known
- Use standard grape variety names
- Include region and country for better searching

### Data Backup

Your data is stored in:
- **Database**: `data/winebox.db`
- **Images**: `data/images/`

Back up these files regularly to preserve your cellar records.

## Development

### Running Tests

WineBox has both unit tests and end-to-end (E2E) browser tests.

```bash
# Run all tests (unit + E2E)
invoke test

# Run only unit tests (fast, no server required)
invoke test-unit

# Run only E2E tests (requires running server)
invoke test-e2e

# Run E2E tests with more workers for faster execution
invoke test-e2e --workers 8
```

**Note**: E2E tests use Playwright for browser automation and create unique test users for parallel execution. The server must be running (`invoke start-background`) before running E2E tests.

### Invoke Tasks

Common development tasks:

```bash
# Server management
invoke start              # Start server in foreground
invoke start-background   # Start server in background
invoke stop               # Stop the server
invoke restart            # Restart the server
invoke status             # Check server status
invoke logs               # View server logs

# Database management
invoke init-db            # Initialize database
invoke purge --force      # Delete database and images
invoke purge-wines --force # Delete wines but keep users

# User management
invoke add-user <username> --password <pass>
invoke remove-user <username> --force
invoke list-users
invoke disable-user <username>
invoke enable-user <username>
invoke passwd <username> --password <newpass>

# Documentation
invoke docs-build         # Build Sphinx documentation
invoke docs-serve         # Build and serve docs locally
```
