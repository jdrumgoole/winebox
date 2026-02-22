"""Transaction document model for tracking wine check-ins and check-outs."""

import enum
from datetime import datetime
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class TransactionType(str, enum.Enum):
    """Type of transaction."""

    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"


class Transaction(Document):
    """Transaction document model for tracking wine movements."""

    owner_id: Indexed(PydanticObjectId)  # Denormalized for efficient user queries
    wine_id: Indexed(PydanticObjectId)
    transaction_type: TransactionType
    quantity: int = Field(..., ge=1)
    notes: Optional[str] = None
    transaction_date: Indexed(datetime) = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "transactions"
        indexes = [
            "owner_id",
            "wine_id",
            "transaction_type",
            "transaction_date",
            [("owner_id", 1), ("transaction_date", -1)],  # Compound index for user transaction queries
        ]

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, type={self.transaction_type}, quantity={self.quantity})>"
