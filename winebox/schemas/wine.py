"""Pydantic schemas for Wine model."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from winebox.schemas.transaction import TransactionResponse


class WineBase(BaseModel):
    """Base wine schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255)
    winery: str | None = Field(None, max_length=255)
    vintage: int | None = Field(None, ge=1900, le=2100)
    grape_variety: str | None = Field(None, max_length=255)
    region: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=255)
    alcohol_percentage: float | None = Field(None, ge=0, le=100)


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
    country: str | None = Field(None, max_length=255)
    alcohol_percentage: float | None = Field(None, ge=0, le=100)


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
