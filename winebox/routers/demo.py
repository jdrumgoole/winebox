"""Demo data API for loading and removing sample wines.

Lets new users populate their cellar with curated sample wines to explore
the app. Demo wines are tagged with custom_fields._demo = "true" so they
can be removed without affecting the user's real wines.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from winebox.models.transaction import Transaction, TransactionType
from winebox.models.wine import InventoryInfo, Wine
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()

DEMO_TAG = {"_demo": "true"}


# --- Response models ---

class DemoStatusResponse(BaseModel):
    installed: bool
    wine_count: int
    bottle_count: int


class DemoInstallResponse(BaseModel):
    installed: int
    bottles: int
    countries: int
    wine_types: int


class DemoRemoveResponse(BaseModel):
    wines_removed: int
    transactions_removed: int


# --- Sample wine data ---

SAMPLE_WINES: list[dict[str, Any]] = [
    # Red wines
    {
        "name": "Chateau Margaux",
        "winery": "Chateau Margaux",
        "vintage": 2015,
        "grape_variety": "Cabernet Sauvignon",
        "region": "Margaux",
        "sub_region": "Haut-Médoc",
        "appellation": "Margaux AOC",
        "country": "France",
        "alcohol_percentage": 13.5,
        "wine_type_id": "red",
        "classification": "Premier Grand Cru Classé",
        "price_tier": "ultra_premium",
        "estimated_price_low": 450.0,
        "estimated_price_high": 650.0,
        "drink_window_start": 2025,
        "drink_window_end": 2060,
        "producer_type": "estate",
        "quantity": 2,
    },
    {
        "name": "Opus One",
        "winery": "Opus One Winery",
        "vintage": 2019,
        "grape_variety": "Cabernet Sauvignon",
        "region": "Napa Valley",
        "sub_region": "Oakville",
        "country": "United States",
        "alcohol_percentage": 14.5,
        "wine_type_id": "red",
        "price_tier": "luxury",
        "estimated_price_low": 350.0,
        "estimated_price_high": 420.0,
        "drink_window_start": 2024,
        "drink_window_end": 2045,
        "producer_type": "estate",
        "quantity": 1,
    },
    {
        "name": "Barolo Monfortino Riserva",
        "winery": "Giacomo Conterno",
        "vintage": 2014,
        "grape_variety": "Nebbiolo",
        "region": "Piedmont",
        "sub_region": "Barolo",
        "appellation": "Barolo DOCG",
        "country": "Italy",
        "alcohol_percentage": 14.0,
        "wine_type_id": "red",
        "classification": "DOCG Riserva",
        "price_tier": "ultra_premium",
        "estimated_price_low": 500.0,
        "estimated_price_high": 800.0,
        "drink_window_start": 2028,
        "drink_window_end": 2060,
        "producer_type": "estate",
        "quantity": 3,
    },
    {
        "name": "Penfolds Grange",
        "winery": "Penfolds",
        "vintage": 2018,
        "grape_variety": "Shiraz",
        "region": "South Australia",
        "country": "Australia",
        "alcohol_percentage": 14.5,
        "wine_type_id": "red",
        "price_tier": "luxury",
        "estimated_price_low": 550.0,
        "estimated_price_high": 750.0,
        "drink_window_start": 2028,
        "drink_window_end": 2055,
        "producer_type": "estate",
        "quantity": 1,
    },
    {
        "name": "Fleur de Cruzeau",
        "winery": "Chateau de Cruzeau",
        "vintage": 2020,
        "grape_variety": "Merlot",
        "region": "Pessac-Léognan",
        "appellation": "Pessac-Léognan AOC",
        "country": "France",
        "alcohol_percentage": 13.0,
        "wine_type_id": "red",
        "price_tier": "value",
        "estimated_price_low": 12.0,
        "estimated_price_high": 18.0,
        "drink_window_start": 2022,
        "drink_window_end": 2028,
        "producer_type": "estate",
        "quantity": 6,
    },
    {
        "name": "Malbec Reserva",
        "winery": "Catena Zapata",
        "vintage": 2021,
        "grape_variety": "Malbec",
        "region": "Mendoza",
        "country": "Argentina",
        "alcohol_percentage": 13.5,
        "wine_type_id": "red",
        "price_tier": "mid_range",
        "estimated_price_low": 25.0,
        "estimated_price_high": 35.0,
        "drink_window_start": 2023,
        "drink_window_end": 2031,
        "producer_type": "estate",
        "quantity": 4,
    },
    {
        "name": "Rioja Gran Reserva 904",
        "winery": "La Rioja Alta",
        "vintage": 2015,
        "grape_variety": "Tempranillo",
        "region": "Rioja",
        "appellation": "Rioja DOCa",
        "country": "Spain",
        "alcohol_percentage": 13.5,
        "wine_type_id": "red",
        "classification": "Gran Reserva",
        "price_tier": "premium",
        "estimated_price_low": 55.0,
        "estimated_price_high": 75.0,
        "drink_window_start": 2025,
        "drink_window_end": 2040,
        "producer_type": "estate",
        "quantity": 3,
    },
    {
        "name": "Côtes du Rhône Rouge",
        "winery": "E. Guigal",
        "vintage": 2022,
        "grape_variety": "Grenache",
        "region": "Rhône Valley",
        "appellation": "Côtes du Rhône AOC",
        "country": "France",
        "alcohol_percentage": 14.0,
        "wine_type_id": "red",
        "price_tier": "budget",
        "estimated_price_low": 10.0,
        "estimated_price_high": 14.0,
        "drink_window_start": 2023,
        "drink_window_end": 2027,
        "producer_type": "negociant",
        "quantity": 12,
    },
    {
        "name": "Pinot Noir Willamette Valley",
        "winery": "Domaine Drouhin Oregon",
        "vintage": 2021,
        "grape_variety": "Pinot Noir",
        "region": "Willamette Valley",
        "country": "United States",
        "alcohol_percentage": 13.5,
        "wine_type_id": "red",
        "price_tier": "mid_range",
        "estimated_price_low": 35.0,
        "estimated_price_high": 45.0,
        "drink_window_start": 2023,
        "drink_window_end": 2032,
        "producer_type": "estate",
        "quantity": 2,
    },
    # White wines
    {
        "name": "Chablis Grand Cru Les Clos",
        "winery": "William Fèvre",
        "vintage": 2020,
        "grape_variety": "Chardonnay",
        "region": "Burgundy",
        "sub_region": "Chablis",
        "appellation": "Chablis Grand Cru AOC",
        "country": "France",
        "alcohol_percentage": 13.0,
        "wine_type_id": "white",
        "classification": "Grand Cru",
        "price_tier": "premium",
        "estimated_price_low": 75.0,
        "estimated_price_high": 100.0,
        "drink_window_start": 2024,
        "drink_window_end": 2040,
        "producer_type": "estate",
        "quantity": 2,
    },
    {
        "name": "Cloudy Bay Sauvignon Blanc",
        "winery": "Cloudy Bay",
        "vintage": 2023,
        "grape_variety": "Sauvignon Blanc",
        "region": "Marlborough",
        "country": "New Zealand",
        "alcohol_percentage": 13.0,
        "wine_type_id": "white",
        "price_tier": "value",
        "estimated_price_low": 18.0,
        "estimated_price_high": 24.0,
        "drink_window_start": 2024,
        "drink_window_end": 2026,
        "producer_type": "estate",
        "quantity": 6,
    },
    {
        "name": "Riesling Spätlese Ürziger Würzgarten",
        "winery": "Dr. Loosen",
        "vintage": 2022,
        "grape_variety": "Riesling",
        "region": "Mosel",
        "country": "Germany",
        "alcohol_percentage": 8.0,
        "wine_type_id": "white",
        "price_tier": "mid_range",
        "estimated_price_low": 25.0,
        "estimated_price_high": 35.0,
        "drink_window_start": 2024,
        "drink_window_end": 2040,
        "producer_type": "estate",
        "quantity": 4,
    },
    {
        "name": "Albariño Rias Baixas",
        "winery": "Pazo de Señoráns",
        "vintage": 2022,
        "grape_variety": "Albariño",
        "region": "Galicia",
        "appellation": "Rías Baixas DO",
        "country": "Spain",
        "alcohol_percentage": 12.5,
        "wine_type_id": "white",
        "price_tier": "value",
        "estimated_price_low": 18.0,
        "estimated_price_high": 24.0,
        "drink_window_start": 2023,
        "drink_window_end": 2026,
        "producer_type": "estate",
        "quantity": 3,
    },
    # Rosé
    {
        "name": "Whispering Angel",
        "winery": "Château d'Esclans",
        "vintage": 2023,
        "grape_variety": "Grenache",
        "region": "Provence",
        "appellation": "Côtes de Provence AOC",
        "country": "France",
        "alcohol_percentage": 13.0,
        "wine_type_id": "rose",
        "price_tier": "value",
        "estimated_price_low": 20.0,
        "estimated_price_high": 26.0,
        "drink_window_start": 2024,
        "drink_window_end": 2025,
        "producer_type": "estate",
        "quantity": 6,
    },
    # Sparkling
    {
        "name": "Dom Pérignon",
        "winery": "Moët & Chandon",
        "vintage": 2013,
        "grape_variety": "Chardonnay",
        "region": "Champagne",
        "appellation": "Champagne AOC",
        "country": "France",
        "alcohol_percentage": 12.5,
        "wine_type_id": "sparkling",
        "wine_subtype": "champagne",
        "classification": "Prestige Cuvée",
        "price_tier": "luxury",
        "estimated_price_low": 200.0,
        "estimated_price_high": 280.0,
        "drink_window_start": 2023,
        "drink_window_end": 2040,
        "producer_type": "estate",
        "quantity": 2,
    },
    {
        "name": "Prosecco Superiore Brut",
        "winery": "Bisol",
        "vintage": 2022,
        "grape_variety": "Glera",
        "region": "Veneto",
        "appellation": "Prosecco Superiore DOCG",
        "country": "Italy",
        "alcohol_percentage": 11.5,
        "wine_type_id": "sparkling",
        "wine_subtype": "prosecco",
        "price_tier": "value",
        "estimated_price_low": 16.0,
        "estimated_price_high": 22.0,
        "drink_window_start": 2023,
        "drink_window_end": 2025,
        "producer_type": "cooperative",
        "quantity": 4,
    },
    # Fortified
    {
        "name": "Vintage Port",
        "winery": "Taylor's",
        "vintage": 2017,
        "grape_variety": "Touriga Nacional",
        "region": "Douro Valley",
        "appellation": "Porto DOC",
        "country": "Portugal",
        "alcohol_percentage": 20.0,
        "wine_type_id": "fortified",
        "price_tier": "premium",
        "estimated_price_low": 65.0,
        "estimated_price_high": 85.0,
        "drink_window_start": 2030,
        "drink_window_end": 2070,
        "producer_type": "estate",
        "quantity": 3,
    },
    # Dessert
    {
        "name": "Sauternes",
        "winery": "Château d'Yquem",
        "vintage": 2017,
        "grape_variety": "Sémillon",
        "region": "Bordeaux",
        "sub_region": "Sauternes",
        "appellation": "Sauternes AOC",
        "country": "France",
        "alcohol_percentage": 14.0,
        "wine_type_id": "dessert",
        "classification": "Premier Cru Supérieur",
        "price_tier": "ultra_premium",
        "estimated_price_low": 350.0,
        "estimated_price_high": 500.0,
        "drink_window_start": 2025,
        "drink_window_end": 2070,
        "producer_type": "estate",
        "quantity": 1,
    },
]

# Wines to check out for realistic transaction history
_CHECKOUTS: dict[str, tuple[int, str]] = {
    "Côtes du Rhône Rouge": (4, "Tuesday night pasta dinner"),
    "Cloudy Bay Sauvignon Blanc": (2, "Summer barbecue with friends"),
    "Whispering Angel": (3, "Picnic at the park"),
    "Prosecco Superiore Brut": (2, "Birthday celebration"),
}


# --- Endpoints ---

@router.get("/status", response_model=DemoStatusResponse)
async def demo_status(current_user: RequireAuth) -> DemoStatusResponse:
    """Check whether sample wines are installed for the current user."""
    demo_wines = await Wine.find(
        {"owner_id": current_user.id, "custom_fields._demo": "true"}
    ).to_list()

    bottle_count = sum(w.inventory.quantity for w in demo_wines)

    return DemoStatusResponse(
        installed=len(demo_wines) > 0,
        wine_count=len(demo_wines),
        bottle_count=bottle_count,
    )


@router.post("/install", response_model=DemoInstallResponse)
async def install_demo(current_user: RequireAuth) -> DemoInstallResponse:
    """Load sample wines into the current user's cellar.

    Creates 18 wines spanning 6 types, 8 countries, and all price tiers.
    Includes some check-out transactions for realistic history.
    Demo wines are tagged so they can be removed without affecting your
    real wines.
    """
    # Check if already installed
    existing = await Wine.find_one(
        {"owner_id": current_user.id, "custom_fields._demo": "true"}
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Sample wines are already loaded. Remove them first to reload.",
        )

    now = datetime.now(timezone.utc)
    wines_created = 0
    wine_name_to_id: dict[str, Any] = {}

    for i, wine_data in enumerate(SAMPLE_WINES):
        data = dict(wine_data)
        quantity = data.pop("quantity", 1)

        # Stagger creation dates for realistic history
        days_ago = len(SAMPLE_WINES) * 3 - (i * 3)
        created_at = now - timedelta(days=days_ago)

        wine = Wine(
            owner_id=current_user.id,
            custom_fields=DEMO_TAG,
            created_at=created_at,
            updated_at=created_at,
            inventory=InventoryInfo(quantity=quantity, updated_at=created_at),
            **data,
        )
        await wine.insert()
        wine_name_to_id[wine.name] = wine.id

        # Create check-in transaction
        txn = Transaction(
            owner_id=current_user.id,
            wine_id=wine.id,
            transaction_type=TransactionType.CHECK_IN,
            quantity=quantity,
            transaction_date=created_at,
            created_at=created_at,
        )
        await txn.insert()
        wines_created += 1

    # Create check-out transactions
    for wine_name, (qty, notes) in _CHECKOUTS.items():
        wine_id = wine_name_to_id.get(wine_name)
        if not wine_id:
            continue

        checkout_date = now - timedelta(days=7 * list(_CHECKOUTS).index(wine_name) + 3)

        txn = Transaction(
            owner_id=current_user.id,
            wine_id=wine_id,
            transaction_type=TransactionType.CHECK_OUT,
            quantity=qty,
            notes=notes,
            transaction_date=checkout_date,
            created_at=checkout_date,
        )
        await txn.insert()

        # Update inventory
        wine = await Wine.find_one({"_id": wine_id})
        if wine:
            wine.inventory.quantity -= qty
            wine.inventory.updated_at = checkout_date
            wine.updated_at = checkout_date
            await wine.save()

    total_bottles = sum(
        w.get("quantity", 1) - _CHECKOUTS.get(w["name"], (0,))[0]
        for w in SAMPLE_WINES
    )
    countries = len(set(w["country"] for w in SAMPLE_WINES))
    wine_types = len(set(w["wine_type_id"] for w in SAMPLE_WINES))

    logger.info(
        "Demo data installed for user %s: %d wines, %d bottles",
        current_user.id, wines_created, total_bottles,
    )

    return DemoInstallResponse(
        installed=wines_created,
        bottles=total_bottles,
        countries=countries,
        wine_types=wine_types,
    )


@router.delete("/remove", response_model=DemoRemoveResponse)
async def remove_demo(current_user: RequireAuth) -> DemoRemoveResponse:
    """Remove all sample wines from the current user's cellar.

    Only removes wines tagged as demo data. Your own wines are not affected.
    """
    # Find demo wine IDs
    demo_wines = await Wine.find(
        {"owner_id": current_user.id, "custom_fields._demo": "true"}
    ).to_list()

    if not demo_wines:
        return DemoRemoveResponse(wines_removed=0, transactions_removed=0)

    demo_wine_ids = [w.id for w in demo_wines]

    # Delete transactions for demo wines
    txn_result = await Transaction.get_pymongo_collection().delete_many(
        {"owner_id": current_user.id, "wine_id": {"$in": demo_wine_ids}}
    )

    # Delete demo wines
    wine_result = await Wine.get_pymongo_collection().delete_many(
        {"owner_id": current_user.id, "custom_fields._demo": "true"}
    )

    logger.info(
        "Demo data removed for user %s: %d wines, %d transactions",
        current_user.id, wine_result.deleted_count, txn_result.deleted_count,
    )

    return DemoRemoveResponse(
        wines_removed=wine_result.deleted_count,
        transactions_removed=txn_result.deleted_count,
    )
