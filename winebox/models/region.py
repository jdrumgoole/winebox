"""Region document model with hierarchical structure."""

from typing import Optional

from pydantic import Field

from winebox.db import MongoDocument, PyObjectId


class Region(MongoDocument):
    """Region document model representing hierarchical wine regions.

    Levels:
        0 = country
        1 = region
        2 = subregion
        3 = appellation

    Uses materialized path pattern for efficient tree queries.
    """

    name: str
    display_name: str  # User-friendly name
    level: int  # 0=country, 1=region, 2=subregion, 3=appellation
    parent_id: Optional[PyObjectId] = None
    country: Optional[str] = None  # Denormalized for filtering

    # Materialized path for efficient tree queries
    ancestors: list[PyObjectId] = Field(default_factory=list)
    path: str = ""  # e.g., "france/bordeaux/medoc"

    class Settings:
        name = "regions"

    def __repr__(self) -> str:
        return f"<Region(id={self.id}, name={self.name}, level={self.level})>"

    def get_full_path(self) -> str:
        """Get the full region path as a string."""
        return self.path.replace("/", " > ") if self.path else self.display_name
