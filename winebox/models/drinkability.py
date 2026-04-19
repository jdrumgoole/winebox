"""Drinkability submodels — estimate + per-vintage window + status enum.

Pure data shapes, no persistence logic. Phase 1 of the drinkability
plan lands just these types plus the compute functions in
`winebox/services/drinkability.py`; later phases wire them through
`XWinesWine.drinkability`, `Wine.drinkability_window`, and the UI.

Design notes:

- `DrinkabilityEstimate` is keyed to the wine's *release* — it's the
  same across vintages for the same reference wine, so we compute it
  once per `XWinesWine`.
- `DrinkabilityWindow` is the vintage-adjusted absolute window — we
  compute it per user wine from the estimate + vintage + wine type.
- `DrinkabilityStatus` is never stored; `compute_status()` derives it
  at read time from the current year so a user's view is always
  consistent without needing a nightly recompute.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class DrinkabilityConfidence(str, Enum):
    """How confident Claude was in the drinkability estimate.

    `user_override` is reserved for a future manual-override path —
    Phase 1 doesn't set it; it's here so downstream code can branch
    on it without a string literal.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    USER_OVERRIDE = "user_override"


class DrinkabilityStatus(str, Enum):
    """Where a wine sits in its drinking window today.

    Ordered past → future for anyone skimming the list.
    """

    UNKNOWN = "unknown"
    PAST_PRIME = "past_prime"
    SELL_SOON = "sell_soon"
    DRINK_NOW = "drink_now"
    HOLD = "hold"
    AGE_FURTHER = "age_further"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DrinkabilityEstimate(BaseModel):
    """Release-relative drinkability estimate from Claude.

    Fields are years *relative to the wine's release year*, not
    absolute calendar years — this is the form Claude produces and
    the form we can safely cache on the reference `XWinesWine`
    without vintage-specific math.
    """

    peak_years_from_release_min: int = Field(..., ge=0, le=100)
    peak_years_from_release_max: int = Field(..., ge=0, le=100)
    drinkable_until_years: int = Field(..., ge=0, le=150)
    confidence: DrinkabilityConfidence
    reasoning: str = Field(..., max_length=500)
    model_used: str = Field(..., max_length=100)
    computed_at: datetime = Field(default_factory=_utc_now)


class DrinkabilityWindow(BaseModel):
    """Vintage-adjusted absolute drinking window for one wine.

    Derived from a `DrinkabilityEstimate` + the wine's vintage +
    wine_type (used to decide release-year offset). This is what the
    UI renders — the user cares about "drink between 2026 and 2032",
    not "3 to 9 years after release".
    """

    peak_start_year: int = Field(..., ge=1900, le=2200)
    peak_end_year: int = Field(..., ge=1900, le=2200)
    drinkable_until_year: int = Field(..., ge=1900, le=2200)
    confidence: DrinkabilityConfidence
    reasoning: str = Field(..., max_length=500)
