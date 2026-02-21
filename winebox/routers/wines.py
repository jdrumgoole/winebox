"""Wine management endpoints."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from winebox.config import settings
from winebox.models import (
    GrapeVariety,
    Transaction,
    TransactionType,
    Wine,
    GrapeBlendEntry,
    InventoryInfo,
    ScoreEntry,
)
from winebox.schemas.reference import (
    GrapeVarietyResponse,
    WineGrapeBlend,
    WineGrapeBlendUpdate,
    WineGrapeResponse,
    WineScoreCreate,
    WineScoreResponse,
    WineScoresResponse,
    WineScoreUpdate,
)
from winebox.schemas.wine import WineResponse, WineUpdate, WineWithInventory
from winebox.services.auth import RequireAuth
from winebox.services.image_storage import ImageStorageService
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
    """
    # Validate and read image data with size limits concurrently
    async def validate_front() -> bytes:
        return await validate_upload_size(front_label, "Front label")

    async def validate_back() -> bytes | None:
        if back_label and back_label.filename:
            return await validate_upload_size(back_label, "Back label")
        return None

    front_data, back_data = await asyncio.gather(validate_front(), validate_back())

    # Try Claude Vision first
    if vision_service.is_available():
        logger.info("Using Claude Vision for label analysis")
        try:
            front_media_type = get_media_type(front_label.filename)
            back_media_type = get_media_type(back_label.filename if back_label else None)

            result = await vision_service.analyze_labels(
                front_image_data=front_data,
                back_image_data=back_data,
                front_media_type=front_media_type,
                back_media_type=back_media_type,
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
        country = country or parsed_data.get("country")
        alcohol_percentage = alcohol_percentage or parsed_data.get("alcohol_percentage")

    # Use provided values
    wine_name = name or "Unknown Wine"

    # Create wine document with embedded inventory
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
        inventory=InventoryInfo(quantity=quantity, updated_at=datetime.utcnow()),
    )
    await wine.insert()

    # Create transaction
    transaction = Transaction(
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_IN,
        quantity=quantity,
        notes=notes,
    )
    await transaction.insert()

    return WineWithInventory.model_validate(wine)


@router.post("/{wine_id}/checkout", response_model=WineWithInventory)
async def checkout_wine(
    wine_id: str,
    _: RequireAuth,
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles to remove")] = 1,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Check-out notes")] = None,
) -> WineWithInventory:
    """Check out wine bottles from the cellar.

    Remove bottles from inventory. If quantity reaches 0, the wine
    remains in history but shows as out of stock.
    """
    # Get wine
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
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
        wine_id=wine.id,
        transaction_type=TransactionType.CHECK_OUT,
        quantity=quantity,
        notes=notes,
    )
    await transaction.insert()

    # Update inventory
    wine.inventory.quantity -= quantity
    wine.inventory.updated_at = datetime.utcnow()
    wine.updated_at = datetime.utcnow()
    await wine.save()

    return WineWithInventory.model_validate(wine)


@router.get("", response_model=list[WineWithInventory])
async def list_wines(
    _: RequireAuth,
    skip: int = 0,
    limit: int = 100,
    in_stock: bool | None = None,
) -> list[WineWithInventory]:
    """List all wines with optional filtering."""
    query = Wine.find()

    if in_stock is True:
        query = Wine.find(Wine.inventory.quantity > 0)
    elif in_stock is False:
        query = Wine.find(Wine.inventory.quantity == 0)

    wines = await query.skip(skip).limit(limit).sort(-Wine.created_at).to_list()

    return [WineWithInventory.model_validate(wine) for wine in wines]


@router.get("/{wine_id}", response_model=WineResponse)
async def get_wine(
    wine_id: str,
    _: RequireAuth,
) -> WineResponse:
    """Get wine details with full transaction history."""
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Get transactions for this wine
    transactions = await Transaction.find(
        Transaction.wine_id == wine.id
    ).sort(-Transaction.transaction_date).to_list()

    # Build response with transactions
    response_data = wine.model_dump()
    response_data["transactions"] = transactions

    return WineResponse.model_validate(response_data)


@router.put("/{wine_id}", response_model=WineWithInventory)
async def update_wine(
    wine_id: str,
    _: RequireAuth,
    wine_update: WineUpdate,
) -> WineWithInventory:
    """Update wine metadata."""
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
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

    wine.updated_at = datetime.utcnow()
    await wine.save()

    return WineWithInventory.model_validate(wine)


@router.delete("/{wine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine(
    wine_id: str,
    _: RequireAuth,
) -> None:
    """Delete wine and all associated history."""
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Delete associated images
    await image_storage.delete_image(wine.front_label_image_path)
    if wine.back_label_image_path:
        await image_storage.delete_image(wine.back_label_image_path)

    # Delete transactions
    await Transaction.find(Transaction.wine_id == wine.id).delete()

    # Delete wine
    await wine.delete()


# =============================================================================
# GRAPE BLEND ENDPOINTS
# =============================================================================


@router.get("/{wine_id}/grapes", response_model=WineGrapeBlend)
async def get_wine_grapes(
    wine_id: str,
    _: RequireAuth,
) -> WineGrapeBlend:
    """Get the grape blend for a wine."""
    # Verify wine exists
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
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


