"""Wine price tracker API endpoints.

Provides CRUD operations for wine prices — each wine (identified by
name + vintage + type) accumulates a list of price observations from
multiple sources.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from winebox.config import settings
from winebox.models.price_capture import (
    CaptureType,
    GeoCoordinates,
    ShopLocation,
)
from winebox.models.wine_price import (
    PriceEntry,
    PriceSource,
    WinePrice,
    WinePriceHistory,
)
from winebox.schemas.wine_price import (
    PriceEntryOut,
    WinePriceHistoryEntryOut,
    WinePriceOut,
    WinePriceSummaryOut,
)
from winebox.services.auth import RequireAuth
from winebox.services.price_service import add_price_entry

logger = logging.getLogger(__name__)

router = APIRouter()

# Sub-directory for price capture photos
PRICE_PHOTOS_DIR = "price_captures"


def _photo_storage_path() -> Path:
    """Get the directory for storing price capture photos."""
    path = settings.image_storage_path / PRICE_PHOTOS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _entry_to_out(entry: PriceEntry, current_user_id: ObjectId | None = None) -> PriceEntryOut:
    """Convert a PriceEntry to the API output schema.

    `WinePrice` is a global crowdsourced document — many users contribute
    entries for the same wine. To avoid leaking other users' PII via
    `GET /api/prices/{wine_price_id}`, sensitive fields (owner_id, GPS
    coordinates, town/state, free-form notes, and the photo URL — which
    is gated by ownership anyway) are only emitted when the requester
    owns the entry. Aggregate fields (price, currency, timestamp, shop
    name, country) are always emitted so price comparison still works.
    """
    is_owner = current_user_id is not None and entry.owner_id == current_user_id

    photo_url = None
    coords = None
    if is_owner:
        if entry.photo_path:
            photo_url = f"/api/prices/photos/{entry.photo_path}"
        if entry.coordinates:
            coords = {
                "latitude": entry.coordinates.latitude,
                "longitude": entry.coordinates.longitude,
                "accuracy_metres": entry.coordinates.accuracy_metres,
            }

    return PriceEntryOut(
        timestamp=entry.timestamp,
        source=entry.source.value,
        price=entry.price,
        currency=entry.currency,
        owner_id=str(entry.owner_id) if (is_owner and entry.owner_id) else None,
        location={
            "shop_name": entry.location.shop_name,
            "town_city": entry.location.town_city if is_owner else None,
            "state_county": entry.location.state_county if is_owner else None,
            "country": entry.location.country,
        },
        coordinates=coords,
        notes=entry.notes if is_owner else None,
        photo_url=photo_url,
        capture_type=entry.capture_type.value if entry.capture_type else None,
    )


def _wine_price_to_out(doc: WinePrice, current_user_id: ObjectId | None = None) -> WinePriceOut:
    """Convert a WinePrice document to the API output schema."""
    return WinePriceOut(
        id=str(doc.id),
        wine_name=doc.wine_name,
        vintage=doc.vintage,
        wine_type=doc.wine_type,
        prices=[_entry_to_out(e, current_user_id) for e in doc.prices],
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _wine_price_to_summary(doc: WinePrice) -> WinePriceSummaryOut:
    """Convert a WinePrice document to a summary."""
    latest = doc.prices[-1] if doc.prices else None
    return WinePriceSummaryOut(
        id=str(doc.id),
        wine_name=doc.wine_name,
        vintage=doc.vintage,
        wine_type=doc.wine_type,
        price_count=len(doc.prices),
        latest_price=latest.price if latest else None,
        latest_currency=latest.currency if latest else None,
        latest_timestamp=latest.timestamp if latest else None,
    )


@router.post("", response_model=WinePriceOut, status_code=status.HTTP_201_CREATED)
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
) -> WinePriceOut:
    """Create a new price observation for a wine.

    Accepts multipart form data so the photo can be uploaded in the same
    request as the metadata. The price is added to the wine's price
    history, creating the wine document if it doesn't exist yet.
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

    # Wine name is required for grouping
    if not wine_name:
        raise HTTPException(status_code=422, detail="Wine name is required.")

    # Price is required
    if price is None:
        raise HTTPException(status_code=422, detail="Price is required.")

    # Save photo if provided
    photo_path = None
    if photo and photo.filename:
        if photo.content_type not in ("image/jpeg", "image/png", "image/webp", "image/heic"):
            raise HTTPException(status_code=422, detail="Photo must be JPEG, PNG, WebP, or HEIC.")

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
            pass

    entry = PriceEntry(
        timestamp=capture_time,
        source=PriceSource.PRICE_CAPTURE_APP,
        price=price,
        currency=currency,
        owner_id=current_user.id,
        location=ShopLocation(
            shop_name=shop_name,
            town_city=town_city,
            state_county=state_county,
            country=country,
        ),
        coordinates=coordinates,
        notes=notes,
        photo_path=photo_path,
        capture_type=CaptureType(capture_type),
    )

    doc = await add_price_entry(
        wine_name=wine_name,
        vintage=vintage,
        wine_type=wine_type,
        entry=entry,
    )
    return _wine_price_to_out(doc, current_user.id)


