"""Demo data API for loading and removing sample wines.

Lets new users populate their cellar with curated sample wines to explore
the app. Demo wines are tagged with custom_fields._demo = "true" so they
can be removed without affecting the user's real wines.

Pulls real wines from the X-Wines reference dataset (xwines_wines) so the
demo cellar looks authentic, with actual wine names, regions, and ratings.
"""

import ast
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from winebox.database import get_database
from winebox.models.transaction import Transaction, TransactionType
from winebox.models.wine import InventoryInfo, Wine
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()

DEMO_TAG = {"_demo": "true"}

# How many wines to load
DEMO_WINE_COUNT = 500

# Target distribution by wine type (approximate — actual depends on what's
# available in xwines_wines)
_TYPE_TARGETS = {
    "Red": 250,
    "White": 120,
    "Rosé": 30,
    "Sparkling": 50,
    "Dessert": 25,
    "Fortified": 25,
}

# Wine type mapping from X-Wines wine_type to our wine_type_id
_TYPE_MAP = {
    "Red": "red",
    "White": "white",
    "Rosé": "rose",
    "Sparkling": "sparkling",
    "Dessert": "dessert",
    "Fortified": "fortified",
}

# Checkout notes for realistic transaction history
_CHECKOUT_NOTES = [
    "Tuesday night pasta dinner",
    "Summer barbecue with friends",
    "Picnic at the park",
    "Birthday celebration",
    "Date night",
    "Holiday dinner",
    "Book club meeting",
    "Housewarming gift",
    "Friday night in",
    "Sunday roast",
    "Dinner party",
    "Cheese and wine evening",
    "Celebration dinner",
    "Weekend lunch",
    "Just because",
]


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


def _parse_grapes(grapes_str: str | None) -> str | None:
    """Parse X-Wines grapes field into a primary grape name."""
    if not grapes_str:
        return None
    try:
        parsed = ast.literal_eval(grapes_str)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    except (ValueError, SyntaxError):
        pass
    stripped = grapes_str.strip()
    if stripped and not stripped.startswith("["):
        return stripped
    return None


def _parse_vintages(vintages_str: str | None) -> list[int]:
    """Parse X-Wines vintages field into a list of ints."""
    if not vintages_str:
        return []
    try:
        parsed = ast.literal_eval(vintages_str)
        if isinstance(parsed, list):
            return [int(v) for v in parsed if v]
    except (ValueError, SyntaxError):
        pass
    return []


