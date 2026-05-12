"""API routers for WineBox.

Auth routes are owned by the embedded regstack instance (mounted from
:func:`winebox.main.lifespan`), so this package exports only the
domain-specific routers.
"""

from winebox.routers import cellar, search, transactions, wines

__all__ = ["wines", "cellar", "transactions", "search"]
