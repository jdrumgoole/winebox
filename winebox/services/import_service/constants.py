"""Constants for wine import service."""

# Maximum rows per import batch (safety limit for MongoDB 16MB doc size)
MAX_ROWS = 10000

# Header alias table: lowercase alias -> wine field name
HEADER_ALIASES: dict[str, str] = {
    # name
    "wine": "name",
    "wine name": "name",
    "wine_name": "name",
    "label": "name",
    "name": "name",
    "title": "name",
    # winery
    "winery": "winery",
    "producer": "winery",
    "maker": "winery",
    "domaine": "winery",
    "chateau": "winery",
    "château": "winery",
    "estate": "winery",
    "bodega": "winery",
    "cantina": "winery",
    # vintage
    "vintage": "vintage",
    "year": "vintage",
    "vintage year": "vintage",
    "vintage_year": "vintage",
    # grape_variety
    "grape": "grape_variety",
    "grape variety": "grape_variety",
    "grape_variety": "grape_variety",
    "varietal": "grape_variety",
    "grapes": "grape_variety",
    "variety": "grape_variety",
    "cépage": "grape_variety",
    # region
    "region": "region",
    "wine region": "region",
    # sub_region
    "sub region": "sub_region",
    "sub_region": "sub_region",
    "subregion": "sub_region",
    # appellation
    "appellation": "appellation",
    "aoc": "appellation",
    "doc": "appellation",
    "docg": "appellation",
    "ava": "appellation",
    # country
    "country": "country",
    "origin": "country",
    "country of origin": "country",
    "country_of_origin": "country",
    # alcohol_percentage
    "alcohol": "alcohol_percentage",
    "alcohol %": "alcohol_percentage",
    "alcohol_percentage": "alcohol_percentage",
    "abv": "alcohol_percentage",
    "alcohol percentage": "alcohol_percentage",
    "alc": "alcohol_percentage",
    # wine_type_id
    "type": "wine_type_id",
    "wine type": "wine_type_id",
    "wine_type": "wine_type_id",
    "color": "wine_type_id",
    "colour": "wine_type_id",
    # classification
    "classification": "classification",
    "class": "classification",
    "grade": "classification",
    # price_tier
    "price": "price_tier",
    "price tier": "price_tier",
    "price_tier": "price_tier",
    # quantity
    "quantity": "quantity",
    "qty": "quantity",
    "bottles": "quantity",
    "count": "quantity",
    # purchase_date
    "purchase date": "purchase_date",
    "purchase_date": "purchase_date",
    "date bought": "purchase_date",
    "date purchased": "purchase_date",
    "date acquired": "purchase_date",
    "bought": "purchase_date",
    "acquired": "purchase_date",
    "purchase": "purchase_date",
    # case_size (bottles per case)
    "case size": "case_size",
    "case_size": "case_size",
    "bottles per case": "case_size",
    "bottles_per_case": "case_size",
    # cases (number of cases — maps to quantity)
    "cases": "num_cases",
    "number of cases": "num_cases",
    # notes (for transactions)
    "notes": "notes",
    "note": "notes",
    "tasting notes": "notes",
    # "description" intentionally omitted — ambiguous (could be wine name or
    # tasting notes depending on the source). Let AI mapping or user decide.
}

# Valid wine field names that can be mapped to
VALID_WINE_FIELDS = {
    "name", "winery", "vintage", "grape_variety", "region", "sub_region",
    "appellation", "country", "alcohol_percentage", "wine_type_id",
    "classification", "price_tier", "quantity", "num_cases", "case_size", "purchase_date",
    "notes",
}

# Core identifying fields for a wine record (name is required; others strongly recommended)
CANONICAL_WINE_FIELDS = ["name", "winery", "vintage", "grape_variety", "country", "region"]

# Human-readable descriptions for each wine field (used in AI mapping prompt)
WINE_FIELD_DESCRIPTIONS: dict[str, str] = {
    "name": "The wine name or label title (REQUIRED — rows without this are skipped)",
    "winery": "The winery, producer, domaine, château, or estate",
    "vintage": "The vintage year (integer)",
    "grape_variety": "The grape variety or varietal (e.g. Cabernet Sauvignon, Merlot)",
    "region": "The wine region (e.g. Bordeaux, Napa Valley, Rioja)",
    "sub_region": "A sub-region within the main region",
    "appellation": "The specific appellation, AOC, DOC, DOCG, or AVA",
    "country": "The country of origin",
    "alcohol_percentage": "The alcohol percentage (numeric, e.g. 13.5)",
    "wine_type_id": "The wine type: red, white, rosé, sparkling, fortified, or dessert",
    "classification": "Quality classification (e.g. Grand Cru, Reserva, DOCG)",
    "price_tier": "Price or price tier",
    "quantity": "Total number of bottles (integer)",
    "num_cases": "Number of cases — multiplied by case_size to get total bottles",
    "case_size": "Bottles per case (e.g. 6 or 12)",
    "purchase_date": "When you bought the wine (e.g. 2024-03-15, 15/03/2024)",
    "notes": "Tasting notes, description, or general notes",
}

# Minimum number of canonical fields (including name) that must match
# for auto-import to proceed without showing the mapping UI
MIN_CANONICAL_MATCHES = 2

# Number of rows per insert_many chunk during upload
UPLOAD_CHUNK_SIZE = 200

# Number of concurrent asyncio enrichment workers for pipelined imports
ENRICHMENT_WORKERS = 4

# Non-wine keywords for filtering
NON_WINE_KEYWORDS = {
    "whiskey", "whisky", "bourbon", "scotch", "cognac", "brandy",
    "gin", "vodka", "rum", "tequila", "mezcal", "beer", "ale",
    "lager", "stout", "sake", "liqueur", "liquor", "spirit",
    "spirits", "absinthe", "grappa", "armagnac", "cider",
}
