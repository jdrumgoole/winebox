"""Transaction history endpoints."""

import logging

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from winebox.models import Transaction, TransactionType, Wine
from winebox.schemas.transaction import TransactionResponse
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 100,
    transaction_type: TransactionType | None = None,
    wine_id: str | None = None,
) -> list[TransactionResponse]:
    """List all transactions with optional filtering."""
    # Always filter by owner
    conditions = {"owner_id": current_user.id}

    if transaction_type:
        conditions["transaction_type"] = transaction_type

    if wine_id:
        try:
            conditions["wine_id"] = PydanticObjectId(wine_id)
        except (InvalidId, ValidationError) as e:
            logger.debug("Invalid wine ID format in filter: %s - %s", wine_id, e)

    transactions = await Transaction.find(
        conditions
    ).skip(skip).limit(limit).sort(-Transaction.transaction_date).to_list()

    # Batch fetch all wine details (fixes N+1 query)
    wine_ids = list({t.wine_id for t in transactions})
    wines = await Wine.find({"_id": {"$in": wine_ids}}).to_list() if wine_ids else []
    wines_by_id = {wine.id: wine for wine in wines}

    # Build response with pre-fetched wine data
    results = []
    for t in transactions:
        wine = wines_by_id.get(t.wine_id)
        response_data = t.model_dump()
        if wine:
            response_data["wine"] = {
                "id": str(wine.id),
                "name": wine.name,
                "vintage": wine.vintage,
                "winery": wine.winery,
            }
        else:
            response_data["wine"] = None
        response_data["id"] = str(t.id)
        response_data["wine_id"] = str(t.wine_id)
        results.append(TransactionResponse.model_validate(response_data))

    return results


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: RequireAuth,
) -> TransactionResponse:
    """Get a single transaction by ID."""
    try:
        transaction = await Transaction.find_one(
            Transaction.id == PydanticObjectId(transaction_id),
            Transaction.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid transaction ID format: %s - %s", transaction_id, e)
        transaction = None

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with ID {transaction_id} not found",
        )

    # Get wine details
    wine = await Wine.get(transaction.wine_id)
    response_data = transaction.model_dump()
    if wine:
        response_data["wine"] = {
            "id": str(wine.id),
            "name": wine.name,
            "vintage": wine.vintage,
            "winery": wine.winery,
        }
    else:
        response_data["wine"] = None
    response_data["id"] = str(transaction.id)
    response_data["wine_id"] = str(transaction.wine_id)

    return TransactionResponse.model_validate(response_data)
