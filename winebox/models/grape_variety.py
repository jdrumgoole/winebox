"""Grape variety reference document model."""

from typing import Optional

from beanie import Document, Indexed


class GrapeVariety(Document):
    """Grape variety document model representing wine grapes."""

    name: Indexed(str, unique=True)
    color: str  # 'red' or 'white'
    category: Optional[str] = None  # 'international' or 'regional'
    origin_country: Optional[str] = None

    class Settings:
        name = "grape_varieties"
        indexes = [
            "name",
            "color",
        ]

    def __repr__(self) -> str:
        return f"<GrapeVariety(id={self.id}, name={self.name}, color={self.color})>"
