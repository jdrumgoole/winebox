"""Wine document model for MongoDB with embedded subdocuments."""

from datetime import datetime
from typing import Optional

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class InventoryInfo(BaseModel):
    """Embedded subdocument for inventory information."""

    quantity: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GrapeBlendEntry(BaseModel):
    """Embedded subdocument for grape blend information."""

    grape_variety_id: str
    grape_name: str  # Denormalized for display
    percentage: Optional[float] = None  # 0-100 or None if unknown
    color: Optional[str] = None  # 'red' or 'white'


class ScoreEntry(BaseModel):
    """Embedded subdocument for wine scores/ratings."""

    id: str  # Unique ID for this score entry
    source: str  # 'wine_advocate', 'wine_spectator', etc.
    score: int  # Raw score value
    score_type: str  # '100_point', '20_point', '5_star'
    review_date: Optional[datetime] = None
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def normalized_score(self) -> float:
        """Return score normalized to 0-100 scale for comparison."""
        if self.score_type == "100_point":
            return float(self.score)
        elif self.score_type == "20_point":
            return self.score * 5.0
        elif self.score_type == "5_star":
            return self.score * 20.0
        return float(self.score)


class Wine(Document):
    """Wine document model representing a wine in the cellar."""

    # Basic wine information
    name: Indexed(str)
    winery: Optional[Indexed(str)] = None
    vintage: Optional[Indexed(int)] = None
    grape_variety: Optional[Indexed(str)] = None  # Primary grape (backward compat)
    region: Optional[str] = None
    country: Optional[Indexed(str)] = None
    alcohol_percentage: Optional[float] = None

    # Label text and images
    front_label_text: str = ""
    back_label_text: Optional[str] = None
    front_label_image_path: str
    back_label_image_path: Optional[str] = None

    # Taxonomy fields
    wine_type_id: Optional[Indexed(str)] = None  # Reference to WineType
    wine_subtype: Optional[str] = None  # e.g., 'full_bodied', 'champagne'
    appellation_id: Optional[str] = None  # Reference to Region
    classification_id: Optional[str] = None  # Reference to Classification
    price_tier: Optional[str] = None  # 'budget', 'value', etc.
    drink_window_start: Optional[int] = None  # Year
    drink_window_end: Optional[int] = None  # Year
    producer_type: Optional[str] = None  # 'estate', 'negociant', 'cooperative'

    # Embedded subdocuments (previously separate tables)
    inventory: InventoryInfo = Field(default_factory=InventoryInfo)
    grape_blends: list[GrapeBlendEntry] = Field(default_factory=list)
    scores: list[ScoreEntry] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "wines"
        indexes = [
            "name",
            "winery",
            "vintage",
            "country",
            "wine_type_id",
            [
                ("name", "text"),
                ("winery", "text"),
                ("region", "text"),
                ("country", "text"),
                ("front_label_text", "text"),
            ],
        ]

    def __repr__(self) -> str:
        return f"<Wine(id={self.id}, name={self.name}, vintage={self.vintage})>"
