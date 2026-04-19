"""Wine CRUD endpoints (list, get, update, delete)."""

import logging
from datetime import datetime, timezone

from fastapi import Query

from winebox.models import ImportBatch, Transaction, Wine
from winebox.models.wine import WineCollection
from winebox.schemas.wine import WineResponse, WineUpdate, WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.cellar_event_view import list_wine_transactions
from winebox.services.cellar_inventory import attach_breakdowns
from winebox.services.rate_limit import MAX_PAGE_SIZE, MAX_USER_RESULTSET

from ._common import get_wine_or_404, image_storage

logger = logging.getLogger(__name__)


async def list_wines(
    current_user: RequireAuth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    in_stock: bool | None = None,
    collection: WineCollection | None = None,
) -> list[WineWithInventory]:
    """List all wines with optional filtering."""
    # Build filter conditions
    conditions: dict = {"owner_id": current_user.id}

    if collection:
        conditions["collection"] = collection.value

    if in_stock is True:
        conditions["inventory.quantity"] = {"$gt": 0}
    elif in_stock is False:
        conditions["inventory.quantity"] = 0

    query = Wine.find(conditions)
    wines = await query.skip(skip).limit(limit).sort([("created_at", -1)]).to_list()

    results = [WineWithInventory.model_validate(wine) for wine in wines]
    await attach_breakdowns(results, wines, current_user.id)
    return results


async def get_wine(
    wine_id: str,
    current_user: RequireAuth,
) -> WineResponse:
    """Get wine details with full transaction history."""
    wine = await get_wine_or_404(wine_id, current_user.id)

    # Transaction history comes from `cellar_events` via the
    # compatibility view — the Wine detail modal sees the same shape as
    # before but with added case-context fields.
    transactions = await list_wine_transactions(wine.id, current_user.id)

    response_data = wine.model_dump()
    response_data["transactions"] = [t.model_dump() for t in transactions]

    response = WineResponse.model_validate(response_data)
    await attach_breakdowns([response], [wine], current_user.id)
    return response


async def update_wine(
    wine_id: str,
    current_user: RequireAuth,
    wine_update: WineUpdate,
) -> WineWithInventory:
    """Update wine metadata."""
    wine = await get_wine_or_404(wine_id, current_user.id)

    # Update only provided fields
    update_data = wine_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(wine, field, value)

    # Recompute custom_fields_text if custom_fields was updated
    if "custom_fields" in update_data:
        cf = update_data["custom_fields"]
        wine.custom_fields_text = (
            " ".join(f"{k} {v}" for k, v in cf.items()) if cf else None
        )

    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    response = WineWithInventory.model_validate(wine)
    await attach_breakdowns([response], [wine], current_user.id)
    return response


async def delete_all_wines(
    current_user: RequireAuth,
) -> dict:
    """Delete all wines, transactions, images, and import batches for the current user."""
    # Find all wines belonging to the current user (bounded — see MAX_USER_RESULTSET).
    wines = await Wine.find({"owner_id": current_user.id}).to_list(length=MAX_USER_RESULTSET)

    # Delete label images for all wines
    deleted_images = 0
    for wine in wines:
        if wine.front_label_image_path:
            await image_storage.delete_image(wine.front_label_image_path)
            deleted_images += 1
        if wine.back_label_image_path:
            await image_storage.delete_image(wine.back_label_image_path)
            deleted_images += 1

    # Delete the user's history. Post-Phase-4 every event is a
    # CellarEvent, but legacy Transaction rows may still exist for
    # accounts that pre-date the migration — drain both collections so
    # `remove demo data` and admin "wipe my cellar" flows are clean.
    from winebox.models.cellar_event import CellarEvent
    delete_events_result = await CellarEvent.find(
        {"$or": [{"owner_id": current_user.id}, {"cellar_id": current_user.id}]}
    ).delete()
    deleted_events = delete_events_result.deleted_count if delete_events_result else 0
    delete_legacy_txns_result = await Transaction.find(
        {"owner_id": current_user.id}
    ).delete()
    deleted_legacy_txns = delete_legacy_txns_result.deleted_count if delete_legacy_txns_result else 0
    # Total surfaced under the same key the API has always returned so
    # clients don't notice the storage swap. Counts the union of new
    # events and any legacy Transaction rows.
    deleted_transactions = deleted_events + deleted_legacy_txns

    # Delete all import batches for this user
    delete_batches_result = await ImportBatch.find(
        {"owner_id": current_user.id}
    ).delete()
    deleted_import_batches = delete_batches_result.deleted_count if delete_batches_result else 0

    # Delete all wines for this user
    delete_wines_result = await Wine.find(
        {"owner_id": current_user.id}
    ).delete()
    deleted_wines = delete_wines_result.deleted_count if delete_wines_result else 0

    logger.info(
        "User %s deleted entire collection: %d wines, %d events (+%d legacy transactions), %d images, %d import batches",
        current_user.id, deleted_wines, deleted_events, deleted_legacy_txns, deleted_images, deleted_import_batches,
    )

    return {
        "deleted_wines": deleted_wines,
        "deleted_transactions": deleted_transactions,
        "deleted_images": deleted_images,
        "deleted_import_batches": deleted_import_batches,
    }


async def delete_wine(
    wine_id: str,
    current_user: RequireAuth,
) -> None:
    """Delete wine and all associated history."""
    wine = await get_wine_or_404(wine_id, current_user.id)

    # Delete associated images
    if wine.front_label_image_path:
        await image_storage.delete_image(wine.front_label_image_path)
    if wine.back_label_image_path:
        await image_storage.delete_image(wine.back_label_image_path)

    # Delete history — both the new CellarEvent rows and any pre-Phase-4
    # Transaction rows that might still exist for legacy wines.
    from winebox.models.cellar_event import CellarEvent
    await CellarEvent.find({"wine_id": wine.id}).delete()
    await Transaction.find({"wine_id": wine.id}).delete()

    # Delete wine
    await wine.delete()
