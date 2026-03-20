"""Grape variety reference document model."""

from typing import Optional

from winebox.db import MongoDocument


class GrapeVariety(MongoDocument):
    """Grape variety document model representing wine grapes."""

    name: str
    color: str  # 'red' or 'white'
    category: Optional[str] = None  # 'international' or 'regional'
    origin_country: Optional[str] = None

    class Settings:
        name = "grape_varieties"

    def __repr__(self) -> str:
        return f"<GrapeVariety(id={self.id}, name={self.name}, color={self.color})>"
