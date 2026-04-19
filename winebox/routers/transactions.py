"""Transaction history endpoints.

Post-Phase-4d, these endpoints read `cellar_events` and map each row to
a `TransactionResponse` via `services/cellar_event_view.py`. The `/api`
path + payload shape are unchanged — clients don't notice the swap.
"""

import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError

from winebox.models import RemovalReason, TransactionType
from winebox.schemas.transaction import TransactionResponse
from winebox.services.auth import RequireAuth
from winebox.services.cellar_event_view import (
    get_event_as_transaction,
    list_events_as_transactions,
)
from winebox.services.rate_limit import MAX_PAGE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    current_user: RequireAuth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    transaction_type: TransactionType | None = None,
    wine_id: str | None = None,
    removal_reason: RemovalReason | None = None,
) -> list[TransactionResponse]:
    """List all transactions with optional filtering."""
    wine_oid: ObjectId | None = None
    if wine_id:
        try:
            wine_oid = ObjectId(wine_id)
        except (InvalidId, ValidationError) as e:
            logger.debug("Invalid wine ID format in filter: %s - %s", wine_id, e)
            wine_oid = None

    return await list_events_as_transactions(
        current_user.id,
        skip=skip,
        limit=limit,
        transaction_type=transaction_type,
        wine_id=wine_oid,
        removal_reason=removal_reason,
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: RequireAuth,
) -> TransactionResponse:
    """Get a single transaction by ID.

    `transaction_id` is the CellarEvent id under the hood — the parameter
    name stays for API back-compat.
    """
    result = await get_event_as_transaction(current_user.id, transaction_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with ID {transaction_id} not found",
        )
    return result
