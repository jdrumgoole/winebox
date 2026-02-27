"""X-Wines dataset document models for wine autocomplete and reference data.

These models represent read-only reference data from the X-Wines dataset.
Source: https://github.com/rogerioxavier/X-Wines
"""

from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class XWinesWine(Document):
    """X-Wines wine reference data.

    External wine data from the X-Wines dataset for autocomplete and auto-fill.
    This is read-only reference data - user's own wines remain in the wines collection.
    """

    # Use the original X-Wines integer ID
    xwines_id: Indexed(int, unique=True)
    name: Indexed(str)
    wine_type: Indexed(str)
    elaborate: Optional[str] = None
    grapes: Optional[str] = None
    harmonize: Optional[str] = None
    abv: Optional[float] = None
    body: Optional[str] = None
    acidity: Optional[str] = None
    country_code: Optional[Indexed(str)] = None
    country: Optional[str] = None
    region_id: Optional[int] = None
    region_name: Optional[str] = None
    winery_id: Optional[int] = None
    winery_name: Optional[Indexed(str)] = None
    website: Optional[str] = None
    vintages: Optional[str] = None
    avg_rating: Optional[float] = None
    rating_count: int = 0

    class Settings:
        name = "xwines_wines"
        indexes = [
            "xwines_id",
            "name",
            "wine_type",
            "country_code",
            "winery_name",
            [
                ("name", "text"),
                ("winery_name", "text"),
            ],
        ]

    def __repr__(self) -> str:
        return f"<XWinesWine(xwines_id={self.xwines_id}, name={self.name}, winery={self.winery_name})>"


class XWinesMetadata(Document):
    """X-Wines dataset metadata for version tracking.

    Stores information about the imported X-Wines dataset version.
    """

    key: Indexed(str, unique=True)
    value: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "xwines_metadata"
        indexes = [
            "key",
        ]

    def __repr__(self) -> str:
        return f"<XWinesMetadata(key={self.key}, value={self.value})>"
