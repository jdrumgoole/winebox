"""Wine price tracker API endpoints.

Provides CRUD operations for price captures — individual bottle or shelf
observations with photo, price, and location data.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from winebox.config import settings
from winebox.models.price_capture import (
    CaptureType,
    GeoCoordinates,
    PriceCapture,
    ShopLocation,
)
from winebox.schemas.price_capture import PriceCaptureOut
from winebox.services.auth import RequireAuth

logger = logging.getLogger(__name__)

router = APIRouter()

# Sub-directory for price capture photos
PRICE_PHOTOS_DIR = "price_captures"


def _photo_storage_path() -> Path:
    """Get the directory for storing price capture photos."""
    path = settings.image_storage_path / PRICE_PHOTOS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _capture_to_out(capture: PriceCapture) -> PriceCaptureOut:
    """Convert a PriceCapture document to the API output schema."""
    photo_url = None
    if capture.photo_path:
        photo_url = f"/api/prices/photos/{capture.photo_path}"

    coords = None
    if capture.coordinates:
        coords = {
            "latitude": capture.coordinates.latitude,
            "longitude": capture.coordinates.longitude,
            "accuracy_metres": capture.coordinates.accuracy_metres,
        }

    return PriceCaptureOut(
        id=str(capture.id),
        capture_type=capture.capture_type.value,
        wine_name=capture.wine_name,
        vintage=capture.vintage,
        wine_type=capture.wine_type,
        price=capture.price,
        currency=capture.currency,
        notes=capture.notes,
        photo_url=photo_url,
        location={
            "shop_name": capture.location.shop_name,
            "town_city": capture.location.town_city,
            "state_county": capture.location.state_county,
            "country": capture.location.country,
        },
        coordinates=coords,
        captured_at=capture.captured_at,
        created_at=capture.created_at,
    )


@router.post("", response_model=PriceCaptureOut, status_code=status.HTTP_201_CREATED)
async def create_price_capture(
    current_user: RequireAuth,
    capture_type: str = Form("bottle"),
    wine_name: str | None = Form(None),
    vintage: int | None = Form(None),
    wine_type: str | None = Form(None),
    price: float | None = Form(None),
    currency: str = Form("EUR"),
    notes: str | None = Form(None),
    shop_name: str | None = Form(None),
    town_city: str | None = Form(None),
    state_county: str | None = Form(None),
    country: str | None = Form(None),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    accuracy_metres: float | None = Form(None),
    captured_at: str | None = Form(None),
    photo: UploadFile | None = File(None),
) -> PriceCaptureOut:
    """Create a new price capture with optional photo upload.

    Accepts multipart form data so the photo can be uploaded in the same
    request as the metadata.
    """
    # Validate capture type
    if capture_type not in ("bottle", "shelf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Capture type must be 'bottle' or 'shelf'.",
        )

    # Validate input lengths
    if wine_name and len(wine_name) > 500:
        raise HTTPException(status_code=422, detail="Wine name too long (max 500 characters).")
    if notes and len(notes) > 2000:
        raise HTTPException(status_code=422, detail="Notes too long (max 2000 characters).")

    # Save photo if provided
    photo_path = None
    if photo and photo.filename:
        # Validate content type
        if photo.content_type not in ("image/jpeg", "image/png", "image/webp", "image/heic"):
            raise HTTPException(status_code=422, detail="Photo must be JPEG, PNG, WebP, or HEIC.")

        # Read with size limit (10 MB)
        content = await photo.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Photo too large (max 10 MB).")

        ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else "jpg"
        filename = f"{uuid.uuid4().hex}.{ext}"
        dest = _photo_storage_path() / filename
        dest.write_bytes(content)
        photo_path = filename

    # Build coordinates
    coordinates = None
    if latitude is not None and longitude is not None:
        coordinates = GeoCoordinates(
            latitude=latitude,
            longitude=longitude,
            accuracy_metres=accuracy_metres,
        )

    # Parse captured_at
    capture_time = datetime.now(timezone.utc)
    if captured_at:
        try:
            capture_time = datetime.fromisoformat(captured_at)
        except ValueError:
            pass  # Fall back to now

    capture = PriceCapture(
        owner_id=current_user.id,
        capture_type=CaptureType(capture_type),
        wine_name=wine_name,
        vintage=vintage,
        wine_type=wine_type,
        price=price,
        currency=currency,
        notes=notes,
        photo_path=photo_path,
        location=ShopLocation(
            shop_name=shop_name,
            town_city=town_city,
            state_county=state_county,
            country=country,
        ),
        coordinates=coordinates,
        captured_at=capture_time,
    )
    await capture.insert()
    return _capture_to_out(capture)


@router.get("", response_model=list[PriceCaptureOut])
async def list_price_captures(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 50,
) -> list[PriceCaptureOut]:
    """List the current user's price captures, newest first."""
    if limit > 200:
        limit = 200
    captures = (
        await PriceCapture.find({"owner_id": current_user.id})
        .sort([("captured_at", -1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    return [_capture_to_out(c) for c in captures]


@router.get("/{capture_id}", response_model=PriceCaptureOut)
async def get_price_capture(
    capture_id: str,
    current_user: RequireAuth,
) -> PriceCaptureOut:
    """Get a single price capture by ID."""
    capture = await PriceCapture.find_one(
        {"_id": ObjectId(capture_id), "owner_id": current_user.id}
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Price capture not found.")
    return _capture_to_out(capture)


@router.delete("/{capture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price_capture(
    capture_id: str,
    current_user: RequireAuth,
) -> None:
    """Delete a price capture and its photo."""
    capture = await PriceCapture.find_one(
        {"_id": ObjectId(capture_id), "owner_id": current_user.id}
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Price capture not found.")

    # Remove photo file
    if capture.photo_path:
        photo_file = _photo_storage_path() / capture.photo_path
        if photo_file.exists():
            photo_file.unlink()

    await capture.delete()


@router.get("/photos/{filename}")
async def get_price_photo(
    filename: str,
    current_user: RequireAuth,
) -> FileResponse:
    """Serve a price capture photo.

    Only serves photos belonging to captures owned by the current user.
    """
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    # Verify the photo belongs to the current user
    capture = await PriceCapture.find_one(
        {"photo_path": filename, "owner_id": current_user.id}
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Photo not found.")

    photo_file = _photo_storage_path() / filename
    if not photo_file.exists():
        raise HTTPException(status_code=404, detail="Photo file not found.")

    return FileResponse(photo_file)
