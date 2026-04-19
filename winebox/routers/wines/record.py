"""Record-a-wine endpoint.

Adds bottles to the cellar: saves label images, optionally runs a scan,
enriches against X-Wines, persists the Wine document plus cellar items
and an ADDED transaction for the history log.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import File, Form, HTTPException, UploadFile, status

from winebox.models import InventoryInfo, Wine
from winebox.schemas.wine import WineWithInventory
from winebox.services.analytics import posthog_service
from winebox.services.auth import RequireAuth
from winebox.services.scan_service import scan_wine_labels
from winebox.services.xwines_enrichment import enrich_parsed_with_xwines

from ._common import (
    MAX_FIELD_LENGTH,
    MAX_NAME_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_OCR_TEXT_LENGTH,
    image_storage,
    ocr_service,
    vision_service,
    wine_parser,
)

logger = logging.getLogger(__name__)


async def record_wine(
    current_user: RequireAuth,
    front_label: Annotated[UploadFile, File(description="Front label image")],
    quantity: Annotated[int, Form(ge=1, le=10000, description="Number of bottles")] = 1,
    case_size: Annotated[int | None, Form(ge=1, le=100, description="Bottles per case (if case-based)")] = None,
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
    wine_type: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH)] = None,
    provenance: Annotated[str | None, Form(max_length=MAX_FIELD_LENGTH, description="Where the wine was purchased")] = None,
    purchase_price: Annotated[float | None, Form(ge=0, description="Price paid per case")] = None,
    notes: Annotated[str | None, Form(max_length=MAX_NOTES_LENGTH, description="Record notes")] = None,
    front_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned front label text")] = None,
    back_label_text: Annotated[str | None, Form(max_length=MAX_OCR_TEXT_LENGTH, description="Pre-scanned back label text")] = None,
    custom_fields: Annotated[str | None, Form(max_length=5000, description="Custom fields as JSON dict")] = None,
) -> WineWithInventory:
    """Record a wine in the cellar.

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

        await front_label.seek(0)
        front_bytes = await front_label.read()
        back_bytes: bytes | None = None
        back_fname: str | None = None
        if back_label and back_label.filename:
            await back_label.seek(0)
            back_bytes = await back_label.read()
            back_fname = back_label.filename

        scanned = await scan_wine_labels(
            front_data=front_bytes,
            back_data=back_bytes,
            front_filename=front_label.filename,
            back_filename=back_fname,
            vision_service=vision_service,
            ocr_service=ocr_service,
            wine_parser=wine_parser,
        )
        front_text = scanned.front_text
        back_text = scanned.back_text

        # Fill any caller-omitted field with whatever the scan recovered.
        name = name or scanned.name
        winery = winery or scanned.winery
        vintage = vintage or scanned.vintage
        grape_variety = grape_variety or scanned.grape_variety
        region = region or scanned.region
        sub_region = sub_region or scanned.sub_region
        appellation = appellation or scanned.appellation
        country = country or scanned.country
        classification = classification or scanned.classification
        alcohol_percentage = alcohol_percentage or scanned.alcohol_percentage

    # Enrich with X-Wines reference data (fills empty fields only)
    enrichment_input = {
        "name": name,
        "winery": winery,
        "grape_variety": grape_variety,
        "region": region,
        "country": country,
        "alcohol_percentage": alcohol_percentage,
    }
    enrichment_input = await enrich_parsed_with_xwines(enrichment_input)
    enriched_fields = enrichment_input.pop("enriched_fields", None)
    xwines_id = enrichment_input.pop("xwines_id", None)
    # Apply enriched values back
    winery = enrichment_input.get("winery") or winery
    grape_variety = enrichment_input.get("grape_variety") or grape_variety
    region = enrichment_input.get("region") or region
    country = enrichment_input.get("country") or country
    alcohol_percentage = enrichment_input.get("alcohol_percentage") or alcohol_percentage

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
        wine_type=wine_type,
        front_label_text=front_text,
        back_label_text=back_text,
        front_label_image_path=front_image_path,
        back_label_image_path=back_image_path,
        enriched_fields=enriched_fields or None,
        xwines_id=xwines_id,
        custom_fields=parsed_custom_fields,
        custom_fields_text=custom_fields_text,
        inventory=InventoryInfo(quantity=quantity, case_size=case_size, updated_at=datetime.now(timezone.utc)),
    )
    await wine.insert()

    # Create bottle records (event-sourced tracking). After Phase 4 of
    # the cases-first-class plan, the CellarEvent rows produced here are
    # the sole audit trail — the legacy Transaction collection is no
    # longer written. The transactions API and CSV exports read from
    # cellar_events via the compatibility view.
    from winebox.services.bottle_service import create_bottles_for_wine
    await create_bottles_for_wine(
        owner_id=current_user.id,
        wine=wine,
        quantity=quantity,
        case_size=case_size,
        provenance=provenance,
        purchase_price=purchase_price,
        notes=notes,
    )

    # Track record event
    posthog_service.capture(
        distinct_id=str(current_user.id),
        event="wine_added",
        properties={
            "quantity": quantity,
            "scan_method": "claude_vision" if vision_service.is_available() else "tesseract",
            "country": country,
            "wine_id": str(wine.id),
        },
    )

    return WineWithInventory.model_validate(wine)
