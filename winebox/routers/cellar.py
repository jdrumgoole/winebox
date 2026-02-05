"""Cellar inventory endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from winebox.database import get_db
from winebox.models import CellarInventory, Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.auth import RequireAuth

router = APIRouter()


@router.get("", response_model=list[WineWithInventory])
async def get_cellar_inventory(
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 100,
) -> list[WineWithInventory]:
    """Get current cellar inventory (wines in stock)."""
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .join(CellarInventory)
        .where(CellarInventory.quantity > 0)
        .offset(skip)
        .limit(limit)
        .order_by(Wine.name)
    )
    wines = result.scalars().all()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/summary")
async def get_cellar_summary(
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Get cellar summary statistics."""
    # Total bottles in cellar
    total_bottles_result = await db.execute(
        select(func.sum(CellarInventory.quantity)).where(CellarInventory.quantity > 0)
    )
    total_bottles = total_bottles_result.scalar() or 0

    # Unique wines in stock
    unique_wines_result = await db.execute(
        select(func.count(CellarInventory.id)).where(CellarInventory.quantity > 0)
    )
    unique_wines = unique_wines_result.scalar() or 0

    # Total wines ever tracked (including out of stock)
    total_wines_result = await db.execute(select(func.count(Wine.id)))
    total_wines_tracked = total_wines_result.scalar() or 0

    # Wines by vintage (in stock)
    vintage_result = await db.execute(
        select(Wine.vintage, func.sum(CellarInventory.quantity))
        .join(CellarInventory)
        .where(CellarInventory.quantity > 0)
        .where(Wine.vintage.isnot(None))
        .group_by(Wine.vintage)
        .order_by(Wine.vintage.desc())
    )
    by_vintage = {str(row[0]): row[1] for row in vintage_result.all()}

    # Wines by country (in stock)
    country_result = await db.execute(
        select(Wine.country, func.sum(CellarInventory.quantity))
        .join(CellarInventory)
        .where(CellarInventory.quantity > 0)
        .where(Wine.country.isnot(None))
        .group_by(Wine.country)
        .order_by(func.sum(CellarInventory.quantity).desc())
    )
    by_country = {row[0]: row[1] for row in country_result.all()}

    # Wines by grape variety (in stock)
    grape_result = await db.execute(
        select(Wine.grape_variety, func.sum(CellarInventory.quantity))
        .join(CellarInventory)
        .where(CellarInventory.quantity > 0)
        .where(Wine.grape_variety.isnot(None))
        .group_by(Wine.grape_variety)
        .order_by(func.sum(CellarInventory.quantity).desc())
    )
    by_grape = {row[0]: row[1] for row in grape_result.all()}

    return {
        "total_bottles": total_bottles,
        "unique_wines": unique_wines,
        "total_wines_tracked": total_wines_tracked,
        "by_vintage": by_vintage,
        "by_country": by_country,
        "by_grape_variety": by_grape,
    }
