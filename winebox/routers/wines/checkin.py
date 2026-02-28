"""Wine check-in and check-out endpoints."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from winebox.models import InventoryInfo, Transaction, TransactionType, Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.analytics import posthog_service
from winebox.services.auth import RequireAuth

from ._common import (
    MAX_FIELD_LENGTH,
    MAX_NAME_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_OCR_TEXT_LENGTH,
    get_media_type,
    image_storage,
    ocr_service,
    vision_service,
    wine_parser,
)

logger = logging.getLogger(__name__)


async def checkin_wine(
    current_user: RequireAuth,
    front_label: Annotated[UploadFile, File(description="Front label image")],
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles")] = 1,
    back_label: Annotated[UploadFile | None, File(description="Back label image")] = None,
    name: Annotated[str | None, Form(max_length=MAX_NAME_LENGTH, description="Wine name (auto-detected if not provided)")] = None,
    winery: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    vintage: Annotated[int | None, Form(ge=1900, le=2100)] = None,
    grape_variety: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    region: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    sub_region: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    appellation: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    country: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    classification: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    alcohol_percentage: Annotated[float | None, Form(ge=0, le=100)] = None,
    wine_type_id: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-in notes")] = None,
    front_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned front label text")] = None,
    back_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned back label text")] = None,
    custom_fields: Annotated[str | None, Form(max_length=5000, description="Custom fields as JSON dict")] = None,
) -> WineWithInventory:
    """Check in wine bottles to the cellar.

    Upload front (required) and back (optional) label images.
    If front_label_text is provided (from a prior /scan call), scanning is skipped.
    Otherwise, uses Claude Vision for intelligent label analysis when available.
    You can override any auto-detected values.
    """
    # Save images
    front_image_path = await image_storage.save_image(front_label)
    back_image_path = None
    if back_label and back_label.filename:
        back_image_path = await image_storage.save_image(back_label)

    # Use pre-scanned text if provided (avoids duplicate API calls)
    front_text = front_label_text or ""
    back_text = back_label_text

    # Only scan if no pre-scanned text was provided and no name given
    if not front_label_text and not name:
        logger.info("No pre-scanned text provided, scanning labels...")

        # Read image data for analysis concurrently
        async def read_front() -> bytes:
            await front_label.seek(0)
            return await front_label.read()

        async def read_back() -> bytes | None:
            if back_label and back_label.filename:
                await back_label.seek(0)
                return await back_label.read()
            return None

        front_data, back_data = await asyncio.gather(read_front(), read_back())

        # Try Claude Vision first
        parsed_data = {}

        if vision_service.is_available():
            logger.info("Using Claude Vision for checkin analysis")
            try:
                front_media_type = get_media_type(front_label.filename)
                back_media_type = get_media_type(back_label.filename if back_label else None)

                result = await vision_service.analyze_labels(
                    front_image_data=front_data,
                    back_image_data=back_data,
                    front_media_type=front_media_type,
                    back_media_type=back_media_type,
                )
                parsed_data = result
                front_text = result.get("raw_text", "")
                back_text = result.get("back_label_text")
            except Exception as e:
                logger.warning(f"Claude Vision failed, falling back to Tesseract: {e}")

        # Fall back to Tesseract if needed
        if not parsed_data.get("name"):
            logger.info("Using Tesseract OCR for checkin analysis")
            front_text = await ocr_service.extract_text(front_image_path)
            if back_image_path:
                back_text = await ocr_service.extract_text(back_image_path)

            combined_text = front_text
            if back_text:
                combined_text = f"{front_text}\n{back_text}"
            parsed_data = wine_parser.parse(combined_text)

        # Use parsed values for fields not provided
        name = name or parsed_data.get("name")
        winery = winery or parsed_data.get("winery")
        vintage = vintage or parsed_data.get("vintage")
        grape_variety = grape_variety or parsed_data.get("grape_variety")
        region = region or parsed_data.get("region")
        sub_region = sub_region or parsed_data.get("sub_region")
        appellation = appellation or parsed_data.get("appellation")
        country = country or parsed_data.get("country")
        classification = classification or parsed_data.get("classification")
        alcohol_percentage = alcohol_percentage or parsed_data.get("alcohol_percentage")

    # Use provided values
    wine_name = name or "Unknown Wine"

    # Parse custom fields JSON
    parsed_custom_fields = None
    custom_fields_text = None
    if custom_fields:
        try:
            parsed_custom_fields = json.loads(custom_fields)
            if not isinstance(parsed_custom_fields, dict):
                raise ValueError("custom_fields must be a JSON object")
            # Ensure all values are strings
            parsed_custom_fields = {str(k): str(v) for k, v in parsed_custom_fields.items()}
            custom_fields_text = " ".join(
                f"{k} {v}" for k, v in parsed_custom_fields.items()
            ) if parsed_custom_fields else None
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid custom_fields JSON: {e}",
            )

    # Create wine document with embedded inventory
    wine = Wine(
        owner_id=current_user.id,
        name=wine_name,
        winery=winery,
        vintage=vintage,
        grape_variety=grape_variety,
        region=region,
        sub_region=sub_region,
        appellation=appellation,
        country=country,
        classification=classification,
        alcohol_percentage=alcohol_percentage,
        wine_type_id=wine_type_id,
        front_label_text=front_text,
        back_label_text=back_text,
        front_label_image_path=front_image_path,
        back_label_image_path=back_image_path,
        custom_fields=parsed_custom_fields,
        custom_fields_text=custom_fields_text,
        inventory=InventoryInfo(quantity=quantity, updated_at=datetime.now(timezone.utc)),
    )
    await wine.insert()

    # Create transaction
    transaction = Transaction(
        owner_id=current_user.id,
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_IN,
        quantity=quantity,
        notes=notes,
    )
    await transaction.insert()

    # Track check-in event
    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="wine_checkin",
        properties={
            "quantity": quantity,
            "scan_method": "claude_vision" if vision_service.is_available() else "tesseract",
            "country": country,
            "wine_id": str(wine.id),
        },
    )

    return WineWithInventory.model_validate(wine)


async def checkout_wine(
    wine_id: str,
    current_user: RequireAuth,
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles to remove")] = 1,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-out notes")] = None,
) -> WineWithInventory:
    """Check out wine bottles from the cellar.

    Remove bottles from inventory. If quantity reaches 0, the wine
    remains in history but shows as out of stock.
    """
    # Get wine - must belong to current user
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

    if wine.inventory.quantity < quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not enough bottles in stock. Available: {wine.inventory.quantity}, Requested: {quantity}",
        )

    # Create transaction
    transaction = Transaction(
        owner_id=current_user.id,
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_OUT,
        quantity=quantity,
        notes=notes,
    )
    await transaction.insert()

    # Update inventory
    wine.inventory.quantity -= quantity
    wine.inventory.updated_at = datetime.now(timezone.utc)
    wine.updated_at = datetime.now(timezone.utc)
    await wine.save()

    # Track check-out event
    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="wine_checkout",
        properties={
            "quantity": quantity,
            "remaining_quantity": wine.inventory.quantity,
            "wine_id": str(wine.id),
        },
    )

    return WineWithInventory.model_validate(wine)
