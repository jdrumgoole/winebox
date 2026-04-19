"""Add a met wine to the cellar."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Form, HTTPException, status

from winebox.models import InventoryInfo, Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineWithInventory
from winebox.services.analytics import posthog_service
from winebox.services.auth import RequireAuth

from ._common import get_wine_or_404

logger = logging.getLogger(__name__)


async def add_met_wine_to_cellar(
    met_wine_id: str,
    current_user: RequireAuth,
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles")] = 1,
) -> WineWithInventory:
    """Add a previously-met wine to the cellar.

    Creates a new cellar Wine document copying metadata from the met wine,
    then links the two together.
    """
    # Load the met wine
    met_wine = await get_wine_or_404(met_wine_id, current_user.id)

    if met_wine.collection != WineCollection.MET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This wine is not in the 'met' collection",
        )

    if met_wine.added_to_cellar:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This wine has already been added to your cellar",
        )

    now = datetime.now(timezone.utc)

    # Create a new cellar wine copying metadata from the met wine
    cellar_wine = Wine(
        owner_id=current_user.id,
        collection=WineCollection.CELLAR,
        name=met_wine.name,
        winery=met_wine.winery,
        vintage=met_wine.vintage,
        grape_variety=met_wine.grape_variety,
        region=met_wine.region,
        sub_region=met_wine.sub_region,
        appellation=met_wine.appellation,
        country=met_wine.country,
        classification=met_wine.classification,
        alcohol_percentage=met_wine.alcohol_percentage,
        wine_type=met_wine.wine_type,
        wine_subtype=met_wine.wine_subtype,
        price_tier=met_wine.price_tier,
        drink_window_start=met_wine.drink_window_start,
        drink_window_end=met_wine.drink_window_end,
        producer_type=met_wine.producer_type,
        front_label_text=met_wine.front_label_text,
        back_label_text=met_wine.back_label_text,
        front_label_image_path=met_wine.front_label_image_path,
        back_label_image_path=met_wine.back_label_image_path,
        enriched_fields=met_wine.enriched_fields,
        xwines_id=met_wine.xwines_id,
        custom_fields=met_wine.custom_fields,
        custom_fields_text=met_wine.custom_fields_text,
        inventory=InventoryInfo(quantity=quantity, updated_at=now),
        grape_blends=met_wine.grape_blends,
        scores=met_wine.scores,
        created_at=now,
        updated_at=now,
    )
    await cellar_wine.insert()

    # Create bottle records
    from winebox.services.bottle_service import create_bottles_for_wine
    # Phase 4 — `create_bottles_for_wine` writes the CellarEvent that
    # the activity feed and transactions API now read. Notes carry the
    # provenance hint that used to live on a separate Transaction row.
    await create_bottles_for_wine(
        owner_id=current_user.id,
        wine=cellar_wine,
        quantity=quantity,
        notes="Added from Wines I've Met",
    )

    # Link met wine to cellar wine
    met_wine.added_to_cellar = True
    met_wine.cellar_wine_id = cellar_wine.id
    met_wine.updated_at = now
    await met_wine.save()

    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="wine_added_to_cellar",
        properties={
            "met_wine_id": str(met_wine.id),
            "cellar_wine_id": str(cellar_wine.id),
            "quantity": quantity,
        },
    )

    return WineWithInventory.model_validate(cellar_wine)
