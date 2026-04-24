"""Export endpoints for downloading wine cellar data."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from starlette.background import BackgroundTask

from winebox.models import TransactionType, Wine
from winebox.schemas.export import (
    ExportFormat,
    TransactionFlatExport,
    WineFlatExport,
)
from winebox.schemas.wine import WineWithInventory
from winebox.services import export_service
from winebox.services.auth import RequireAuth
from winebox.services.cellar_event_view import build_event_query, event_to_transaction_response
from winebox.services.cellar_inventory import attach_breakdowns
from winebox.services.export_service.static_site import generate_static_site_zip
from winebox.services.rate_limit import MAX_USER_RESULTSET, make_limiter
from winebox.services.search_service import WineSearchFilters, search_wines

from winebox.models.cellar_event import CellarEvent

router = APIRouter()

limiter = make_limiter()


def _generate_filename(export_type: str, export_format: ExportFormat) -> str:
    """Generate a standardized filename for exports."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = export_format.value
    return f"winebox_{export_type}_{timestamp}.{extension}"


@router.get("/wines")
@limiter.limit("10/minute;30/hour")
async def export_wines(
    request: Request,
    current_user: RequireAuth,
    format: ExportFormat = Query(default=ExportFormat.JSON, description="Export format"),
    in_stock: bool | None = Query(default=None, description="Filter: only wines with quantity > 0"),
    country: str | None = Query(default=None, description="Filter by country"),
    include_blends: bool = Query(default=True, description="Include grape blend details"),
    include_scores: bool = Query(default=True, description="Include wine scores"),
    cases_as_rows: bool = Query(
        default=True,
        description=(
            "Phase 5 — when True (default), a wine with cases is split "
            "into one CSV/XLSX row per case plus a loose-remainder row, "
            "each carrying case_size + provenance + purchase_price. "
            "Old readers that rely on one-row-per-wine can pass False."
        ),
    ),
) -> Response:
    """Export wine inventory data.

    Returns wine data in the specified format (CSV, XLSX, YAML, or JSON).
    """
    # Build query conditions - always filter by owner
    conditions: dict[str, Any] = {"owner_id": current_user.id}

    if in_stock is not None:
        if in_stock:
            conditions["inventory.quantity"] = {"$gt": 0}
        else:
            conditions["inventory.quantity"] = {"$lte": 0}

    if country:
        conditions["country"] = country

    # Fetch wines (filtered by owner). Bounded — exports above MAX_USER_RESULTSET
    # are well outside any realistic personal cellar size and would risk OOM.
    wines = await Wine.find(conditions).sort([("name", 1)]).to_list(length=MAX_USER_RESULTSET)

    # Phase 5 — attach the case/loose breakdown so the export carries
    # per-case provenance and counts. Hierarchical formats emit the
    # `inventory.cases` array; flat formats either spill into per-case
    # rows (default) or collapse to one row per wine (cases_as_rows=False).
    wine_views: list = []
    for wine in wines:
        from winebox.schemas.wine import WineWithInventory
        view = WineWithInventory.model_validate(wine)
        wine_views.append(view)
    await attach_breakdowns(wine_views, wines, current_user.id)

    # Track applied filters
    filters_applied: dict[str, Any] = {}
    if in_stock is not None:
        filters_applied["in_stock"] = in_stock
    if country:
        filters_applied["country"] = country

    # Generate response based on format
    if format in (ExportFormat.CSV, ExportFormat.XLSX):
        # Flat format for CSV/Excel
        flat_wines: list[WineFlatExport] = []
        for wine, view in zip(wines, wine_views):
            # Shim the view's inventory (with cases/loose_bottles) onto the
            # Wine instance so `rows_with_cases` can read it off a single
            # object without changing the underlying shape the row builder
            # has always expected.
            original_inventory = wine.inventory
            wine.inventory = view.inventory
            try:
                if cases_as_rows:
                    flat_wines.extend(WineFlatExport.rows_with_cases(
                        wine, include_blends=include_blends, include_scores=include_scores,
                    ))
                else:
                    flat_wines.append(WineFlatExport.from_wine(
                        wine, include_blends=include_blends, include_scores=include_scores,
                    ))
            finally:
                wine.inventory = original_inventory

        if format == ExportFormat.CSV:
            content = export_service.export_wines_to_csv(flat_wines)
        else:
            content = export_service.export_wines_to_xlsx(flat_wines)

        return Response(
            content=content,
            media_type=export_service.get_content_type(format),
            headers={
                "Content-Disposition": f"attachment; filename={_generate_filename('wines', format)}"
            },
        )

    else:
        # Hierarchical format for JSON/YAML — inject the case breakdown
        # onto the wine's inventory dict so the export is a complete
        # round-trippable description of what's in the cellar.
        wine_dicts = []
        for wine, view in zip(wines, wine_views):
            wine_dict = wine.model_dump(mode="json")
            wine_dict["id"] = str(wine.id)

            # Strip internal owner_id from export payloads — exports are for the
            # user, not for inter-user data exchange. Leaking the ObjectId could
            # help an attacker correlate or enumerate users elsewhere.
            wine_dict.pop("owner_id", None)

            # Phase 5: replace the legacy two-field `inventory` with the
            # full breakdown — cases list + loose count + aggregate.
            wine_dict["inventory"] = view.inventory.model_dump(mode="json")

            # Optionally exclude blends/scores
            if not include_blends:
                wine_dict.pop("grape_blends", None)
            if not include_scores:
                wine_dict.pop("scores", None)

            wine_dicts.append(wine_dict)

        if format == ExportFormat.YAML:
            content = export_service.export_wines_to_yaml(wine_dicts, filters_applied)
            return Response(
                content=content,
                media_type=export_service.get_content_type(format),
                headers={
                    "Content-Disposition": f"attachment; filename={_generate_filename('wines', format)}"
                },
            )
        else:
            # JSON
            export_data = export_service.export_wines_to_json(wine_dicts, filters_applied)
            return JSONResponse(
                content=export_data,
                headers={
                    "Content-Disposition": f"attachment; filename={_generate_filename('wines', format)}"
                },
            )


