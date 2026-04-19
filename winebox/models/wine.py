"""Wine document model for MongoDB with embedded subdocuments."""

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from winebox.db import MongoDocument, PyObjectId


class WineCollection(str, enum.Enum):
    """Which collection a wine belongs to: cellar or met (encountered)."""

    CELLAR = "cellar"
    MET = "met"


class InventoryInfo(BaseModel):
    """Embedded subdocument for inventory information."""

    quantity: int = Field(default=0, ge=0)
    case_size: Optional[int] = Field(default=None, ge=1)  # Bottles per case (None = single bottles)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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


class Wine(MongoDocument):
    """Wine document model representing a wine in the cellar or a wine the user has met."""

    # Owner reference for data isolation
    owner_id: PyObjectId

    # Collection: "cellar" (owned bottles) or "met" (wines encountered)
    collection: WineCollection = WineCollection.CELLAR
    added_to_cellar: bool = False  # Only meaningful when collection="met"
    cellar_wine_id: Optional[PyObjectId] = None  # Links met wine → cellar wine

    # Basic wine information
    name: str
    winery: Optional[str] = None
    vintage: Optional[int] = None
    grape_variety: Optional[str] = None  # Primary grape (backward compat)
    region: Optional[str] = None
    sub_region: Optional[str] = None
    appellation: Optional[str] = None
    country: Optional[str] = None
    alcohol_percentage: Optional[float] = None

    # Label text and images
    front_label_text: str = ""
    back_label_text: Optional[str] = None
    front_label_image_path: Optional[str] = None
    back_label_image_path: Optional[str] = None

    # Taxonomy fields
    wine_type: Optional[str] = None  # Reference to WineType
    wine_subtype: Optional[str] = None  # e.g., 'full_bodied', 'champagne'
    classification: Optional[str] = None  # e.g., Grand Cru, DOCG, Reserve
    price_tier: Optional[str] = None  # 'budget', 'value', etc.
    estimated_price_low: Optional[float] = None  # From X-Wines price data (USD)
    estimated_price_high: Optional[float] = None  # From X-Wines price data (USD)
    drink_window_start: Optional[int] = None  # Year
    drink_window_end: Optional[int] = None  # Year
    producer_type: Optional[str] = None  # 'estate', 'negociant', 'cooperative'

    # Embedded subdocuments (previously separate tables)
    inventory: InventoryInfo = Field(default_factory=InventoryInfo)
    grape_blends: list[GrapeBlendEntry] = Field(default_factory=list)
    scores: list[ScoreEntry] = Field(default_factory=list)

    # X-Wines enrichment tracking
    enriched_fields: Optional[list[str]] = None  # Fields filled by X-Wines enrichment
    xwines_id: Optional[int] = None  # ID from X-Wines dataset for reference

    # Import batch tracking
    import_batch_id: Optional[PyObjectId] = None

    # Custom fields from spreadsheet import or manual entry
    custom_fields: Optional[dict[str, str]] = None
    custom_fields_text: Optional[str] = None  # Denormalized for text search

    # Purchase info
    purchase_date: Optional[datetime] = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "wines"

    def __repr__(self) -> str:
        return f"<Wine(id={self.id}, name={self.name}, vintage={self.vintage})>"
