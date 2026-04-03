"""Import tests using rich CSV fixture files.

Each test uses a real CSV file from tests/data/ to exercise import
scenarios with realistic, varied wine data.
"""

import io
from pathlib import Path

import pytest
from httpx import AsyncClient

DATA_DIR = Path(__file__).parent / "data"


def _load_csv(filename: str) -> bytes:
    """Load a CSV fixture file as bytes."""
    return (DATA_DIR / filename).read_bytes()


async def _upload_and_map(
    client: AsyncClient,
    filename: str,
    mapping: dict[str, str],
    *,
    skip_duplicates: bool = True,
    skip_non_wine: bool = True,
) -> dict:
    """Helper: upload a CSV, set mapping, process, return result."""
    csv_data = _load_csv(filename)
    files = {"file": (filename, io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    assert upload_resp.status_code == 200, upload_resp.text
    batch_id = upload_resp.json()["batch_id"]

    map_resp = await client.post(
        f"/api/import/{batch_id}/mapping",
        json={"mapping": mapping},
    )
    assert map_resp.status_code == 200, map_resp.text

    process_resp = await client.post(
        f"/api/import/{batch_id}/process",
        json={
            "skip_non_wine": skip_non_wine,
            "default_quantity": 1,
            "skip_duplicates": skip_duplicates,
        },
    )
    assert process_resp.status_code == 200, process_resp.text
    result = process_resp.json()
    result["batch_id"] = batch_id
    return result


# =========================================================================
# Standard Collection — 10 wines across 8 countries, all wine types
# =========================================================================


@pytest.mark.asyncio
async def test_standard_collection_full_import(client: AsyncClient) -> None:
    """Import a standard wine collection with all canonical fields + price."""
    result = await _upload_and_map(client, "standard_collection.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Region": "region",
        "Grape": "grape_variety",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Price": "price_tier",
        "Notes": "notes",
    })
    assert result["wines_created"] == 10
    assert result["rows_skipped"] == 0

    # Verify wine data integrity
    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}

    # Check a selection of wines for correct field mapping
    margaux = wines["Chateau Margaux"]
    assert margaux["winery"] == "Chateau Margaux"
    assert margaux["vintage"] == 2015
    assert margaux["country"] == "France"
    assert margaux["region"] == "Bordeaux"
    assert margaux["grape_variety"] == "Cabernet Sauvignon"
    assert margaux["wine_type_id"] == "Red"
    assert margaux["inventory"]["quantity"] == 2
    assert margaux["price_tier"] == "$850"

    # Verify all 8 countries are represented
    countries = {w["country"] for w in wines.values()}
    assert countries == {
        "France", "Italy", "New Zealand", "Australia",
        "Spain", "Hungary", "Portugal", "Germany",
    }

    # Verify all wine types
    types = {w["wine_type_id"] for w in wines.values() if w.get("wine_type_id")}
    assert types == {"Red", "White", "Sparkling", "Dessert", "Rose", "Fortified"}


@pytest.mark.asyncio
async def test_standard_collection_price_as_custom(client: AsyncClient) -> None:
    """Import standard collection with price mapped as custom field."""
    result = await _upload_and_map(client, "standard_collection.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Price": "custom:Purchase Price",
        "Region": "skip",
        "Grape": "skip",
        "Type": "skip",
        "Quantity": "quantity",
        "Notes": "skip",
    })
    assert result["wines_created"] == 10

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}
    assert wines["Chateau Margaux"]["custom_fields"]["Purchase Price"] == "$850"
    assert wines["Whispering Angel Rose"]["custom_fields"]["Purchase Price"] == "$22"


# =========================================================================
# Mixed Beverages — wines + spirits, testing non-wine filtering
# =========================================================================


