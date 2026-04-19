"""Pydantic schemas for data export functionality."""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    """Supported export formats."""

    CSV = "csv"
    XLSX = "xlsx"
    YAML = "yaml"
    JSON = "json"


class WineFlatExport(BaseModel):
    """Flat wine schema for CSV/Excel export.

    Phase 5 — when the caller opts into `cases_as_rows` (the default),
    a wine with mixed inventory spills into multiple rows: one per
    case plus one for the loose remainder. The new columns
    (`item_type`, `case_size`, `bottles_in_case_remaining`,
    `provenance`, `purchase_price`, `purchase_date`) carry the
    case-level context that was previously lost.
    """

    id: str
    name: str
    winery: str | None = None
    vintage: int | None = None
    grape_variety: str | None = None
    region: str | None = None
    country: str | None = None
    alcohol_percentage: float | None = None
    wine_type: str | None = None
    price_tier: str | None = None
    quantity: int = 0
    inventory_updated_at: datetime | None = None
    grape_blend_summary: str | None = None
    scores_summary: str | None = None
    average_score: float | None = None
    custom_fields: str | None = None
    custom_fields_dict: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime

    # Phase 5 — case-level columns. Present on case rows, None on the
    # aggregate / loose rows. Readers that ignore them see today's shape.
    item_type: str | None = None
    case_size: int | None = None
    bottles_in_case_remaining: int | None = None
    provenance: str | None = None
    purchase_price: float | None = None
    purchase_date: datetime | None = None

    @staticmethod
    def from_wine(wine: Any, include_blends: bool = True, include_scores: bool = True) -> "WineFlatExport":
        """Create a flat export schema from a Wine model instance.

        Args:
            wine: Wine model instance
            include_blends: Whether to include grape blend summary
            include_scores: Whether to include scores summary

        Returns:
            WineFlatExport instance
        """
        # Build grape blend summary
        grape_blend_summary = None
        if include_blends and wine.grape_blends:
            blend_parts = []
            for entry in wine.grape_blends:
                if entry.percentage is not None:
                    blend_parts.append(f"{entry.grape_name} ({entry.percentage:.0f}%)")
                else:
                    blend_parts.append(entry.grape_name)
            grape_blend_summary = ", ".join(blend_parts) if blend_parts else None

        # Build scores summary and average
        scores_summary = None
        average_score = None
        if include_scores and wine.scores:
            score_parts = []
            normalized_scores = []
            for entry in wine.scores:
                score_parts.append(f"{entry.source}: {entry.score}")
                normalized_scores.append(entry.normalized_score)
            scores_summary = ", ".join(score_parts) if score_parts else None
            if normalized_scores:
                average_score = sum(normalized_scores) / len(normalized_scores)

        # Build custom fields JSON string
        custom_fields_str = None
        if hasattr(wine, "custom_fields") and wine.custom_fields:
            custom_fields_str = json.dumps(wine.custom_fields)

        # Keep dict form for CSV/XLSX expansion
        custom_fields_raw = None
        if hasattr(wine, "custom_fields") and wine.custom_fields:
            custom_fields_raw = wine.custom_fields

        return WineFlatExport(
            id=str(wine.id),
            name=wine.name,
            winery=wine.winery,
            vintage=wine.vintage,
            grape_variety=wine.grape_variety,
            region=wine.region,
            country=wine.country,
            alcohol_percentage=wine.alcohol_percentage,
            wine_type=wine.wine_type,
            price_tier=wine.price_tier,
            quantity=wine.inventory.quantity if wine.inventory else 0,
            inventory_updated_at=wine.inventory.updated_at if wine.inventory else None,
            grape_blend_summary=grape_blend_summary,
            scores_summary=scores_summary,
            average_score=average_score,
            custom_fields=custom_fields_str,
            custom_fields_dict=custom_fields_raw,
            created_at=wine.created_at,
            updated_at=wine.updated_at,
        )

    @staticmethod
    def rows_with_cases(
        wine: Any, include_blends: bool = True, include_scores: bool = True,
    ) -> list["WineFlatExport"]:
        """Emit one row per case plus one row for the loose remainder.

        Phase 5 default for CSV/XLSX. A wine with a case of 12 (Berry
        Bros) + 3 loose becomes two rows, both carrying the full wine
        descriptor but different `item_type` / `case_size` /
        `bottles_in_case_remaining` / `provenance` / `purchase_price` /
        `purchase_date`. The aggregate `quantity` column on each row is
        that row's own `bottles_in_case_remaining` (case) or loose count
        (loose); summing the `quantity` column across a wine's rows
        reconstructs the total.

        Wines with no breakdown (met wines, or pre-Phase-1 rows where
        the inventory service didn't run) yield a single row matching
        today's shape.
        """
        base = WineFlatExport.from_wine(wine, include_blends, include_scores)

        inv = getattr(wine, "inventory", None)
        cases = getattr(inv, "cases", None) or []
        loose = getattr(inv, "loose_bottles", 0) if inv is not None else 0

        if not cases and loose == 0:
            # No breakdown information — emit today's single-row shape.
            return [base]

        rows: list[WineFlatExport] = []
        for case in cases:
            row = base.model_copy(update={
                "item_type": "case",
                "quantity": case.bottles_remaining,
                "case_size": case.case_size,
                "bottles_in_case_remaining": case.bottles_remaining,
                "provenance": case.provenance,
                "purchase_price": case.purchase_price,
                "purchase_date": case.purchase_date,
            })
            rows.append(row)
        if loose > 0:
            rows.append(base.model_copy(update={
                "item_type": "bottle",
                "quantity": loose,
                "case_size": None,
                "bottles_in_case_remaining": None,
                "provenance": None,
                "purchase_price": None,
                "purchase_date": None,
            }))
        return rows or [base]


