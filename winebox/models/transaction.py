"""Transaction document model for tracking wine check-ins and check-outs."""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field, model_validator

from winebox.db import MongoDocument, PyObjectId


class TransactionType(str, enum.Enum):
    """Type of transaction."""

    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"


class RemovalReason(str, enum.Enum):
    """Reason for removing wine from the cellar."""

    DRINK = "DRINK"
    SELL = "SELL"
    GIFT = "GIFT"
    OTHER = "OTHER"


class Transaction(MongoDocument):
    """Transaction document model for tracking wine movements."""

    owner_id: PyObjectId  # Denormalized for efficient user queries
    wine_id: PyObjectId
    transaction_type: TransactionType
    quantity: int = Field(..., ge=1)
    notes: Optional[str] = None
    transaction_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Removal metadata (only for CHECK_OUT transactions)
    removal_reason: Optional[RemovalReason] = None
    tasting_notes: Optional[str] = None
    sale_price_usd: Optional[float] = Field(default=None, ge=0)
    gift_recipient: Optional[str] = None
    removal_notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_removal_fields(self) -> "Transaction":
        """Enforce cross-field validation for removal metadata."""
        if self.transaction_type == TransactionType.CHECK_IN:
            if self.removal_reason is not None:
                raise ValueError("removal_reason is only valid for CHECK_OUT transactions")
            if self.tasting_notes is not None:
                raise ValueError("tasting_notes is only valid for CHECK_OUT transactions")
            if self.sale_price_usd is not None:
                raise ValueError("sale_price_usd is only valid for CHECK_OUT transactions")
            if self.gift_recipient is not None:
                raise ValueError("gift_recipient is only valid for CHECK_OUT transactions")
            if self.removal_notes is not None:
                raise ValueError("removal_notes is only valid for CHECK_OUT transactions")

        if self.removal_reason == RemovalReason.SELL and self.sale_price_usd is None:
            raise ValueError("sale_price_usd is required when removal_reason is SELL")

        if self.removal_reason == RemovalReason.GIFT and not self.gift_recipient:
            raise ValueError("gift_recipient is required when removal_reason is GIFT")

        # Cross-field: fields only valid for their specific reason
        if self.sale_price_usd is not None and self.removal_reason != RemovalReason.SELL:
            raise ValueError("sale_price_usd is only valid when removal_reason is SELL")

        if self.gift_recipient is not None and self.removal_reason != RemovalReason.GIFT:
            raise ValueError("gift_recipient is only valid when removal_reason is GIFT")

        if self.tasting_notes is not None and self.removal_reason != RemovalReason.DRINK:
            raise ValueError("tasting_notes is only valid when removal_reason is DRINK")

        if self.removal_notes is not None and self.removal_reason != RemovalReason.OTHER:
            raise ValueError("removal_notes is only valid when removal_reason is OTHER")

        return self

    class Settings:
        name = "transactions"

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, type={self.transaction_type}, quantity={self.quantity})>"
