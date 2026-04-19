"""Pydantic schemas for Transaction model."""

from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from winebox.models.transaction import RemovalReason, TransactionType


class TransactionCreate(BaseModel):
    """Schema for creating a transaction."""

    quantity: int = Field(..., ge=1)
    notes: str | None = None


class WineBasicInfo(BaseModel):
    """Basic wine info for transaction response."""

    id: str
    name: str
    vintage: int | None = None
    winery: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def convert_objectid_to_str(cls, v: Any) -> str:
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v


class TransactionResponse(BaseModel):
    """Schema for transaction response.

    Post-Phase-4d, these rows are synthesised from `CellarEvent` — the
    legacy `Transaction` collection is no longer written to. Three new
    optional fields carry the case context that CellarEvent has always
    known but Transaction never did:

    - `item_type`: "case" | "bottle" | "legacy" (pre-Phase-4 rows)
    - `case_size_at_event` / `provenance_at_event`: frozen snapshots so
      the activity feed can say "drank 2 from your Berry Bros case"
      even after the case itself has been fully consumed.

    Old clients that ignore these fields render identically to before.
    """

    id: str
    wine_id: str
    transaction_type: TransactionType
    quantity: int
    notes: str | None
    transaction_date: datetime
    created_at: datetime
    wine: WineBasicInfo | None = None
    removal_reason: RemovalReason | None = None
    tasting_notes: str | None = None
    sale_price_usd: float | None = None
    gift_recipient: str | None = None
    removal_notes: str | None = None

    # Phase 4f — case context (populated when the source event was a case
    # or a case-backfilled legacy row; None otherwise).
    item_type: str | None = None
    case_size_at_event: int | None = None
    provenance_at_event: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "wine_id", mode="before")
    @classmethod
    def convert_objectid_to_str(cls, v: Any) -> str:
        """Convert ObjectId to string."""
        if isinstance(v, ObjectId):
            return str(v)
        return v