@pytest.mark.asyncio
async def test_mixed_beverages_filtering(client: AsyncClient) -> None:
    """Import mixed beverages CSV, spirits should be filtered out."""
    result = await _upload_and_map(client, "mixed_beverages.csv", {
        "Name": "name",
        "Producer": "winery",
        "Year": "vintage",
        "Country": "country",
        "Type": "wine_type_id",
        "Quantity": "quantity",
    }, skip_non_wine=True)

    # 16 rows: 7 wines + 9 spirits
    assert result["wines_created"] == 7
    assert result["rows_skipped"] == 9  # whiskey, gin, scotch, rum, tequila, bourbon, whisky, beer, stout

    wines_resp = await client.get("/api/wines")
    wine_names = {w["name"] for w in wines_resp.json()}
    assert "Chateau Margaux" in wine_names
    assert "Opus One" in wine_names
    assert "Chateau d'Yquem" in wine_names
    # Spirits should NOT be present
    assert "Jameson Irish Whiskey" not in wine_names
    assert "Tanqueray London Dry" not in wine_names
    assert "Sapporo Premium" not in wine_names
    assert "Guinness Extra Stout" not in wine_names


@pytest.mark.asyncio
async def test_mixed_beverages_no_filtering(client: AsyncClient) -> None:
    """Import mixed beverages with filtering disabled — all rows imported."""
    result = await _upload_and_map(client, "mixed_beverages.csv", {
        "Name": "name",
        "Producer": "winery",
        "Year": "vintage",
        "Country": "country",
        "Type": "wine_type_id",
        "Quantity": "quantity",
    }, skip_non_wine=False)

    assert result["wines_created"] == 16
    assert result["rows_skipped"] == 0


# =========================================================================
# Case Quantities — testing case_size × quantity multiplication
# =========================================================================


@pytest.mark.asyncio
async def test_case_quantities_multiplication(client: AsyncClient) -> None:
    """Import wines with case-based quantities — verify bottle totals."""
    result = await _upload_and_map(client, "case_quantities.csv", {
        "Wine Name": "name",
        "Winery": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Cases": "quantity",
        "Case Size": "case_size",
        "Region": "region",
        "Purchase Price per Case": "custom:Price per Case",
    })
    assert result["wines_created"] == 8

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}

    # 2 cases × 12 bottles = 24
    assert wines["Chateau Lafite Rothschild"]["inventory"]["quantity"] == 24
    # 1 case × 6 bottles = 6
    assert wines["Sassicaia"]["inventory"]["quantity"] == 6
    # 3 cases × 12 bottles = 36
    assert wines["Penfolds Bin 389"]["inventory"]["quantity"] == 36
    # 1 case × 3 bottles = 3
    assert wines["Vega Sicilia Unico"]["inventory"]["quantity"] == 3

    # Verify price stored as custom field
    assert wines["Chateau Lafite Rothschild"]["custom_fields"]["Price per Case"] == "$10200"

    # Total bottles across all wines
    total_bottles = sum(w["inventory"]["quantity"] for w in wines.values())
    assert total_bottles == 24 + 6 + 36 + 12 + 6 + 3 + 12 + 6  # = 105


# =========================================================================
# Purchase Dates — various date formats
# =========================================================================


@pytest.mark.asyncio
async def test_purchase_dates_parsing(client: AsyncClient) -> None:
    """Import wines with various date formats for purchase_date."""
    result = await _upload_and_map(client, "purchase_dates.csv", {
        "Wine Name": "name",
        "Winery": "winery",
        "Vintage": "vintage",
        "Date Purchased": "purchase_date",
        "Country": "country",
        "Quantity": "quantity",
    })
    assert result["wines_created"] == 8

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}

    # ISO format: 2023-06-15
    assert wines["Chateau Margaux"]["purchase_date"] is not None
    assert "2023-06-15" in wines["Chateau Margaux"]["purchase_date"]

    # DD/MM/YYYY: 15/03/2024
    assert wines["Barolo Riserva"]["purchase_date"] is not None
    assert "2024-03-15" in wines["Barolo Riserva"]["purchase_date"]

    # Missing date should be None
    assert wines["Vega Sicilia Unico"]["purchase_date"] is None


# =========================================================================
# Duplicate Detection — within-file and cross-import
# =========================================================================