@router.get("/transactions")
@limiter.limit("10/minute;30/hour")
async def export_transactions(
    request: Request,
    current_user: RequireAuth,
    format: ExportFormat = Query(default=ExportFormat.JSON, description="Export format"),
    transaction_type: TransactionType | None = Query(default=None, description="Filter by transaction type"),
    wine_id: str | None = Query(default=None, description="Filter by specific wine"),
    from_date: datetime | None = Query(default=None, description="Filter from date"),
    to_date: datetime | None = Query(default=None, description="Filter to date"),
    include_wine_details: bool = Query(default=True, description="Include wine name/vintage"),
) -> Response:
    """Export transaction history.

    Returns transaction data in the specified format (CSV, XLSX, YAML, or JSON).
    """
    # Build Mongo filter on `cellar_events` with the same semantics as the
    # old transactions-based export (owner scoped, optional type / wine /
    # date range).
    wine_oid: ObjectId | None = None
    if wine_id:
        try:
            wine_oid = ObjectId(wine_id)
        except (InvalidId, ValidationError):
            wine_oid = None
    conditions = build_event_query(
        current_user.id,
        transaction_type=transaction_type,
        wine_id=wine_oid,
        date_from=from_date,
        date_to=to_date,
    )

    # Fetch events and project them onto the TransactionResponse shape so
    # the existing flat/hierarchical serialisers keep working unchanged.
    events = await CellarEvent.find(conditions).sort([("event_date", -1)]).to_list(
        length=MAX_USER_RESULTSET,
    )
    transactions = [event_to_transaction_response(e) for e in events]

    # Track applied filters
    filters_applied: dict[str, Any] = {}
    if transaction_type:
        filters_applied["transaction_type"] = transaction_type.value
    if wine_id:
        filters_applied["wine_id"] = wine_id
    if from_date:
        filters_applied["from_date"] = from_date.isoformat()
    if to_date:
        filters_applied["to_date"] = to_date.isoformat()

    # Batch fetch wine details if needed. `TransactionResponse.wine_id` is a
    # string here (post-Phase-4 the source is CellarEvent → view model),
    # so we cast back to ObjectId for the DB filter and key the cache by
    # string so lookups below work.
    wines_by_id: dict[str, Any] = {}
    if include_wine_details and transactions:
        wine_oids: list[ObjectId] = []
        for t in transactions:
            if not t.wine_id:
                continue
            try:
                wine_oids.append(ObjectId(t.wine_id))
            except (InvalidId, ValidationError):
                pass
        if wine_oids:
            wines = await Wine.find({"_id": {"$in": wine_oids}}).to_list(length=MAX_USER_RESULTSET)
            wines_by_id = {str(wine.id): wine for wine in wines}

    # Generate response based on format
    if format in (ExportFormat.CSV, ExportFormat.XLSX):
        # Flat format for CSV/Excel
        flat_transactions = [
            TransactionFlatExport.from_transaction(
                txn,
                wine=wines_by_id.get(str(txn.wine_id)),
                include_wine_details=include_wine_details,
            )
            for txn in transactions
        ]

        if format == ExportFormat.CSV:
            content = export_service.export_transactions_to_csv(flat_transactions)
        else:
            content = export_service.export_transactions_to_xlsx(flat_transactions)

        return Response(
            content=content,
            media_type=export_service.get_content_type(format),
            headers={
                "Content-Disposition": f"attachment; filename={_generate_filename('transactions', format)}"
            },
        )

    else:
        # Hierarchical format for JSON/YAML
        txn_dicts = []
        for txn in transactions:
            txn_dict = txn.model_dump(mode="json")
            txn_dict["id"] = str(txn.id)
            txn_dict["wine_id"] = str(txn.wine_id)
            txn_dict.pop("owner_id", None)

            # Add wine details if requested
            if include_wine_details:
                wine = wines_by_id.get(str(txn.wine_id))
                if wine:
                    txn_dict["wine"] = {
                        "id": str(wine.id),
                        "name": wine.name,
                        "vintage": wine.vintage,
                        "winery": wine.winery,
                    }
                else:
                    txn_dict["wine"] = None

            txn_dicts.append(txn_dict)

        if format == ExportFormat.YAML:
            content = export_service.export_transactions_to_yaml(txn_dicts, filters_applied)
            return Response(
                content=content,
                media_type=export_service.get_content_type(format),
                headers={
                    "Content-Disposition": f"attachment; filename={_generate_filename('transactions', format)}"
                },
            )
        else:
            # JSON
            export_data = export_service.export_transactions_to_json(txn_dicts, filters_applied)
            return JSONResponse(
                content=export_data,
                headers={
                    "Content-Disposition": f"attachment; filename={_generate_filename('transactions', format)}"
                },
            )


