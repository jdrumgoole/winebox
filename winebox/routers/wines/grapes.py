"""Wine grape blend endpoints."""

import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import ValidationError

from winebox.models import GrapeBlendEntry, GrapeVariety, Wine
from winebox.schemas.reference import (
    GrapeVarietyResponse,
    WineGrapeBlend,
    WineGrapeBlendUpdate,
    WineGrapeResponse,
)
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)


async def get_wine_grapes(
    wine_id: str,
    current_user: RequireAuth,
) -> WineGrapeBlend:
    """Get the grape blend for a wine."""
    # Verify wine exists and belongs to current user
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Build response from embedded grape_blends
    grapes_response = []
    for blend in wine.grape_blends:
        grapes_response.append(WineGrapeResponse(
            id=blend.grape_variety_id,  # Use grape_variety_id as the ID
            grape_variety_id=blend.grape_variety_id,
            percentage=blend.percentage,
            grape_variety=GrapeVarietyResponse(
                id=blend.grape_variety_id,
                name=blend.grape_name,
                color=blend.color or "unknown",
                category=None,
                origin_country=None,
            ),
        ))

    # Calculate total percentage
    total_pct = None
    if wine.grape_blends:
        percentages = [g.percentage for g in wine.grape_blends if g.percentage is not None]
        if percentages:
            total_pct = sum(percentages)

    return WineGrapeBlend(
        wine_id=wine_id,
        grapes=grapes_response,
        total_percentage=total_pct,
    )


async def set_wine_grapes(
    wine_id: str,
    current_user: RequireAuth,
    blend: WineGrapeBlendUpdate,
) -> WineGrapeBlend:
    """Set the grape blend for a wine (replaces all existing grapes)."""
    # Verify wine exists and belongs to current user
    try:
        wine = await Wine.find_one(
            Wine.id == PydanticObjectId(wine_id),
            Wine.owner_id == current_user.id,
        )
    except (InvalidId, ValidationError) as e:
        logger.debug("Invalid wine ID format: %s - %s", wine_id, e)
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Verify all grape varieties exist and get their details
    new_blends = []

    for grape_data in blend.grapes:
        # Try to find grape variety
        try:
            grape = await GrapeVariety.get(PydanticObjectId(grape_data.grape_variety_id))
        except (InvalidId, ValidationError) as e:
            logger.debug("Invalid grape variety ID format: %s - %s", grape_data.grape_variety_id, e)
            grape = None

        if not grape:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Grape variety not found: {grape_data.grape_variety_id}",
            )

        new_blends.append(GrapeBlendEntry(
            grape_variety_id=str(grape.id),
            grape_name=grape.name,
            percentage=grape_data.percentage,
            color=grape.color,
        ))

    # Update wine with new grape blends
    wine.grape_blends = new_blends
    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    # Return updated blend
    return await get_wine_grapes(wine_id, current_user)
