"""MongoDB document models for WineBox."""

from winebox.models.wine import Wine, WineCollection, InventoryInfo, GrapeBlendEntry, ScoreEntry
from winebox.models.transaction import Transaction, TransactionType, RemovalReason
from winebox.models.user import User
from winebox.models.wine_type import WineType
from winebox.models.grape_variety import GrapeVariety
from winebox.models.region import Region
from winebox.models.classification import Classification
from winebox.models.xwines import XWinesWine, XWinesMetadata
from winebox.models.token_blacklist import RevokedToken
from winebox.models.login_attempt import LoginAttempt
from winebox.models.import_batch import ImportBatch, ImportStatus
from winebox.models.import_batch_row import RawUploadRow
from winebox.models.case import Case
from winebox.models.bottle import Bottle
from winebox.models.wine_event import WineEvent, WineEventType, WineEventScope
from winebox.models.price_capture import PriceCapture, CaptureType, ShopLocation, GeoCoordinates

__all__ = [
    # Main documents
    "Wine",
    "WineCollection",
    "Transaction",
    "TransactionType",
    "RemovalReason",
    "User",
    "RevokedToken",
    "LoginAttempt",
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
    # Case & Bottle tracking
    "Case",
    "Bottle",
    "WineEvent",
    "WineEventType",
    "WineEventScope",
    # Price tracker
    "PriceCapture",
    "CaptureType",
    "ShopLocation",
    "GeoCoordinates",
]
