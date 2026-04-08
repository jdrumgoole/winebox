"""Service layer for wine price operations.

Handles adding prices with the 20-entry cap and overflow archival
to the wine_prices_history collection.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from winebox.models.wine_price import (
    MAX_PRICES_PER_WINE,
    PriceEntry,
    WinePrice,
    WinePriceHistory,
)

logger = logging.getLogger(__name__)


async def add_price_entry(
    wine_name: str,
    vintage: Optional[int],
    wine_type: Optional[str],
    entry: PriceEntry,
) -> WinePrice:
    """Add a price entry to an existing or new WinePrice document.

    Looks up the wine by (wine_name, vintage, wine_type). If found,
    appends the entry. If the prices array exceeds MAX_PRICES_PER_WINE,
    the oldest entries are archived to wine_prices_history.

    Args:
        wine_name: Name of the wine.
        vintage: Vintage year (None if non-vintage).
        wine_type: e.g. "Red", "White", "Rosé" (None if unknown).
        entry: The price observation to add.

    Returns:
        The WinePrice document (created or updated).
    """
    now = datetime.now(timezone.utc)

    # Find existing document (global, not per-owner)
    doc = await WinePrice.find_one({
        "wine_name": wine_name,
        "vintage": vintage,
        "wine_type": wine_type,
    })

    if doc is None:
        doc = WinePrice(
            wine_name=wine_name,
            vintage=vintage,
            wine_type=wine_type,
            prices=[entry],
            created_at=now,
            updated_at=now,
        )
        await doc.insert()
        return doc

    # Append new entry
    doc.prices.append(entry)
    doc.updated_at = now

    # Overflow: archive oldest entries beyond the cap
    if len(doc.prices) > MAX_PRICES_PER_WINE:
        overflow_count = len(doc.prices) - MAX_PRICES_PER_WINE
        overflow = doc.prices[:overflow_count]
        doc.prices = doc.prices[overflow_count:]

        history_docs = [
            WinePriceHistory(
                wine_name=wine_name,
                vintage=vintage,
                wine_type=wine_type,
                timestamp=e.timestamp,
                source=e.source,
                price=e.price,
                currency=e.currency,
                owner_id=e.owner_id,
                location=e.location,
                coordinates=e.coordinates,
                notes=e.notes,
                photo_path=e.photo_path,
                capture_type=e.capture_type,
                archived_at=now,
            )
            for e in overflow
        ]
        await WinePriceHistory.insert_many(history_docs)
        logger.info(
            "Archived %d price(s) for %s %s to history",
            overflow_count, wine_name, vintage,
        )

    await doc.save()
    return doc
