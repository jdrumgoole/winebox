"""Checkout / remove bottles from the cellar."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Form, HTTPException, status

from winebox.models import RemovalReason, Transaction, TransactionType, Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.analytics import posthog_service
from winebox.services.auth import RequireAuth
from winebox.services.cellar_debit import (
    CellarDebitError,
    debit_cellar_for_wine,
    event_type_from_removal_reason,
)
from winebox.services.cellar_inventory import attach_breakdowns

from ._common import (
    MAX_FIELD_LENGTH,
    MAX_NOTES_LENGTH,
    get_wine_or_404,
)

logger = logging.getLogger(__name__)


async def checkout_wine(
    wine_id: str,
    current_user: RequireAuth,
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles to remove")] = 1,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-out notes")] = None,
    removal_reason: Annotated[RemovalReason | None, Form(description="Why the wine is being removed")] = None,
    tasting_notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Tasting notes (for drinks)")] = None,
    sale_price_usd: Annotated[float | None, Form(ge=0, description="Sale price in USD")] = None,
    gift_recipient: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH, description="Gift recipient name")] = None,
    removal_notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Notes about removal (breakage, loss, etc.)")] = None,
    cellar_item_id: Annotated[str | None, Form(description="Optional: the specific case or loose-bottle row to debit. When omitted, the server picks loose bottles first, then the oldest case.")] = None,
) -> WineWithInventory:
    """Remove wine bottles from the cellar.

    Remove bottles from inventory with an optional reason (drank, sold, gifted, other).
    If quantity reaches 0, the wine remains in history but shows as out of stock.

    When `cellar_item_id` is supplied the debit is taken from that specific
    physical row (a named case with its own provenance, or a loose-bottle
    row), preserving the user's case-level bookkeeping. When omitted, the
    server drains loose bottles first, then the oldest case.
    """
    # Server-side validation for removal reason fields
    if removal_reason == RemovalReason.SELL and sale_price_usd is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Sale price is required when removing wine as sold",
        )
    if removal_reason == RemovalReason.GIFT and not gift_recipient:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Recipient name is required when gifting wine",
        )

    # Get wine - must belong to current user
    wine = await get_wine_or_404(wine_id, current_user.id)

    # When the caller picks a specific source, defer the insufficiency
    # check to the debit service so the error message names the source
    # ("Source has 6 bottles; cannot remove 7") instead of the aggregate.
    # Without a picked source, keep the legacy aggregate check so existing
    # clients see the same 400 status code they've always seen.
    if cellar_item_id is None and wine.inventory.quantity < quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not enough bottles in stock. Available: {wine.inventory.quantity}, Requested: {quantity}",
        )

    # Case-aware debit: route through the shared service so the physical
    # rows in the cellars collection and the CellarEvent log stay in step
    # with Wine.inventory. The service may spread the debit across several
    # CellarItem rows when no specific source is named.
    try:
        debited = await debit_cellar_for_wine(
            wine_id=wine.id,
            owner_id=current_user.id,
            quantity=quantity,
            cellar_item_id=cellar_item_id,
            event_type=event_type_from_removal_reason(removal_reason),
            removal_reason=removal_reason,
            event_notes=notes,
            removal_notes=removal_notes,
            sale_price=sale_price_usd,
            gift_recipient=gift_recipient,
            tasting_notes=tasting_notes,
        )
    except CellarDebitError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    # Build transaction kwargs, only including removal fields when relevant
    transaction_kwargs: dict = {
        "owner_id": current_user.id,
        "wine_id": wine.id,
        "transaction_type": TransactionType.REMOVED,
        "quantity": quantity,
        "notes": notes,
    }
    if removal_reason is not None:
        transaction_kwargs["removal_reason"] = removal_reason
        if removal_reason == RemovalReason.DRINK and tasting_notes:
            transaction_kwargs["tasting_notes"] = tasting_notes
        elif removal_reason == RemovalReason.SELL:
            transaction_kwargs["sale_price_usd"] = sale_price_usd
        elif removal_reason == RemovalReason.GIFT:
            transaction_kwargs["gift_recipient"] = gift_recipient
        elif removal_reason == RemovalReason.OTHER and removal_notes:
            transaction_kwargs["removal_notes"] = removal_notes

    # Create transaction (Phase 4 will converge this onto CellarEvent)
    transaction = Transaction(**transaction_kwargs)
    await transaction.insert()

    # Update aggregate inventory so the Wine doc stays consistent with
    # the per-row debits the debit service just applied.
    wine.inventory.quantity -= quantity
    wine.inventory.updated_at = datetime.now(timezone.utc)
    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    # If quantity hit 0, clear added_to_cellar flag on any linked met wine
    if wine.inventory.quantity == 0:
        met_wine = await Wine.find_one(
            {"cellar_wine_id": wine.id, "owner_id": current_user.id}
        )
        if met_wine:
            met_wine.added_to_cellar = False
            met_wine.cellar_wine_id = None
            met_wine.updated_at = datetime.now(timezone.utc)
            await met_wine.save()

    # Track removal event
    removal_properties: dict = {
        "quantity": quantity,
        "remaining_quantity": wine.inventory.quantity,
        "wine_id": str(wine.id),
    }
    if removal_reason:
        removal_properties["removal_reason"] = removal_reason.value
    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="wine_removed",
        properties=removal_properties,
    )

    response = WineWithInventory.model_validate(wine)
    await attach_breakdowns([response], [wine], current_user.id)
    return response
