"""Search endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from winebox.database import get_db
from winebox.models import CellarInventory, Transaction, TransactionType, Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def search_wines(
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str | None, Query(description="Full-text search query")] = None,
    vintage: Annotated[int | None, Query(description="Wine vintage year")] = None,
    grape: Annotated[str | None, Query(description="Grape variety")] = None,
    winery: Annotated[str | None, Query(description="Winery name")] = None,
    region: Annotated[str | None, Query(description="Wine region")] = None,
    country: Annotated[str | None, Query(description="Country")] = None,
    checked_in_after: Annotated[datetime | None, Query(description="Checked in after date")] = None,
    checked_in_before: Annotated[datetime | None, Query(description="Checked in before date")] = None,
    checked_out_after: Annotated[datetime | None, Query(description="Checked out after date")] = None,
    checked_out_before: Annotated[datetime | None, Query(description="Checked out before date")] = None,
    in_stock: Annotated[bool | None, Query(description="Only wines currently in stock")] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[WineWithInventory]:
    """Search wines by various criteria.

    Use `q` for full-text search across name, winery, region, and label text.
    Other parameters filter on specific fields.
    """
    query = select(Wine).options(selectinload(Wine.inventory))
    conditions = []

    # Full-text search (simple LIKE-based search for SQLite)
    if q:
        search_pattern = f"%{q}%"
        conditions.append(
            or_(
                Wine.name.ilike(search_pattern),
                Wine.winery.ilike(search_pattern),
                Wine.region.ilike(search_pattern),
                Wine.country.ilike(search_pattern),
                Wine.grape_variety.ilike(search_pattern),
                Wine.front_label_text.ilike(search_pattern),
                Wine.back_label_text.ilike(search_pattern),
            )
        )

    # Exact/partial matches on specific fields
    if vintage:
        conditions.append(Wine.vintage == vintage)

    if grape:
        conditions.append(Wine.grape_variety.ilike(f"%{grape}%"))

    if winery:
        conditions.append(Wine.winery.ilike(f"%{winery}%"))

    if region:
        conditions.append(Wine.region.ilike(f"%{region}%"))

    if country:
        conditions.append(Wine.country.ilike(f"%{country}%"))

    # Date-based filters (based on transactions)
    if checked_in_after or checked_in_before:
        # Subquery to find wines with check-in transactions in date range
        checkin_subquery = (
            select(Transaction.wine_id)
            .where(Transaction.transaction_type == TransactionType.CHECK_IN)
        )
        if checked_in_after:
            checkin_subquery = checkin_subquery.where(
                Transaction.transaction_date >= checked_in_after
            )
        if checked_in_before:
            checkin_subquery = checkin_subquery.where(
                Transaction.transaction_date <= checked_in_before
            )
        conditions.append(Wine.id.in_(checkin_subquery))

    if checked_out_after or checked_out_before:
        # Subquery to find wines with check-out transactions in date range
        checkout_subquery = (
            select(Transaction.wine_id)
            .where(Transaction.transaction_type == TransactionType.CHECK_OUT)
        )
        if checked_out_after:
            checkout_subquery = checkout_subquery.where(
                Transaction.transaction_date >= checked_out_after
            )
        if checked_out_before:
            checkout_subquery = checkout_subquery.where(
                Transaction.transaction_date <= checked_out_before
            )
        conditions.append(Wine.id.in_(checkout_subquery))

    # Stock filter
    if in_stock is True:
        query = query.join(CellarInventory).where(CellarInventory.quantity > 0)
    elif in_stock is False:
        query = query.outerjoin(CellarInventory).where(
            (CellarInventory.quantity == 0) | (CellarInventory.quantity.is_(None))
        )

    # Apply all conditions
    if conditions:
        query = query.where(and_(*conditions))

    # Pagination and ordering
    query = query.offset(skip).limit(limit).order_by(Wine.created_at.desc())

    result = await db.execute(query)
    wines = result.scalars().all()

    return [WineWithInventory.model_validate(wine) for wine in wines]