async def _select_demo_wines() -> list[dict[str, Any]]:
    """Select diverse wines from xwines_wines for the demo cellar.

    Stratifies by wine type, prefers popular wines (high rating_count),
    and picks a random vintage for each wine.

    Returns:
        List of dicts ready to create Wine documents.
    """
    db = get_database()
    xwines_col = db["xwines_wines"]
    prices_col = db["xwines_prices"]

    selected: list[dict[str, Any]] = []

    for wine_type, target in _TYPE_TARGETS.items():
        # Fetch popular wines of this type
        cursor = xwines_col.find(
            {"wine_type": wine_type, "rating_count": {"$gte": 25}},
            {
                "xwines_id": 1, "name": 1, "wine_type": 1, "grapes": 1,
                "abv": 1, "country": 1, "region_name": 1, "winery_name": 1,
                "avg_rating": 1, "rating_count": 1, "vintages": 1,
            },
        ).sort([("rating_count", -1)]).limit(target * 3)

        candidates = await cursor.to_list(length=target * 3)

        # Shuffle to avoid always picking the same top-N
        random.shuffle(candidates)
        chosen = candidates[:target]

        for doc in chosen:
            # Pick a vintage
            vintages = _parse_vintages(doc.get("vintages"))
            vintage = random.choice(vintages) if vintages else None

            # Random quantity (1-6 bottles, weighted toward small)
            quantity = random.choices([1, 2, 3, 4, 6], weights=[30, 25, 20, 15, 10])[0]

            wine_data: dict[str, Any] = {
                "name": doc["name"],
                "winery": doc.get("winery_name"),
                "vintage": vintage,
                "grape_variety": _parse_grapes(doc.get("grapes")),
                "region": doc.get("region_name"),
                "country": doc.get("country"),
                "alcohol_percentage": doc.get("abv"),
                "wine_type_id": _TYPE_MAP.get(wine_type, "red"),
                "xwines_id": doc.get("xwines_id"),
                "quantity": quantity,
            }

            selected.append(wine_data)

    # Look up prices for all selected wines (batch)
    xwines_ids = [w["xwines_id"] for w in selected if w.get("xwines_id")]
    if xwines_ids:
        price_cursor = prices_col.find(
            {"xwines_id": {"$in": xwines_ids}, "vintage": None},
            {"_id": 0, "xwines_id": 1, "price_low_usd": 1, "price_high_usd": 1, "price_tier": 1},
        )
        price_map: dict[int, dict] = {
            doc["xwines_id"]: doc async for doc in price_cursor
        }

        for wine_data in selected:
            xid = wine_data.get("xwines_id")
            if xid and xid in price_map:
                p = price_map[xid]
                wine_data["estimated_price_low"] = p.get("price_low_usd")
                wine_data["estimated_price_high"] = p.get("price_high_usd")
                wine_data["price_tier"] = p.get("price_tier")

    random.shuffle(selected)
    return selected[:DEMO_WINE_COUNT]


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

    Pulls 500 real wines from the X-Wines reference dataset, spanning
    multiple types, countries, and price tiers. Includes some check-out
    transactions for realistic history. Demo wines are tagged so they
    can be removed without affecting your real wines.
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

    # Select wines from X-Wines
    sample_wines = await _select_demo_wines()
    if not sample_wines:
        raise HTTPException(
            status_code=503,
            detail="No reference wine data available. The X-Wines dataset may not be loaded.",
        )

    now = datetime.now(timezone.utc)
    wines_created = 0
    total_bottles = 0
    countries: set[str] = set()
    wine_types: set[str] = set()
    checkout_candidates: list[tuple[Any, int]] = []  # (wine_id, max_checkout)

    for i, wine_data in enumerate(sample_wines):
        data = dict(wine_data)
        quantity = data.pop("quantity", 1)
        xwines_id = data.pop("xwines_id", None)

        # Stagger creation dates over the past year
        days_ago = len(sample_wines) - i
        created_at = now - timedelta(days=days_ago)

        wine = Wine(
            owner_id=current_user.id,
            custom_fields=DEMO_TAG,
            xwines_id=xwines_id,
            created_at=created_at,
            updated_at=created_at,
            inventory=InventoryInfo(quantity=quantity, updated_at=created_at),
            **data,
        )
        await wine.insert()

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
        total_bottles += quantity
        if data.get("country"):
            countries.add(data["country"])
        if data.get("wine_type_id"):
            wine_types.add(data["wine_type_id"])

        # Wines with 3+ bottles are checkout candidates
        if quantity >= 3:
            checkout_candidates.append((wine.id, quantity))

    # Create some check-out transactions (~10% of wines with enough stock)
    checkout_count = min(len(checkout_candidates), max(20, len(sample_wines) // 10))
    random.shuffle(checkout_candidates)

    for wine_id, max_qty in checkout_candidates[:checkout_count]:
        qty = random.randint(1, max(1, max_qty - 1))
        notes = random.choice(_CHECKOUT_NOTES)
        checkout_date = now - timedelta(days=random.randint(1, 60))

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

        wine = await Wine.find_one({"_id": wine_id})
        if wine:
            wine.inventory.quantity -= qty
            wine.inventory.updated_at = checkout_date
            wine.updated_at = checkout_date
            await wine.save()
            total_bottles -= qty

    logger.info(
        "Demo data installed for user %s: %d wines, %d bottles",
        current_user.id, wines_created, total_bottles,
    )

    return DemoInstallResponse(
        installed=wines_created,
        bottles=total_bottles,
        countries=len(countries),
        wine_types=len(wine_types),
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