MAX_QUERY_LENGTH = 200


@router.get("/static-site")
@limiter.limit("3/minute;10/hour")
async def export_static_site(
    request: Request,
    current_user: RequireAuth,
    q: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    vintage: int | None = None,
    grape: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    winery: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    region: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    country: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    wine_type: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    price_tier: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    in_stock: bool | None = None,
    storage: str | None = None,
    provenance: Annotated[str | None, Query(max_length=MAX_QUERY_LENGTH)] = None,
    enriched: str | None = None,
) -> FileResponse:
    """Export cellar as a self-contained static website (ZIP download).

    Accepts the same filter parameters as the search endpoint.
    Returns a ZIP file containing an ``index.html`` that can be opened
    in any browser to browse the cellar offline.
    """
    from winebox.config import settings

    filters = WineSearchFilters(
        q=q, vintage=vintage, grape=grape, winery=winery,
        region=region, country=country, wine_type=wine_type,
        price_tier=price_tier, in_stock=in_stock, storage=storage,
        provenance=provenance, enriched=enriched,
    )

    wines = await search_wines(current_user.id, filters, skip=0, limit=MAX_USER_RESULTSET)
    results = [WineWithInventory.model_validate(w) for w in wines]
    await attach_breakdowns(results, wines, current_user.id)

    filters_applied = {
        k: v for k, v in {
            "search": q, "vintage": str(vintage) if vintage else None,
            "grape": grape, "winery": winery, "region": region,
            "country": country, "wine_type": wine_type,
            "price_tier": price_tier,
            "in_stock": "yes" if in_stock else None,
            "storage": storage, "provenance": provenance,
            "enriched": enriched,
        }.items() if v
    }

    zip_path = generate_static_site_zip(
        results,
        settings.image_storage_path,
        filters_applied=filters_applied,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"winebox-cellar-{timestamp}.zip"

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(os.unlink, zip_path),
    )