@router.post("/{wine_id}/grapes", response_model=WineGrapeBlend)
async def set_wine_grapes(
    wine_id: str,
    _: RequireAuth,
    blend: WineGrapeBlendUpdate,
) -> WineGrapeBlend:
    """Set the grape blend for a wine (replaces all existing grapes)."""
    # Verify wine exists
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Verify all grape varieties exist and get their details
    grape_ids = [g.grape_variety_id for g in blend.grapes]
    new_blends = []

    for grape_data in blend.grapes:
        # Try to find grape variety
        try:
            grape = await GrapeVariety.get(PydanticObjectId(grape_data.grape_variety_id))
        except Exception:
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
    wine.updated_at = datetime.utcnow()
    await wine.save()

    # Return updated blend
    return await get_wine_grapes(wine_id, _)


# =============================================================================
# WINE SCORE ENDPOINTS
# =============================================================================


@router.get("/{wine_id}/scores", response_model=WineScoresResponse)
async def get_wine_scores(
    wine_id: str,
    _: RequireAuth,
) -> WineScoresResponse:
    """Get all scores for a wine."""
    # Verify wine exists
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Build response from embedded scores
    scores_response = []
    for score in wine.scores:
        scores_response.append(WineScoreResponse(
            id=score.id,
            wine_id=wine_id,
            source=score.source,
            score=score.score,
            score_type=score.score_type,
            review_date=score.review_date,
            reviewer=score.reviewer,
            notes=score.notes,
            created_at=score.created_at,
            normalized_score=score.normalized_score,
        ))

    # Calculate average normalized score
    average_score = None
    if wine.scores:
        normalized_scores = [s.normalized_score for s in wine.scores]
        average_score = sum(normalized_scores) / len(normalized_scores)

    return WineScoresResponse(
        wine_id=wine_id,
        scores=scores_response,
        average_score=average_score,
    )


@router.post("/{wine_id}/scores", response_model=WineScoreResponse, status_code=status.HTTP_201_CREATED)
async def add_wine_score(
    wine_id: str,
    _: RequireAuth,
    score_data: WineScoreCreate,
) -> WineScoreResponse:
    """Add a score/rating for a wine."""
    # Verify wine exists
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Validate score type
    valid_score_types = ["100_point", "20_point", "5_star"]
    if score_data.score_type not in valid_score_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid score_type. Must be one of: {valid_score_types}",
        )

    # Create score entry
    score = ScoreEntry(
        id=str(uuid.uuid4()),
        source=score_data.source,
        score=score_data.score,
        score_type=score_data.score_type,
        review_date=score_data.review_date,
        reviewer=score_data.reviewer,
        notes=score_data.notes,
        created_at=datetime.utcnow(),
    )

    # Add to wine's scores
    wine.scores.append(score)
    wine.updated_at = datetime.utcnow()
    await wine.save()

    return WineScoreResponse(
        id=score.id,
        wine_id=wine_id,
        source=score.source,
        score=score.score,
        score_type=score.score_type,
        review_date=score.review_date,
        reviewer=score.reviewer,
        notes=score.notes,
        created_at=score.created_at,
        normalized_score=score.normalized_score,
    )


@router.put("/{wine_id}/scores/{score_id}", response_model=WineScoreResponse)
async def update_wine_score(
    wine_id: str,
    score_id: str,
    _: RequireAuth,
    score_update: WineScoreUpdate,
) -> WineScoreResponse:
    """Update a score for a wine."""
    # Get wine
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Find score
    score_index = None
    for i, s in enumerate(wine.scores):
        if s.id == score_id:
            score_index = i
            break

    if score_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Score with ID {score_id} not found for wine {wine_id}",
        )

    # Update fields
    update_data = score_update.model_dump(exclude_unset=True)

    # Validate score type if updating
    if "score_type" in update_data:
        valid_score_types = ["100_point", "20_point", "5_star"]
        if update_data["score_type"] not in valid_score_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid score_type. Must be one of: {valid_score_types}",
            )

    # Update the score entry
    score = wine.scores[score_index]
    for field, value in update_data.items():
        setattr(score, field, value)

    wine.updated_at = datetime.utcnow()
    await wine.save()

    return WineScoreResponse(
        id=score.id,
        wine_id=wine_id,
        source=score.source,
        score=score.score,
        score_type=score.score_type,
        review_date=score.review_date,
        reviewer=score.reviewer,
        notes=score.notes,
        created_at=score.created_at,
        normalized_score=score.normalized_score,
    )


@router.delete("/{wine_id}/scores/{score_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wine_score(
    wine_id: str,
    score_id: str,
    _: RequireAuth,
) -> None:
    """Delete a score from a wine."""
    try:
        wine = await Wine.get(PydanticObjectId(wine_id))
    except Exception:
        wine = None

    if not wine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wine with ID {wine_id} not found",
        )

    # Find and remove score
    original_count = len(wine.scores)
    wine.scores = [s for s in wine.scores if s.id != score_id]

    if len(wine.scores) == original_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Score with ID {score_id} not found for wine {wine_id}",
        )

    wine.updated_at = datetime.utcnow()
    await wine.save()
