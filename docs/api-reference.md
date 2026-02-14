# API Reference

Complete reference for the WineBox REST API.

## Base URL

```
http://localhost:8000/api
```

## Authentication

Currently, the API does not require authentication.

## Endpoints

### Health Check

#### GET /health

Check if the server is running.

**Response**:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "app_name": "WineBox"
}
```

---

## Wine Endpoints

### POST /api/wines/checkin

Check in wine bottles to the cellar.

**Content-Type**: `multipart/form-data`

**Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| front_label | file | Yes | Front label image |
| back_label | file | No | Back label image |
| name | string | No | Wine name (auto-detected if not provided) |
| winery | string | No | Winery name |
| vintage | integer | No | Vintage year (1900-2100) |
| grape_variety | string | No | Grape variety |
| region | string | No | Wine region |
| country | string | No | Country of origin |
| alcohol_percentage | float | No | Alcohol percentage (0-100) |
| quantity | integer | Yes | Number of bottles (min: 1) |
| notes | string | No | Check-in notes |

**Response**: `201 Created`
```json
{
  "id": "uuid",
  "name": "Wine Name",
  "winery": "Winery Name",
  "vintage": 2019,
  "grape_variety": "Cabernet Sauvignon",
  "region": "Napa Valley",
  "country": "United States",
  "alcohol_percentage": 14.5,
  "front_label_text": "OCR extracted text...",
  "back_label_text": null,
  "front_label_image_path": "uuid.jpg",
  "back_label_image_path": null,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "inventory": {
    "quantity": 6,
    "updated_at": "2024-01-15T10:30:00Z"
  }
}
```

---

### POST /api/wines/{wine_id}/checkout

Check out wine bottles from the cellar.

**Content-Type**: `multipart/form-data`

**Path Parameters**:
- `wine_id`: UUID of the wine

**Form Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| quantity | integer | Yes | Number of bottles to remove (min: 1) |
| notes | string | No | Check-out notes |

**Response**: `200 OK`

Returns the updated wine object.

**Errors**:
- `404 Not Found`: Wine not found
- `400 Bad Request`: Not enough bottles in stock

---

### GET /api/wines

List all wines.

**Query Parameters**:

| Name | Type | Description |
|------|------|-------------|
| skip | integer | Number of records to skip (default: 0) |
| limit | integer | Maximum records to return (default: 100) |
| in_stock | boolean | Filter by stock status |

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "name": "Wine Name",
    ...
    "inventory": {
      "quantity": 3,
      "updated_at": "..."
    }
  }
]
```

---

### GET /api/wines/{wine_id}

Get wine details with full transaction history.

**Response**: `200 OK`
```json
{
  "id": "uuid",
  "name": "Wine Name",
  ...
  "inventory": {...},
  "transactions": [
    {
      "id": "uuid",
      "transaction_type": "CHECK_IN",
      "quantity": 6,
      "notes": "Purchased at auction",
      "transaction_date": "2024-01-15T10:30:00Z"
    }
  ]
}
```

---

### PUT /api/wines/{wine_id}

Update wine metadata.

**Content-Type**: `application/json`

**Request Body**:
```json
{
  "name": "Updated Name",
  "vintage": 2020,
  "grape_variety": "Merlot"
}
```

Only include fields you want to update.

**Response**: `200 OK`

---

### DELETE /api/wines/{wine_id}

Delete a wine and all its history.

**Response**: `204 No Content`

---

## Cellar Endpoints

### GET /api/cellar

Get current cellar inventory (wines in stock).

**Query Parameters**:
- `skip`: Number to skip (default: 0)
- `limit`: Maximum to return (default: 100)

**Response**: `200 OK`

Returns list of wines with quantity > 0.

---

### GET /api/cellar/summary

Get cellar summary statistics.

**Response**: `200 OK`
```json
{
  "total_bottles": 42,
  "unique_wines": 15,
  "total_wines_tracked": 20,
  "by_vintage": {
    "2019": 12,
    "2020": 8
  },
  "by_country": {
    "France": 18,
    "Italy": 12
  },
  "by_grape_variety": {
    "Cabernet Sauvignon": 15,
    "Merlot": 10
  }
}
```

---

## Transaction Endpoints

### GET /api/transactions

List all transactions.

**Query Parameters**:

| Name | Type | Description |
|------|------|-------------|
| skip | integer | Number to skip |
| limit | integer | Maximum to return |
| transaction_type | string | Filter: "CHECK_IN" or "CHECK_OUT" |
| wine_id | string | Filter by wine UUID |

