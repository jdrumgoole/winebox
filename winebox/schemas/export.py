"""Pydantic schemas for data export functionality."""

from datetime import datetime
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
    """Flat wine schema for CSV/Excel export."""

    id: str
    name: str
    winery: str | None = None
    vintage: int | None = None
    grape_variety: str | None = None
    region: str | None = None
    country: str | None = None
    alcohol_percentage: float | None = None
    wine_type_id: str | None = None
    price_tier: str | None = None
    quantity: int = 0
    inventory_updated_at: datetime | None = None
    grape_blend_summary: str | None = None
    scores_summary: str | None = None
    average_score: float | None = None
    created_at: datetime
    updated_at: datetime

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

        return WineFlatExport(
            id=str(wine.id),
            name=wine.name,
            winery=wine.winery,
            vintage=wine.vintage,
            grape_variety=wine.grape_variety,
            region=wine.region,
            country=wine.country,
            alcohol_percentage=wine.alcohol_percentage,
            wine_type_id=wine.wine_type_id,
            price_tier=wine.price_tier,
            quantity=wine.inventory.quantity if wine.inventory else 0,
            inventory_updated_at=wine.inventory.updated_at if wine.inventory else None,
            grape_blend_summary=grape_blend_summary,
            scores_summary=scores_summary,
            average_score=average_score,
            created_at=wine.created_at,
            updated_at=wine.updated_at,
        )


class TransactionFlatExport(BaseModel):
    """Flat transaction schema for CSV/Excel export."""

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
        )


class ExportMetadata(BaseModel):
    """Metadata included in hierarchical exports (JSON, YAML)."""

    exported_at: datetime = Field(default_factory=datetime.utcnow)
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