@router.get("", response_model=list[WinePriceSummaryOut])
async def list_wine_prices(
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 50,
) -> list[WinePriceSummaryOut]:
    """List wines where the current user has contributed prices."""
    if limit > 200:
        limit = 200
    docs = (
        await WinePrice.find({"prices.owner_id": current_user.id})
        .sort([("updated_at", -1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    return [_wine_price_to_summary(d) for d in docs]


@router.get("/{wine_price_id}", response_model=WinePriceOut)
async def get_wine_price(
    wine_price_id: str,
    current_user: RequireAuth,
) -> WinePriceOut:
    """Get a wine's full price history."""
    doc = await WinePrice.find_one({"_id": ObjectId(wine_price_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Wine price not found.")
    return _wine_price_to_out(doc, current_user.id)


@router.delete(
    "/{wine_price_id}/entries/{entry_index}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_price_entry(
    wine_price_id: str,
    entry_index: int,
    current_user: RequireAuth,
) -> None:
    """Delete a specific price entry from a wine's price history.

    Only the user who created the entry can delete it. If the prices
    array becomes empty, the entire wine document is removed.
    """
    doc = await WinePrice.find_one({"_id": ObjectId(wine_price_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Wine price not found.")

    if entry_index < 0 or entry_index >= len(doc.prices):
        raise HTTPException(status_code=404, detail="Price entry not found.")

    entry = doc.prices[entry_index]
    if entry.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own price entries.")

    # Remove photo file if present
    if entry.photo_path:
        photo_file = _photo_storage_path() / entry.photo_path
        if photo_file.exists():
            photo_file.unlink()

    doc.prices.pop(entry_index)
    doc.updated_at = datetime.now(timezone.utc)

    if not doc.prices:
        await doc.delete()
    else:
        await doc.save()


@router.get(
    "/{wine_price_id}/history",
    response_model=list[WinePriceHistoryEntryOut],
)
async def get_wine_price_history(
    wine_price_id: str,
    current_user: RequireAuth,
    skip: int = 0,
    limit: int = 50,
) -> list[WinePriceHistoryEntryOut]:
    """Get archived price history for a wine."""
    doc = await WinePrice.find_one({"_id": ObjectId(wine_price_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Wine price not found.")

    if limit > 200:
        limit = 200

    history = (
        await WinePriceHistory.find({
            "wine_name": doc.wine_name,
            "vintage": doc.vintage,
            "wine_type": doc.wine_type,
        })
        .sort([("archived_at", -1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    return [
        WinePriceHistoryEntryOut(
            id=str(h.id),
            wine_name=h.wine_name,
            vintage=h.vintage,
            wine_type=h.wine_type,
            timestamp=h.timestamp,
            source=h.source.value,
            price=h.price,
            currency=h.currency,
            location={
                "shop_name": h.location.shop_name,
                "town_city": h.location.town_city,
                "state_county": h.location.state_county,
                "country": h.location.country,
            },
            notes=h.notes,
            archived_at=h.archived_at,
        )
        for h in history
    ]


@router.get("/photos/{filename}")
async def get_price_photo(
    filename: str,
    current_user: RequireAuth,
) -> FileResponse:
    """Serve a price capture photo.

    Only serves photos belonging to price entries owned by the current user.
    """
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    # Find any wine_prices document containing this photo for this user
    doc = await WinePrice.find_one({
        "prices": {
            "$elemMatch": {
                "photo_path": filename,
                "owner_id": current_user.id,
            }
        }
    })
    if not doc:
        raise HTTPException(status_code=404, detail="Photo not found.")

    photo_file = _photo_storage_path() / filename
    if not photo_file.exists():
        raise HTTPException(status_code=404, detail="Photo file not found.")

    return FileResponse(photo_file)
