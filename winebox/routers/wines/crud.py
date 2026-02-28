"""Wine CRUD endpoints (list, get, update, delete)."""

import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import ValidationError

from winebox.models import ImportBatch, Transaction, Wine
from winebox.schemas.wine import WineResponse, WineUpdate, WineWithInventory
from winebox.services.auth import RequireAuth

from ._common import image_storage

logger = logging.getLogger(__name__)


async def list_wines(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 100,
    in_stock: bool | None = None,
) -> list[WineWithInventory]:
    """List all wines with optional filtering."""
    # Filter by owner
    if in_stock is True:
        query = Wine.find(
            Wine.owner_id == current_user.id,
            Wine.inventory.quantity > 0,
        )
    elif in_stock is False:
        query = Wine.find(
            Wine.owner_id == current_user.id,
            Wine.inventory.quantity == 0,
        )
    else:
        query = Wine.find(Wine.owner_id == current_user.id)

    wines = await query.skip(skip).limit(limit).sort(-Wine.created_at).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


async def get_wine(
    wine_id: str,
    current_user: RequireAuth,
) -> WineResponse:
    """Get wine details with full transaction history."""
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

    # Get transactions for this wine (owner already verified via wine ownership)
    transactions = await Transaction.find(
        Transaction.wine_id == wine.id
    ).sort(-Transaction.transaction_date).to_list()

    # Build response with transactions
    response_data = wine.model_dump()
    response_data["transactions"] = transactions

    return WineResponse.model_validate(response_data)


async def update_wine(
    wine_id: str,
    current_user: RequireAuth,
    wine_update: WineUpdate,
) -> WineWithInventory:
    """Update wine metadata."""
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

    return WineWithInventory.model_validate(wine)


async def delete_all_wines(
    current_user: RequireAuth,
) -> dict:
    """Delete all wines, transactions, images, and import batches for the current user."""
    # Find all wines belonging to the current user
    wines = await Wine.find(Wine.owner_id == current_user.id).to_list()

    # Delete label images for all wines
    deleted_images = 0
    for wine in wines:
        if wine.front_label_image_path:
            await image_storage.delete_image(wine.front_label_image_path)
            deleted_images += 1
        if wine.back_label_image_path:
            await image_storage.delete_image(wine.back_label_image_path)
            deleted_images += 1

    # Delete all transactions for this user
    delete_transactions_result = await Transaction.find(
        Transaction.owner_id == current_user.id
    ).delete()
    deleted_transactions = delete_transactions_result.deleted_count if delete_transactions_result else 0

    # Delete all import batches for this user
    delete_batches_result = await ImportBatch.find(
        ImportBatch.owner_id == current_user.id
    ).delete()
    deleted_import_batches = delete_batches_result.deleted_count if delete_batches_result else 0

    # Delete all wines for this user
    delete_wines_result = await Wine.find(
        Wine.owner_id == current_user.id
    ).delete()
    deleted_wines = delete_wines_result.deleted_count if delete_wines_result else 0

    logger.info(
        "User %s deleted entire collection: %d wines, %d transactions, %d images, %d import batches",
        current_user.id, deleted_wines, deleted_transactions, deleted_images, deleted_import_batches,
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

    # Delete associated images
    if wine.front_label_image_path:
        await image_storage.delete_image(wine.front_label_image_path)
    if wine.back_label_image_path:
        await image_storage.delete_image(wine.back_label_image_path)

    # Delete transactions
    await Transaction.find(Transaction.wine_id == wine.id).delete()

    # Delete wine
    await wine.delete()
