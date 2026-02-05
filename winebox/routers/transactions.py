"""Transaction history endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from winebox.database import get_db
from winebox.models import Transaction, TransactionType
from winebox.schemas.transaction import TransactionResponse
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 100,
    transaction_type: TransactionType | None = None,
    wine_id: str | None = None,
) -> list[TransactionResponse]:
    """List all transactions with optional filtering."""
    query = select(Transaction).options(selectinload(Transaction.wine))

    if transaction_type:
        query = query.where(Transaction.transaction_type == transaction_type)

    if wine_id:
        query = query.where(Transaction.wine_id == wine_id)

    query = query.offset(skip).limit(limit).order_by(Transaction.transaction_date.desc())
    result = await db.execute(query)
    transactions = result.scalars().all()

    return [TransactionResponse.model_validate(t) for t in transactions]


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransactionResponse:
    """Get a single transaction by ID."""
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.wine))
        .where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with ID {transaction_id} not found",
        )

    return TransactionResponse.model_validate(transaction)
