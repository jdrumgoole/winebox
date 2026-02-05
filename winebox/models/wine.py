"""Wine model for storing wine information."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from winebox.database import Base

if TYPE_CHECKING:
    from winebox.models.inventory import CellarInventory
    from winebox.models.transaction import Transaction


class Wine(Base):
    """Wine model representing a wine in the cellar."""

    __tablename__ = "wines"

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    winery: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    vintage: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    grape_variety: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    alcohol_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    front_label_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    back_label_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    front_label_image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    back_label_image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="wine",
        cascade="all, delete-orphan",
        order_by="Transaction.transaction_date.desc()",
    )
    inventory: Mapped["CellarInventory | None"] = relationship(
        "CellarInventory",
        back_populates="wine",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Wine(id={self.id}, name={self.name}, vintage={self.vintage})>"
