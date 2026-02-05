"""Wine management endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from winebox.config import settings
from winebox.database import get_db
from winebox.models import CellarInventory, Transaction, TransactionType, Wine
from winebox.schemas.wine import WineCreate, WineResponse, WineUpdate, WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.image_storage import ALLOWED_MIME_TYPES, ImageStorageService
from winebox.services.ocr import OCRService
from winebox.services.vision import ClaudeVisionService
from winebox.services.wine_parser import WineParserService

logger = logging.getLogger(__name__)

router = APIRouter()


async def validate_upload_size(upload_file: UploadFile, field_name: str) -> bytes:
    """Validate file size and return content.

    Args:
        upload_file: The uploaded file.
        field_name: Name of the field for error messages.

    Returns:
        The file content as bytes.

    Raises:
        HTTPException: If file exceeds size limit.
    """
    content = await upload_file.read()
    await upload_file.seek(0)

    if len(content) > settings.max_upload_size_bytes:
        max_mb = settings.max_upload_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"{field_name} exceeds maximum allowed size of {max_mb:.1f} MB",
        )
    return content

# Service dependencies
image_storage = ImageStorageService()
ocr_service = OCRService()
wine_parser = WineParserService()
vision_service = ClaudeVisionService()


def get_media_type(filename: str | None) -> str:
    """Get media type from filename."""
    if not filename:
        return "image/jpeg"
    ext = filename.lower().split(".")[-1]
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")


@router.post("/scan")
async def scan_label(
    current_user: RequireAuth,
    front_label: Annotated[UploadFile, File(description="Front label image")],
    back_label: Annotated[UploadFile | None, File(description="Back label image")] = None,
) -> dict:
    """Scan wine label images and extract text without creating a wine record.

    Uses Claude Vision for intelligent label analysis when available,
    falls back to Tesseract OCR otherwise.
    Uses user's API key if configured, otherwise falls back to system key.
    """
    # Validate and read image data with size limits
    front_data = await validate_upload_size(front_label, "Front label")

    back_data = None
    if back_label and back_label.filename:
        back_data = await validate_upload_size(back_label, "Back label")

    # Get user's API key (if they have one configured)
    user_api_key = current_user.anthropic_api_key

    # Try Claude Vision first
    if vision_service.is_available(user_api_key):
        logger.info("Using Claude Vision for label analysis")
        try:
            front_media_type = get_media_type(front_label.filename)
            back_media_type = get_media_type(back_label.filename if back_label else None)

            result = await vision_service.analyze_labels(
                front_image_data=front_data,
                back_image_data=back_data,
                front_media_type=front_media_type,
                back_media_type=back_media_type,
                user_api_key=user_api_key,
            )

            return {
                "parsed": {
                    "name": result.get("name"),
                    "winery": result.get("winery"),
                    "vintage": result.get("vintage"),
                    "grape_variety": result.get("grape_variety"),
                    "region": result.get("region"),
                    "country": result.get("country"),
                    "alcohol_percentage": result.get("alcohol_percentage"),
                },
                "ocr": {
                    "front_label_text": result.get("raw_text", ""),
                    "back_label_text": result.get("back_label_text"),
                },
                "method": "claude_vision",
            }
        except Exception as e:
            logger.warning(f"Claude Vision failed, falling back to Tesseract: {e}")

    # Fall back to Tesseract OCR
    logger.info("Using Tesseract OCR for label analysis")
    front_text = await ocr_service.extract_text_from_bytes(front_data)

    back_text = None
    if back_data:
        back_text = await ocr_service.extract_text_from_bytes(back_data)

    # Parse wine details from OCR text
    combined_text = front_text
    if back_text:
        combined_text = f"{front_text}\n{back_text}"
    parsed_data = wine_parser.parse(combined_text)

    return {
        "parsed": {
            "name": parsed_data.get("name"),
            "winery": parsed_data.get("winery"),
            "vintage": parsed_data.get("vintage"),
            "grape_variety": parsed_data.get("grape_variety"),
            "region": parsed_data.get("region"),
            "country": parsed_data.get("country"),
            "alcohol_percentage": parsed_data.get("alcohol_percentage"),
        },
        "ocr": {
            "front_label_text": front_text,
            "back_label_text": back_text,
        },
        "method": "tesseract",
    }


# Maximum lengths for form fields (security limits)
MAX_NAME_LENGTH = 500
MAX_FIELD_LENGTH = 200
MAX_NOTES_LENGTH = 2000
MAX_OCR_TEXT_LENGTH = 10000


@router.post("/checkin", response_model=WineWithInventory, status_code=status.HTTP_201_CREATED)
async def checkin_wine(
    current_user: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    front_label: Annotated[UploadFile, File(description="Front label image")],
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles")] = 1,
    back_label: Annotated[UploadFile | None, File(description="Back label image")] = None,
    name: Annotated[str | None, Form(max_length=MAX_NAME_LENGTH, description="Wine name (auto-detected if not provided)")] = None,
    winery: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    vintage: Annotated[int | None, Form(ge=1900, le=2100)] = None,
    grape_variety: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    region: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    country: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    alcohol_percentage: Annotated[float | None, Form(ge=0, le=100)] = None,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-in notes")] = None,
    front_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned front label text")] = None,
    back_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned back label text")] = None,
) -> WineWithInventory:
    """Check in wine bottles to the cellar.

    Upload front (required) and back (optional) label images.
    If front_label_text is provided (from a prior /scan call), scanning is skipped.
    Otherwise, uses Claude Vision for intelligent label analysis when available.
    Uses user's API key if configured, otherwise falls back to system key.
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

    # Get user's API key (if they have one configured)
    user_api_key = current_user.anthropic_api_key

    # Only scan if no pre-scanned text was provided and no name given
    if not front_label_text and not name:
        logger.info("No pre-scanned text provided, scanning labels...")

        # Read image data for analysis
        await front_label.seek(0)
        front_data = await front_label.read()

        back_data = None
        if back_label and back_label.filename:
            await back_label.seek(0)
            back_data = await back_label.read()

        # Try Claude Vision first
        parsed_data = {}

        if vision_service.is_available(user_api_key):
            logger.info("Using Claude Vision for checkin analysis")
            try:
                front_media_type = get_media_type(front_label.filename)
                back_media_type = get_media_type(back_label.filename if back_label else None)

                result = await vision_service.analyze_labels(
                    front_image_data=front_data,
                    back_image_data=back_data,
                    front_media_type=front_media_type,
                    back_media_type=back_media_type,
                    user_api_key=user_api_key,
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
        country = country or parsed_data.get("country")
        alcohol_percentage = alcohol_percentage or parsed_data.get("alcohol_percentage")

    # Use provided values
    wine_name = name or "Unknown Wine"

    # Create wine record
    wine = Wine(
        name=wine_name,
        winery=winery,
        vintage=vintage,
        grape_variety=grape_variety,
        region=region,
        country=country,
        alcohol_percentage=alcohol_percentage,
        front_label_text=front_text,
        back_label_text=back_text,
        front_label_image_path=front_image_path,
        back_label_image_path=back_image_path,
    )
    db.add(wine)
    await db.flush()  # Get the wine ID

    # Create transaction
    transaction = Transaction(
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_IN,
        quantity=quantity,
        notes=notes,
    )
    db.add(transaction)

    # Create or update inventory
    inventory = CellarInventory(
        wine_id=wine.id,
        quantity=quantity,
    )
    db.add(inventory)

    await db.commit()

    # Re-query with eager loading for relationships
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .where(Wine.id == wine.id)
    )
    wine = result.scalar_one()

    return WineWithInventory.model_validate(wine)