@pytest.mark.asyncio
async def test_duplicates_within_file_skip(client: AsyncClient) -> None:
    """Import a CSV with duplicate wines — duplicates should be skipped."""
    # First we need existing wines to detect against.
    # The duplicates_test.csv has Margaux and Barolo each appearing twice.
    # Import once to establish the baseline.
    result1 = await _upload_and_map(client, "duplicates_test.csv", {
        "Wine Name": "name",
        "Winery": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Quantity": "quantity",
    }, skip_duplicates=False)
    # 6 rows, no dedup = all imported
    assert result1["wines_created"] == 6

    # Now import the same file again WITH skip_duplicates
    result2 = await _upload_and_map(client, "duplicates_test.csv", {
        "Wine Name": "name",
        "Winery": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Quantity": "quantity",
    }, skip_duplicates=True)
    # All 6 rows match existing wines (4 unique keys from first import)
    # so all should be skipped
    assert result2["wines_created"] == 0
    assert result2["rows_skipped"] == 6


@pytest.mark.asyncio
async def test_duplicates_cross_import_partial(client: AsyncClient) -> None:
    """Import overlapping CSVs — only new wines should be added."""
    # Import standard collection first
    result1 = await _upload_and_map(client, "standard_collection.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Region": "region",
        "Grape": "grape_variety",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Price": "price_tier",
        "Notes": "notes",
    }, skip_duplicates=False)
    assert result1["wines_created"] == 10

    # Now import purchase_dates.csv which shares some wines with standard_collection.
    # Matches by (name, winery, vintage):
    #   Chateau Margaux + Chateau Margaux + 2015 ✓
    #   Penfolds Grange + Penfolds + 2018 ✓
    #   Dom Perignon + Moet & Chandon + 2012 ✓
    #   Vega Sicilia Unico + Vega Sicilia + 2011 ✓
    # Non-matches (different name or winery):
    #   "Barolo Riserva" vs "Barolo Riserva Monfortino"
    #   "Cloudy Bay" vs "Cloudy Bay Sauvignon Blanc"
    #   Opus One (new), Tignanello (new)
    result2 = await _upload_and_map(client, "purchase_dates.csv", {
        "Wine Name": "name",
        "Winery": "winery",
        "Vintage": "vintage",
        "Date Purchased": "purchase_date",
        "Country": "country",
        "Quantity": "quantity",
    }, skip_duplicates=True)
    assert result2["wines_created"] == 4  # 4 new wines
    assert result2["rows_skipped"] == 4   # 4 duplicates skipped


# =========================================================================
# Messy Real-World Data — whitespace, accents, missing fields, bad vintages
# =========================================================================


@pytest.mark.asyncio
async def test_messy_data_handling(client: AsyncClient) -> None:
    """Import messy real-world CSV with whitespace, accents, empty rows, missing data."""
    result = await _upload_and_map(client, "messy_real_world.csv", {
        "wine": "name",
        "producer": "winery",
        "year": "vintage",
        "country": "country",
        "region": "region",
        "grape variety": "grape_variety",
        "abv": "alcohol_percentage",
        "qty": "quantity",
        "cellar location": "custom:Cellar Location",
        "price": "custom:Price",
    })

    # 10 data rows: 1 has blank name (row with just Unknown Winery)
    # so 9 wines created, 1 skipped (missing name)
    assert result["wines_created"] == 9
    assert result["rows_skipped"] == 1

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}

    # Accented characters preserved
    assert "Château Lafite-Rothschild" in wines
    assert "Dom Pérignon" in wines
    assert "Grüner Veltliner Smaragd" in wines
    assert "Tokaji Aszú 5 Puttonyos" in wines

    # Leading/trailing whitespace stripped
    assert "Barolo Riserva" in wines  # was " Barolo Riserva " in CSV
    barolo = wines["Barolo Riserva"]
    assert barolo["winery"] == "Giacomo Conterno"  # was "  Giacomo Conterno "

    # Alcohol percentage with % sign stripped
    lafite = wines["Château Lafite-Rothschild"]
    assert lafite["alcohol_percentage"] == 13.0

    # Float vintage coerced to int
    grange = wines["Penfolds Grange"]
    assert grange["vintage"] == 2018  # was "2018.0"

    # "NV" vintage should be None (not parseable as int in range)
    sancerre = wines["Sancerre Les Monts Damnés"]
    assert sancerre["vintage"] is None

    # Minimal wine with no winery/vintage still imported
    assert "My Favourite Red" in wines
    assert wines["My Favourite Red"]["winery"] is None

    # Custom fields preserved
    assert lafite["custom_fields"]["Price"] == "$850"
    assert lafite["custom_fields"]["Cellar Location"] == "Cave A Shelf 3"


