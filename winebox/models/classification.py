"""Wine classification reference document model."""

from typing import Optional

from winebox.db import MongoDocument


class Classification(MongoDocument):
    """Classification document model representing wine quality classifications.

    Examples: Premier Cru Classé, DOCG, Grand Cru, Reserve, etc.
    """

    name: str
    display_name: str
    country: str
    system: str  # e.g., 'bordeaux_1855', 'burgundy', 'italy_docg'
    level: Optional[int] = None  # Ordering within system (1=highest)

    class Settings:
        name = "classifications"

    def __repr__(self) -> str:
        return f"<Classification(id={self.id}, name={self.name}, system={self.system})>"
