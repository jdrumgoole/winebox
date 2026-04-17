"""Search endpoints."""

import re
from datetime import datetime
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Query, Request

from winebox.models import Transaction, TransactionType, Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.rate_limit import MAX_PAGE_SIZE, MAX_USER_RESULTSET, make_limiter

router = APIRouter()


# Maximum length for search query parameters to prevent DoS
MAX_QUERY_LENGTH = 200

limiter = make_limiter()


@router.get("", response_model=list[WineWithInventory])
@limiter.limit("120/minute;2000/hour")
async def search_wines(
    request: Request,
    current_user: RequireAuth,
    q: Annotated[str | None, Query(description="Full-text search query", max_length=MAX_QUERY_LENGTH)] = None,
    vintage: Annotated[int | None, Query(description="Wine vintage year")] = None,
    grape: Annotated[str | None, Query(description="Grape variety", max_length=MAX_QUERY_LENGTH)] = None,
    winery: Annotated[str | None, Query(description="Winery name", max_length=MAX_QUERY_LENGTH)] = None,
    region: Annotated[str | None, Query(description="Wine region", max_length=MAX_QUERY_LENGTH)] = None,
    country: Annotated[str | None, Query(description="Country", max_length=MAX_QUERY_LENGTH)] = None,
    checked_in_after: Annotated[datetime | None, Query(description="Checked in after date")] = None,
    checked_in_before: Annotated[datetime | None, Query(description="Checked in before date")] = None,
    checked_out_after: Annotated[datetime | None, Query(description="Checked out after date")] = None,
    checked_out_before: Annotated[datetime | None, Query(description="Checked out before date")] = None,
    in_stock: Annotated[bool | None, Query(description="Only wines currently in stock")] = None,
    collection: Annotated[WineCollection | None, Query(description="Filter by collection: cellar or met")] = None,
    storage: Annotated[str | None, Query(description="Storage type: 'case' or 'loose'")] = None,
    provenance: Annotated[str | None, Query(description="Case provenance (where purchased)", max_length=MAX_QUERY_LENGTH)] = None,
    wine_type: Annotated[str | None, Query(description="Wine type: red, white, rosé, sparkling, etc.", max_length=MAX_QUERY_LENGTH)] = None,
    price_tier: Annotated[str | None, Query(description="Price tier: budget, value, mid_range, premium, luxury, ultra_premium", max_length=MAX_QUERY_LENGTH)] = None,
    enriched: Annotated[str | None, Query(description="Enrichment filter: 'yes' for enriched, 'no' for unenriched")] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
) -> list[WineWithInventory]:
    """Search wines by various criteria.

    Use `q` for full-text search across name, winery, region, and label text.
    Other parameters filter on specific fields.
    """
    # Build filter conditions - always filter by owner
    conditions = {"owner_id": current_user.id}

    if collection:
        conditions["collection"] = collection.value

    # Use MongoDB text search for full-text queries when available
    # Falls back to regex for compatibility (e.g., mongomock in tests)
    use_text_search = False
    if q:
        # Try to use MongoDB $text search which uses the text index
        # This is much faster than regex but requires a text index
        try:
            # Check if we can use text search (won't work in mongomock)
            test_result = await Wine.find({"$text": {"$search": q}}).limit(1).to_list()
            conditions["$text"] = {"$search": q}
            use_text_search = True
        except Exception:
            # Fall back to regex for case-insensitive search
            search_pattern = re.compile(re.escape(q), re.IGNORECASE)
            conditions["$or"] = [
                {"name": {"$regex": search_pattern}},
                {"winery": {"$regex": search_pattern}},
                {"region": {"$regex": search_pattern}},
                {"sub_region": {"$regex": search_pattern}},
                {"appellation": {"$regex": search_pattern}},
                {"country": {"$regex": search_pattern}},
                {"grape_variety": {"$regex": search_pattern}},
                {"front_label_text": {"$regex": search_pattern}},
                {"back_label_text": {"$regex": search_pattern}},
                {"custom_fields_text": {"$regex": search_pattern}},
            ]

    # Exact/partial matches on specific fields
    if vintage:
        conditions["vintage"] = vintage

    if grape:
        conditions["grape_variety"] = {"$regex": re.compile(re.escape(grape), re.IGNORECASE)}

    if winery:
        conditions["winery"] = {"$regex": re.compile(re.escape(winery), re.IGNORECASE)}

    if region:
        conditions["region"] = {"$regex": re.compile(re.escape(region), re.IGNORECASE)}

    if country:
        conditions["country"] = {"$regex": re.compile(re.escape(country), re.IGNORECASE)}

    if wine_type:
        conditions["wine_type_id"] = wine_type

    if price_tier:
        conditions["price_tier"] = price_tier

    if enriched == "yes":
        conditions["xwines_id"] = {"$ne": None}
    elif enriched == "no":
        conditions["xwines_id"] = None

    # Stock filter
    if in_stock is True:
        conditions["inventory.quantity"] = {"$gt": 0}
    elif in_stock is False:
        conditions["inventory.quantity"] = {"$lte": 0}

    # Filter by storage type (case/loose) via cellars collection
    if storage or provenance:
        from winebox.models.cellar import CellarItem
        cellar_col = CellarItem.get_pymongo_collection()
        cellar_query: dict = {"cellar_id": current_user.id}

        if storage == "case":
            cellar_query["item_type"] = "case"
        elif storage == "loose":
            cellar_query["item_type"] = "bottle"

        if provenance:
            prov_pattern = re.compile(re.escape(provenance), re.IGNORECASE)
            cellar_query["provenance"] = {"$regex": prov_pattern}

        matching_items = await cellar_col.find(
            cellar_query, {"wine.wine_id": 1}
        ).to_list(length=MAX_USER_RESULTSET)
        matching_wine_ids = {item["wine"]["wine_id"] for item in matching_items if item.get("wine")}
        if not matching_wine_ids:
            return []
        if "_id" in conditions and "$in" in conditions["_id"]:
            # Intersect with existing ID filter
            existing = set(conditions["_id"]["$in"])
            conditions["_id"] = {"$in": list(existing & matching_wine_ids)}
        else:
            conditions["_id"] = {"$in": list(matching_wine_ids)}

    # Get wine IDs filtered by transaction dates
    wine_ids_from_transactions = None

    if checked_in_after or checked_in_before:
        # Find wines with check-in transactions in date range (filtered by owner)
        checkin_filter = {"owner_id": current_user.id, "transaction_type": TransactionType.CHECK_IN}
        if checked_in_after:
            checkin_filter["transaction_date"] = {"$gte": checked_in_after}
        if checked_in_before:
            if "transaction_date" in checkin_filter:
                checkin_filter["transaction_date"]["$lte"] = checked_in_before
            else:
                checkin_filter["transaction_date"] = {"$lte": checked_in_before}

        checkin_transactions = await Transaction.find(checkin_filter).to_list(length=MAX_USER_RESULTSET)
        checkin_wine_ids = {t.wine_id for t in checkin_transactions}

        if wine_ids_from_transactions is None:
            wine_ids_from_transactions = checkin_wine_ids
        else:
            wine_ids_from_transactions &= checkin_wine_ids

    if checked_out_after or checked_out_before:
        # Find wines with check-out transactions in date range (filtered by owner)
        checkout_filter = {"owner_id": current_user.id, "transaction_type": TransactionType.CHECK_OUT}
        if checked_out_after:
            checkout_filter["transaction_date"] = {"$gte": checked_out_after}
        if checked_out_before:
            if "transaction_date" in checkout_filter:
                checkout_filter["transaction_date"]["$lte"] = checked_out_before
            else:
                checkout_filter["transaction_date"] = {"$lte": checked_out_before}

        checkout_transactions = await Transaction.find(checkout_filter).to_list(length=MAX_USER_RESULTSET)
        checkout_wine_ids = {t.wine_id for t in checkout_transactions}

        if wine_ids_from_transactions is None:
            wine_ids_from_transactions = checkout_wine_ids
        else:
            wine_ids_from_transactions &= checkout_wine_ids

    # Add wine ID filter if we filtered by transactions
    if wine_ids_from_transactions is not None:
        if not wine_ids_from_transactions:
            # No wines match the transaction criteria
            return []
        conditions["_id"] = {"$in": list(wine_ids_from_transactions)}

    # Execute query - use text score for sorting when using text search
    if use_text_search:
        # For text search, sort by relevance (text score) then by created_at
        wines = await Wine.find(
            conditions
        ).skip(skip).limit(limit).sort(
            [("score", {"$meta": "textScore"}), ("created_at", -1)]
        ).to_list()
    else:
        wines = await Wine.find(
            conditions
        ).skip(skip).limit(limit).sort([("created_at", -1)]).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]