# =========================================================================
# Custom Fields — rich metadata beyond canonical wine fields
# =========================================================================


@pytest.mark.asyncio
async def test_custom_fields_rich(client: AsyncClient) -> None:
    """Import with many custom fields — verify all are preserved."""
    result = await _upload_and_map(client, "custom_fields_rich.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Cellar Location": "custom:Cellar Location",
        "Purchase Price": "custom:Purchase Price",
        "Rating": "custom:Rating",
        "Drink Window": "custom:Drink Window",
        "Food Pairing": "custom:Food Pairing",
        "Occasion": "custom:Occasion",
    })
    assert result["wines_created"] == 8

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}

    margaux = wines["Chateau Margaux"]
    assert margaux["custom_fields"]["Cellar Location"] == "Cave A Rack 3"
    assert margaux["custom_fields"]["Purchase Price"] == "$850"
    assert margaux["custom_fields"]["Rating"] == "98"
    assert margaux["custom_fields"]["Drink Window"] == "2025-2060"
    assert margaux["custom_fields"]["Food Pairing"] == "Lamb and beef"
    assert margaux["custom_fields"]["Occasion"] == "Special dinner"

    # All 8 wines should have all 6 custom fields
    for wine in wines.values():
        assert wine["custom_fields"] is not None
        assert len(wine["custom_fields"]) == 6


# =========================================================================
# Minimal Data — wines with just a name, nothing else
# =========================================================================


@pytest.mark.asyncio
async def test_minimal_wines(client: AsyncClient) -> None:
    """Import wines with only a name — everything else defaults."""
    result = await _upload_and_map(client, "minimal_wines.csv", {
        "name": "name",
    })
    assert result["wines_created"] == 3

    wines_resp = await client.get("/api/wines")
    wines = {w["name"]: w for w in wines_resp.json()}
    expected_names = {"My Birthday Wine", "That Nice Red from Holiday", "Kitchen Red"}
    assert set(wines.keys()) == expected_names

    for wine in wines.values():
        assert wine["winery"] is None
        assert wine["vintage"] is None
        assert wine["country"] is None
        assert wine["inventory"]["quantity"] == 1  # default


# =========================================================================
# Auto-Mapping — verify header aliases resolve correctly
# =========================================================================


