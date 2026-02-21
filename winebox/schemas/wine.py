"""Pydantic schemas for Wine model."""

from datetime import datetime
from typing import Any

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator

from winebox.schemas.transaction import TransactionResponse


class WineBase(BaseModel):
    """Base wine schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255)
    winery: str | None = Field(None, max_length=255)
    vintage: int | None = Field(None, ge=1900, le=2100)
    grape_variety: str | None = Field(None, max_length=255)
    region: str | None = Field(None, max_length=255)
    sub_region: str | None = Field(None, max_length=255)
    appellation: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=255)
    alcohol_percentage: float | None = Field(None, ge=0, le=100)

    # New taxonomy fields (v2)
    wine_type_id: str | None = Field(None, description="Wine type (red, white, etc.)")
    wine_subtype: str | None = Field(None, max_length=50, description="Subtype (e.g., full_bodied, champagne)")
    classification: str | None = Field(None, max_length=255, description="e.g., Grand Cru, DOCG, Reserve")
    price_tier: str | None = Field(None, description="Price tier: budget, value, mid_range, premium, luxury, ultra_premium")
    drink_window_start: int | None = Field(None, ge=1900, le=2200, description="Start year of drink window")
    drink_window_end: int | None = Field(None, ge=1900, le=2200, description="End year of drink window")
    producer_type: str | None = Field(None, description="Producer type: estate, negociant, cooperative")


class WineCreate(WineBase):
    """Schema for creating a wine (via form, not direct JSON)."""

    pass


class WineUpdate(BaseModel):
    """Schema for updating wine metadata."""

    name: str | None = Field(None, min_length=1, max_length=255)
    winery: str | None = Field(None, max_length=255)
    vintage: int | None = Field(None, ge=1900, le=2100)
    grape_variety: str | None = Field(None, max_length=255)
    region: str | None = Field(None, max_length=255)
    sub_region: str | None = Field(None, max_length=255)
    appellation: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=255)
    alcohol_percentage: float | None = Field(None, ge=0, le=100)

    # New taxonomy fields (v2)
    wine_type_id: str | None = Field(None, description="Wine type (red, white, etc.)")
    wine_subtype: str | None = Field(None, max_length=50)
    classification: str | None = Field(None, max_length=255, description="e.g., Grand Cru, DOCG, Reserve")
    price_tier: str | None = Field(None)
    drink_window_start: int | None = Field(None, ge=1900, le=2200)
    drink_window_end: int | None = Field(None, ge=1900, le=2200)
    producer_type: str | None = Field(None)


class InventoryInfo(BaseModel):
    """Schema for inventory information."""

    quantity: int = Field(..., ge=0)
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WineWithInventory(WineBase):
    """Wine schema with current inventory."""

    id: str
    front_label_text: str
    back_label_text: str | None
    front_label_image_path: str
    back_label_image_path: str | None
    created_at: datetime
    updated_at: datetime
    inventory: InventoryInfo | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def convert_objectid_to_str(cls, v: Any) -> str:
        """Convert ObjectId to string."""
        if isinstance(v, PydanticObjectId):
            return str(v)
        return v

    @property
    def current_quantity(self) -> int:
        """Get current quantity in stock."""
        return self.inventory.quantity if self.inventory else 0

    @property
    def in_stock(self) -> bool:
        """Check if wine is in stock."""
        return self.current_quantity > 0


class WineResponse(WineWithInventory):
    """Full wine response with transaction history."""

    transactions: list[TransactionResponse] = []

    model_config = ConfigDict(from_attributes=True)
