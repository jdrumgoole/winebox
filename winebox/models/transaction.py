"""Transaction document model for tracking wine check-ins and check-outs."""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class TransactionType(str, enum.Enum):
    """Type of transaction."""

    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"


class Transaction(MongoDocument):
    """Transaction document model for tracking wine movements."""

    owner_id: PyObjectId  # Denormalized for efficient user queries
    wine_id: PyObjectId
    transaction_type: TransactionType
    quantity: int = Field(..., ge=1)
    notes: Optional[str] = None
    transaction_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "transactions"

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, type={self.transaction_type}, quantity={self.quantity})>"