@pytest.mark.asyncio
async def test_auto_mapping_standard_headers(client: AsyncClient) -> None:
    """Verify that standard_collection.csv headers auto-map correctly."""
    csv_data = _load_csv("standard_collection.csv")
    files = {"file": ("standard_collection.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    data = upload_resp.json()

    suggested = data["suggested_mapping"]
    # These should be auto-mapped via HEADER_ALIASES
    assert suggested["Wine Name"] == "name"  # "wine name" alias
    assert suggested["Producer"] == "winery"  # "producer" alias
    assert suggested["Vintage"] == "vintage"
    assert suggested["Country"] == "country"
    assert suggested["Region"] == "region"
    assert suggested["Grape"] == "grape_variety"  # "grape" alias
    assert suggested["Type"] == "wine_type_id"  # "type" alias
    assert suggested["Quantity"] == "quantity"
    assert suggested["Price"] == "price_tier"  # "price" alias
    assert suggested["Notes"] == "notes"


@pytest.mark.asyncio
async def test_auto_mapping_case_quantities(client: AsyncClient) -> None:
    """Verify case_size header alias auto-maps correctly."""
    csv_data = _load_csv("case_quantities.csv")
    files = {"file": ("case_quantities.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    data = upload_resp.json()

    suggested = data["suggested_mapping"]
    assert suggested["Cases"] == "quantity"  # "cases" maps to quantity (number of cases)
    assert suggested["Case Size"] == "case_size"  # "case size" maps to bottles per case


@pytest.mark.asyncio
async def test_auto_mapping_purchase_dates(client: AsyncClient) -> None:
    """Verify purchase_date header alias auto-maps correctly."""
    csv_data = _load_csv("purchase_dates.csv")
    files = {"file": ("purchase_dates.csv", io.BytesIO(csv_data), "text/csv")}
    upload_resp = await client.post("/api/import/upload", files=files)
    data = upload_resp.json()

    suggested = data["suggested_mapping"]
    assert suggested["Date Purchased"] == "purchase_date"  # "date purchased" alias


# =========================================================================
# Undo Import — verify rollback with fixture data
# =========================================================================


@pytest.mark.asyncio
async def test_undo_standard_collection(client: AsyncClient) -> None:
    """Import standard collection, then undo — cellar should be empty."""
    result = await _upload_and_map(client, "standard_collection.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Region": "region",
        "Grape": "grape_variety",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Price": "price_tier",
        "Notes": "notes",
    })
    assert result["wines_created"] == 10

    # Undo
    undo_resp = await client.delete(f"/api/import/batches/{result['batch_id']}/wines")
    assert undo_resp.status_code == 200
    assert undo_resp.json()["wines_deleted"] == 10

    # Cellar should be empty
    wines_resp = await client.get("/api/wines")
    assert len(wines_resp.json()) == 0


# =========================================================================
# Case-Aware Import — rows with case_size create Case + linked Bottles
# =========================================================================


@pytest.mark.asyncio
async def test_case_import_creates_cases(client: AsyncClient) -> None:
    """Import with case_size creates Case records and links bottles to them."""
    result = await _upload_and_map(client, "case_import.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Case Size": "case_size",
        "Purchase Date": "purchase_date",
    })

    assert result["wines_created"] == 5

    # Check that cases were created
    cases_resp = await client.get("/api/cases")
    assert cases_resp.status_code == 200
    cases = cases_resp.json()["cases"]

    # Margaux: 2 cases of 6, Opus One: 1 case of 12, Dom Perignon: 1 case of 6
    # = 4 cases total
    assert len(cases) == 4

    # Verify case sizes
    case_sizes = sorted([c["case_size"] for c in cases])
    assert case_sizes == [6, 6, 6, 12]  # 2×6 (Margaux) + 1×12 (Opus) + 1×6 (Dom)

    # Verify total bottles
    bottles_resp = await client.get("/api/bottles")
    assert bottles_resp.status_code == 200
    all_bottles = bottles_resp.json()["bottles"]

    # Margaux: 2×6=12, Opus: 1×12=12, Cloudy Bay: 3 loose, Dom: 1×6=6, Barolo: 4 loose
    # Total: 12 + 12 + 3 + 6 + 4 = 37
    assert len(all_bottles) == 37

    # Verify loose bottles have no case_id
    loose_bottles = [b for b in all_bottles if b["case_id"] is None]
    assert len(loose_bottles) == 7  # 3 Cloudy Bay + 4 Barolo

    # Verify cased bottles have case_ids
    cased_bottles = [b for b in all_bottles if b["case_id"] is not None]
    assert len(cased_bottles) == 30  # 12 + 12 + 6


@pytest.mark.asyncio
async def test_case_import_bottles_per_case(client: AsyncClient) -> None:
    """Each case has exactly case_size bottles linked to it."""
    await _upload_and_map(client, "case_import.csv", {
        "Wine Name": "name",
        "Producer": "winery",
        "Vintage": "vintage",
        "Country": "country",
        "Type": "wine_type_id",
        "Quantity": "quantity",
        "Case Size": "case_size",
    })

    cases_resp = await client.get("/api/cases")
    cases = cases_resp.json()["cases"]

    for case in cases:
        case_detail = await client.get(f"/api/cases/{case['id']}")
        detail = case_detail.json()
        assert detail["bottles_remaining"] == detail["case_size"], (
            f"Case {case['id']} has {detail['bottles_remaining']} bottles "
            f"but case_size is {detail['case_size']}"
        )
