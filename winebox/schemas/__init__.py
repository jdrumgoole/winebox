"""Pydantic schemas for WineBox API."""

from winebox.schemas.transaction import TransactionCreate, TransactionResponse
from winebox.schemas.wine import WineCreate, WineResponse, WineUpdate, WineWithInventory
from winebox.schemas.xwines import (
    XWinesSearchResponse,
    XWinesStats,
    XWinesWineDetail,
    XWinesWineSearchResult,
)

__all__ = [
    "WineCreate",
    "WineUpdate",
    "WineResponse",
    "WineWithInventory",
    "TransactionCreate",
    "TransactionResponse",
    "XWinesSearchResponse",
    "XWinesStats",
    "XWinesWineDetail",
    "XWinesWineSearchResult",
]
