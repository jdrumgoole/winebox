"""Wine type reference document model."""

from typing import Optional

from beanie import Document
from pydantic import Field


class WineType(Document):
    """Wine type document model representing wine categories (red, white, rosé, etc.)."""

    # Use string ID for simplicity ('red', 'white', etc.)
    type_id: str = Field(..., description="Unique type identifier")
    name: str = Field(..., description="Display name")
    description: Optional[str] = None

    class Settings:
        name = "wine_types"
        indexes = [
            "type_id",
        ]

    def __repr__(self) -> str:
        return f"<WineType(type_id={self.type_id}, name={self.name})>"
