"""MongoDB document models for WineBox."""

from winebox.models.wine import Wine, InventoryInfo, GrapeBlendEntry, ScoreEntry
from winebox.models.transaction import Transaction, TransactionType
from winebox.models.user import User
from winebox.models.wine_type import WineType
from winebox.models.grape_variety import GrapeVariety
from winebox.models.region import Region
from winebox.models.classification import Classification
from winebox.models.xwines import XWinesWine, XWinesMetadata
from winebox.models.token_blacklist import RevokedToken
from winebox.models.login_attempt import LoginAttempt
from winebox.models.import_batch import ImportBatch, ImportStatus

__all__ = [
    # Main documents
    "Wine",
    "Transaction",
    "TransactionType",
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
]
