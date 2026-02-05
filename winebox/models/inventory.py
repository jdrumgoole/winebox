"""Cellar inventory model for tracking current stock levels."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from winebox.database import Base

if TYPE_CHECKING:
    from winebox.models.wine import Wine


class CellarInventory(Base):
    """Cellar inventory model tracking current wine quantities."""

    __tablename__ = "cellar_inventory"

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    wine_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("wines.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    wine: Mapped["Wine"] = relationship("Wine", back_populates="inventory")

    def __repr__(self) -> str:
        return f"<CellarInventory(wine_id={self.wine_id}, quantity={self.quantity})>"
