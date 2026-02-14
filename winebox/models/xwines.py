"""X-Wines dataset models for wine autocomplete and reference data.

These models represent read-only reference data from the X-Wines dataset.
Source: https://github.com/rogerioxavier/X-Wines
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from winebox.database import Base


class XWinesWine(Base):
    """X-Wines wine reference data.

    External wine data from the X-Wines dataset for autocomplete and auto-fill.
    This is read-only reference data - user's own wines remain in the wines table.
    """

    __tablename__ = "xwines_wines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    wine_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    elaborate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    grapes: Mapped[str | None] = mapped_column(Text, nullable=True)
    harmonize: Mapped[str | None] = mapped_column(Text, nullable=True)
    abv: Mapped[float | None] = mapped_column(Float, nullable=True)
    body: Mapped[str | None] = mapped_column(String(50), nullable=True)
    acidity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    winery_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winery_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vintages: Mapped[str | None] = mapped_column(Text, nullable=True)
    avg_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<XWinesWine(id={self.id}, name={self.name}, winery={self.winery_name})>"


class XWinesMetadata(Base):
    """X-Wines dataset metadata for version tracking.

    Stores information about the imported X-Wines dataset version.
    """

    __tablename__ = "xwines_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<XWinesMetadata(key={self.key}, value={self.value})>"
