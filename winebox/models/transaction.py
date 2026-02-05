"""Transaction model for tracking wine check-ins and check-outs."""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from winebox.database import Base

if TYPE_CHECKING:
    from winebox.models.wine import Wine


class TransactionType(str, enum.Enum):
    """Type of transaction."""

    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"


class Transaction(Base):
    """Transaction model for tracking wine movements."""

    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        CHAR(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    wine_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("wines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    wine: Mapped["Wine"] = relationship("Wine", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, type={self.transaction_type}, quantity={self.quantity})>"