**Response**: `200 OK`
```json
[
  {
    "id": "uuid",
    "wine_id": "uuid",
    "transaction_type": "CHECK_IN",
    "quantity": 6,
    "notes": "...",
    "transaction_date": "2024-01-15T10:30:00Z",
    "created_at": "2024-01-15T10:30:00Z",
    "wine": {
      "id": "uuid",
      "name": "Wine Name",
      "vintage": 2019,
      "winery": "Winery Name"
    }
  }
]
```

---

### GET /api/transactions/{transaction_id}

Get a single transaction.

**Response**: `200 OK`

---

## Search Endpoint

### GET /api/search

Search wines by various criteria.

**Query Parameters**:

| Name | Type | Description |
|------|------|-------------|
| q | string | Full-text search |
| vintage | integer | Vintage year |
| grape | string | Grape variety (partial match) |
| winery | string | Winery name (partial match) |
| region | string | Region (partial match) |
| country | string | Country (partial match) |
| checked_in_after | datetime | Check-in date filter |
| checked_in_before | datetime | Check-in date filter |
| checked_out_after | datetime | Check-out date filter |
| checked_out_before | datetime | Check-out date filter |
| in_stock | boolean | Only in-stock wines |
| skip | integer | Pagination offset |
| limit | integer | Pagination limit |

**Response**: `200 OK`

Returns list of matching wines.

---

## Images

### GET /api/images/{filename}

Serve stored label images.

**Response**: Image file with appropriate content type.

---

## X-Wines Dataset Endpoints

The X-Wines endpoints provide access to a reference database of 100K+ wines with community ratings from the [X-Wines dataset](https://github.com/rogerioxavier/X-Wines).

### GET /api/xwines/search

Search X-Wines dataset for wine autocomplete.

**Query Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| q | string | Yes | Search query (min 2 characters) |
| limit | integer | No | Maximum results (default: 10, max: 50) |
| wine_type | string | No | Filter by wine type (Red, White, etc.) |
| country | string | No | Filter by country code (FR, US, etc.) |

**Response**: `200 OK`
```json
{
  "results": [
    {
      "id": 100062,
      "name": "Origem Merlot",
      "winery": "Casa Valduga",
      "wine_type": "Red",
      "country": "Brazil",
      "region": "Vale dos Vinhedos",
      "abv": 13.0,
      "avg_rating": 4.12,
      "rating_count": 21
    }
  ],
  "total": 2
}
```

---

### GET /api/xwines/wines/{wine_id}

Get full details for a specific X-Wines wine.

**Path Parameters**:
- `wine_id`: Integer ID of the wine

**Response**: `200 OK`
```json
{
  "id": 100062,
  "name": "Origem Merlot",
  "wine_type": "Red",
  "elaborate": "Varietal/100%",
  "grapes": "['Merlot']",
  "harmonize": "['Beef', 'Lamb', 'Veal']",
  "abv": 13.0,
  "body": "Full-bodied",
  "acidity": "Medium",
  "country_code": "BR",
  "country": "Brazil",
  "region_id": 1002,
  "region_name": "Vale dos Vinhedos",
  "winery_id": 10014,
  "winery_name": "Casa Valduga",
  "website": "http://www.casavalduga.com.br",
  "vintages": "[2020, 2019, 2018, 2017]",
  "avg_rating": 4.12,
  "rating_count": 21
}
```

---

### GET /api/xwines/stats

Get X-Wines dataset statistics.

**Response**: `200 OK`
```json
{
  "wine_count": 100646,
  "rating_count": 21013536,
  "version": "full",
  "import_date": "2024-01-15T10:30:00",
  "source": "https://github.com/rogerioxavier/X-Wines"
}
```

---

### GET /api/xwines/types

List distinct wine types in the dataset.

**Response**: `200 OK`
```json
["Dessert/Port", "Fortified", "Red", "Rosé", "Sparkling", "White"]
```

---

### GET /api/xwines/countries

List countries with wine counts.

**Response**: `200 OK`
```json
[
  {"code": "FR", "name": "France", "count": 25432},
  {"code": "IT", "name": "Italy", "count": 18234},
  {"code": "US", "name": "United States", "count": 15678}
]
```

---

## Error Responses

All endpoints may return these error responses:

### 400 Bad Request
```json
{
  "detail": "Description of the error"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 422 Unprocessable Entity
```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "Validation error message",
      "type": "error_type"
    }
  ]
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```
