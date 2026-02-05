"""Pydantic schemas for Transaction model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from winebox.models.transaction import TransactionType


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


class TransactionResponse(BaseModel):
    """Schema for transaction response."""

    id: str
    wine_id: str
    transaction_type: TransactionType
    quantity: int
    notes: str | None
    transaction_date: datetime
    created_at: datetime
    wine: WineBasicInfo | None = None

    model_config = ConfigDict(from_attributes=True)