class TransactionFlatExport(BaseModel):
    """Flat transaction schema for CSV/Excel export.

    Phase 5 — gains `item_type` + `case_size_at_event` +
    `provenance_at_event` so a CSV row reflects which physical case
    (if any) a removal came from. These fields are populated from the
    TransactionResponse the new compatibility view emits; rows
    sourced from pre-Phase-4 Transactions leave them None.
    """

    id: str
    wine_id: str
    wine_name: str | None = None
    wine_vintage: int | None = None
    wine_winery: str | None = None
    transaction_type: str
    quantity: int
    notes: str | None = None
    transaction_date: datetime
    created_at: datetime

    # Phase 5 — case context snapshots carried through from CellarEvent.
    item_type: str | None = None
    case_size_at_event: int | None = None
    provenance_at_event: str | None = None

    @staticmethod
    def from_transaction(
        transaction: Any,
        wine: Any | None = None,
        include_wine_details: bool = True,
    ) -> "TransactionFlatExport":
        """Create a flat export schema from a Transaction model instance.

        Args:
            transaction: Transaction model instance
            wine: Optional Wine model instance for wine details
            include_wine_details: Whether to include wine details

        Returns:
            TransactionFlatExport instance
        """
        wine_name = None
        wine_vintage = None
        wine_winery = None

        if include_wine_details and wine:
            wine_name = wine.name
            wine_vintage = wine.vintage
            wine_winery = wine.winery

        return TransactionFlatExport(
            id=str(transaction.id),
            wine_id=str(transaction.wine_id),
            wine_name=wine_name,
            wine_vintage=wine_vintage,
            wine_winery=wine_winery,
            transaction_type=transaction.transaction_type.value,
            quantity=transaction.quantity,
            notes=transaction.notes,
            transaction_date=transaction.transaction_date,
            created_at=transaction.created_at,
            # Pull the case context when the source is a TransactionResponse
            # (post-Phase-4 compatibility view) or a legacy Transaction row
            # without these fields (they fall back to None).
            item_type=getattr(transaction, "item_type", None),
            case_size_at_event=getattr(transaction, "case_size_at_event", None),
            provenance_at_event=getattr(transaction, "provenance_at_event", None),
        )


class ExportMetadata(BaseModel):
    """Metadata included in hierarchical exports (JSON, YAML)."""

    exported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_count: int
    format: str
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class WinesExportResponse(BaseModel):
    """Response schema for wine exports in hierarchical formats."""

    wines: list[dict[str, Any]]
    export_info: ExportMetadata


class TransactionsExportResponse(BaseModel):
    """Response schema for transaction exports in hierarchical formats."""

    transactions: list[dict[str, Any]]
    export_info: ExportMetadata
