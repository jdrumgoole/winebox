"""MongoDB document models for WineBox."""

from winebox.models.wine import Wine, WineCollection, InventoryInfo, GrapeBlendEntry, ScoreEntry
from winebox.models.transaction import Transaction, TransactionType, RemovalReason
from winebox.models.user import User
from winebox.models.wine_type import WineType
from winebox.models.grape_variety import GrapeVariety
from winebox.models.region import Region
from winebox.models.classification import Classification
from winebox.models.xwines import XWinesWine, XWinesMetadata
from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.models.cellar import CellarItem, EmbeddedWine
from winebox.models.cellar_event import CellarEvent, CellarEventType
from winebox.models.price_capture import CaptureType, ShopLocation, GeoCoordinates
from winebox.models.wine_price import WinePrice, WinePriceHistory, PriceEntry, PriceSource

__all__ = [
    # Main documents
    "Wine",
    "WineCollection",
    "Transaction",
    "TransactionType",
    "RemovalReason",
    "User",
    # Embedded subdocuments
    "InventoryInfo",
    "GrapeBlendEntry",
    "ScoreEntry",
    # Reference data documents
    "WineType",
    "GrapeVariety",
    "Region",
    "Classification",
    # X-Wines reference data
    "XWinesWine",
    "XWinesMetadata",
    # Import
    "ImportBatch",
    "ImportStatus",
    "RawUploadRow",
    # Cellar (document-oriented replacement)
    "CellarItem",
    "EmbeddedWine",
    "CellarEvent",
    "CellarEventType",
    # Price tracker
    "WinePrice",
    "WinePriceHistory",
    "PriceEntry",
    "PriceSource",
    "CaptureType",
    "ShopLocation",
    "GeoCoordinates",
]
