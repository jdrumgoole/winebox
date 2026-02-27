"""Export endpoints for downloading wine cellar data."""

from datetime import datetime, timezone
from typing import Any

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from winebox.models import Transaction, TransactionType, Wine
from winebox.schemas.export import (
    ExportFormat,
    TransactionFlatExport,
    WineFlatExport,
)
from winebox.services import export_service
from winebox.services.auth import RequireAuth

router = APIRouter()


def _generate_filename(export_type: str, export_format: ExportFormat) -> str:
    """Generate a standardized filename for exports."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = export_format.value
    return f"winebox_{export_type}_{timestamp}.{extension}"


@router.get("/wines")
async def export_wines(
    current_user: RequireAuth,
    format: ExportFormat = Query(default=ExportFormat.JSON, description="Export format"),
    in_stock: bool | None = Query(default=None, description="Filter: only wines with quantity > 0"),
    country: str | None = Query(default=None, description="Filter by country"),
    include_blends: bool = Query(default=True, description="Include grape blend details"),
    include_scores: bool = Query(default=True, description="Include wine scores"),
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

    # Fetch wines (filtered by owner)
    wines = await Wine.find(conditions).sort(Wine.name).to_list()

    # Track applied filters
    filters_applied: dict[str, Any] = {}
    if in_stock is not None:
        filters_applied["in_stock"] = in_stock
    if country:
        filters_applied["country"] = country

    # Generate response based on format
    if format in (ExportFormat.CSV, ExportFormat.XLSX):
        # Flat format for CSV/Excel
        flat_wines = [
            WineFlatExport.from_wine(wine, include_blends=include_blends, include_scores=include_scores)
            for wine in wines
        ]

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
        # Hierarchical format for JSON/YAML
        wine_dicts = []
        for wine in wines:
            wine_dict = wine.model_dump(mode="json")
            wine_dict["id"] = str(wine.id)

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
async def export_transactions(
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
    # Build query conditions - always filter by owner
    conditions: dict[str, Any] = {"owner_id": current_user.id}

    if transaction_type:
        conditions["transaction_type"] = transaction_type

    if wine_id:
        try:
            conditions["wine_id"] = PydanticObjectId(wine_id)
        except (InvalidId, ValidationError):
            pass  # Ignore invalid wine_id

    if from_date:
        conditions.setdefault("transaction_date", {})
        conditions["transaction_date"]["$gte"] = from_date

    if to_date:
        conditions.setdefault("transaction_date", {})
        conditions["transaction_date"]["$lte"] = to_date

    # Fetch transactions
    transactions = await Transaction.find(conditions).sort(-Transaction.transaction_date).to_list()

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

    # Batch fetch wine details if needed
    wines_by_id: dict[str, Any] = {}
    if include_wine_details and transactions:
        wine_ids = list({t.wine_id for t in transactions})
        wines = await Wine.find({"_id": {"$in": wine_ids}}).to_list()
        wines_by_id = {wine.id: wine for wine in wines}

    # Generate response based on format
    if format in (ExportFormat.CSV, ExportFormat.XLSX):
        # Flat format for CSV/Excel
        flat_transactions = [
            TransactionFlatExport.from_transaction(
                txn,
                wine=wines_by_id.get(txn.wine_id),
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

            # Add wine details if requested
            if include_wine_details:
                wine = wines_by_id.get(txn.wine_id)
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
