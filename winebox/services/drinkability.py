"""Drinkability compute functions — pure, no DB, no network.

Phase 1 of the drinkability plan. These functions are behaviour-preserving
primitives that later phases compose:

- `derive_window()` converts a reference `DrinkabilityEstimate` (release-
  relative) into an absolute `DrinkabilityWindow` for a specific vintage.
- `compute_status()` maps a window + today's year onto a categorical
  `DrinkabilityStatus` — derived at read time so the UI's view is always
  consistent without a nightly recompute.

These two functions are the only way a window or status should ever be
constructed in application code. Tests pin the state-transition table.
"""

from __future__ import annotations

from typing import Optional

from winebox.models.drinkability import (
    DrinkabilityEstimate,
    DrinkabilityStatus,
    DrinkabilityWindow,
)


# Release-year offset by wine type. Whites / sparkling / rosé are usually
# released the year after vintage (e.g. 2024 harvest, 2025 release); reds
# and fortifieds spend longer in barrel/bottle before release. Unknown
# types fall through to 1 year — the safer default for "drink sooner than
# later" since a too-early release estimate will show the wine as
# ready-to-drink slightly early, not past its peak prematurely.
_RELEASE_OFFSET_YEARS: dict[str, int] = {
    "red": 2,
    "fortified": 2,
    "dessert": 2,
}
_DEFAULT_RELEASE_OFFSET = 1


def _release_offset_for(wine_type: Optional[str]) -> int:
    if not wine_type:
        return _DEFAULT_RELEASE_OFFSET
    return _RELEASE_OFFSET_YEARS.get(wine_type.strip().lower(), _DEFAULT_RELEASE_OFFSET)


def derive_window(
    estimate: DrinkabilityEstimate,
    vintage: int,
    wine_type: Optional[str],
) -> DrinkabilityWindow:
    """Convert a release-relative estimate into an absolute calendar window
    for the given vintage and wine type.

    The estimate is the same across vintages for a reference wine; the
    window is what the UI renders because users think in calendar years.
    """
    release_year = vintage + _release_offset_for(wine_type)
    return DrinkabilityWindow(
        peak_start_year=release_year + estimate.peak_years_from_release_min,
        peak_end_year=release_year + estimate.peak_years_from_release_max,
        drinkable_until_year=release_year + estimate.drinkable_until_years,
        confidence=estimate.confidence,
        reasoning=estimate.reasoning,
    )


def compute_status(
    window: Optional[DrinkabilityWindow],
    now_year: int,
) -> DrinkabilityStatus:
    """Map a (window, today) pair to a `DrinkabilityStatus`.

    Ordering is past → future:
    - `past_prime`   : today is at or beyond `drinkable_until_year`
    - `sell_soon`    : past the peak_end but still drinkable
    - `drink_now`    : inside the peak window
    - `hold`         : within one year of the peak window opening
    - `age_further`  : more than a year before peak
    - `unknown`      : no window available

    Derived at read time — never stored — so a cellar's view updates
    automatically as years pass without any background recompute.
    """
    if window is None:
        return DrinkabilityStatus.UNKNOWN
    if now_year >= window.drinkable_until_year:
        return DrinkabilityStatus.PAST_PRIME
    if now_year >= window.peak_end_year:
        return DrinkabilityStatus.SELL_SOON
    if now_year >= window.peak_start_year:
        return DrinkabilityStatus.DRINK_NOW
    if now_year >= window.peak_start_year - 1:
        return DrinkabilityStatus.HOLD
    return DrinkabilityStatus.AGE_FURTHER