@router.post("/{wine_id}/checkout", response_model=WineWithInventory)
async def checkout_wine(
    wine_id: str,
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles to remove")] = 1,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-out notes")] = None,
) -> WineWithInventory:
    """Check out wine bottles from the cellar.

    Remove bottles from inventory. If quantity reaches 0, the wine
    remains in history but shows as out of stock.
    """
    # Get wine with inventory
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .where(Wine.id == wine_id)
    )
    wine = result.scalar_one_or_none()

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    if not wine.inventory or wine.inventory.quantity < quantity:
        available = wine.inventory.quantity if wine.inventory else 0
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not enough bottles in stock. Available: {available}, Requested: {quantity}",
        )

    # Create transaction
    transaction = Transaction(
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_OUT,
        quantity=quantity,
        notes=notes,
    )
    db.add(transaction)

    # Update inventory
    wine.inventory.quantity -= quantity

    await db.commit()

    # Re-query with eager loading for relationships
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .where(Wine.id == wine_id)
    )
    wine = result.scalar_one()

    return WineWithInventory.model_validate(wine)


@router.get("", response_model=list[WineWithInventory])
async def list_wines(
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = 0,
    limit: int = 100,
    in_stock: bool | None = None,
) -> list[WineWithInventory]:
    """List all wines with optional filtering."""
    query = select(Wine).options(selectinload(Wine.inventory))

    if in_stock is True:
        query = query.join(CellarInventory).where(CellarInventory.quantity > 0)
    elif in_stock is False:
        query = query.outerjoin(CellarInventory).where(
            (CellarInventory.quantity == 0) | (CellarInventory.quantity.is_(None))
        )

    query = query.offset(skip).limit(limit).order_by(Wine.created_at.desc())
    result = await db.execute(query)
    wines = result.scalars().all()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/{wine_id}", response_model=WineResponse)
async def get_wine(
    wine_id: str,
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WineResponse:
    """Get wine details with full transaction history."""
    result = await db.execute(
        select(Wine)
        .options(
            selectinload(Wine.inventory),
            selectinload(Wine.transactions),
        )
        .where(Wine.id == wine_id)
    )
    wine = result.scalar_one_or_none()

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    return WineResponse.model_validate(wine)


@router.put("/{wine_id}", response_model=WineWithInventory)
async def update_wine(
    wine_id: str,
    _: RequireAuth,
    wine_update: WineUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WineWithInventory:
    """Update wine metadata."""
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .where(Wine.id == wine_id)
    )
    wine = result.scalar_one_or_none()

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Update only provided fields
    update_data = wine_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(wine, field, value)

    await db.commit()

    # Re-query with eager loading for relationships
    result = await db.execute(
        select(Wine)
        .options(selectinload(Wine.inventory))
        .where(Wine.id == wine_id)
    )
    wine = result.scalar_one()

    return WineWithInventory.model_validate(wine)


@router.delete("/{wine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine(
    wine_id: str,
    _: RequireAuth,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete wine and all associated history."""
    result = await db.execute(select(Wine).where(Wine.id == wine_id))
    wine = result.scalar_one_or_none()

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Delete associated images
    await image_storage.delete_image(wine.front_label_image_path)
    if wine.back_label_image_path:
        await image_storage.delete_image(wine.back_label_image_path)

    await db.delete(wine)
    await db.commit()
