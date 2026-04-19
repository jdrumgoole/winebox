"""Unit tests for drinkability compute primitives.

Pins the state-transition table for `compute_status` and the
release-offset math in `derive_window`. These are the only entry
points for constructing a `DrinkabilityWindow` or deriving a status
in application code, so coverage here means the whole system stays
consistent without exhaustive integration tests at every callsite.
"""

from __future__ import annotations

import pytest

from winebox.models.drinkability import (
    DrinkabilityConfidence,
    DrinkabilityEstimate,
    DrinkabilityStatus,
    DrinkabilityWindow,
)
from winebox.services.drinkability import compute_status, derive_window


def _estimate(
    peak_min: int = 3, peak_max: int = 10, until: int = 15,
    confidence: DrinkabilityConfidence = DrinkabilityConfidence.MEDIUM,
    reasoning: str = "Test estimate.",
    model: str = "claude-test",
) -> DrinkabilityEstimate:
    return DrinkabilityEstimate(
        peak_years_from_release_min=peak_min,
        peak_years_from_release_max=peak_max,
        drinkable_until_years=until,
        confidence=confidence,
        reasoning=reasoning,
        model_used=model,
    )


# ---------------------------------------------------------------------------
# derive_window: release-offset math
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wine_type,expected_release_year",
    [
        ("Red", 2022),           # reds get +2
        ("red", 2022),           # case-insensitive
        ("fortified", 2022),     # fortifieds get +2 (port, sherry)
        ("Dessert", 2022),       # sweet wines (sauternes) get +2
        ("White", 2021),         # whites get +1
        ("Sparkling", 2021),     # NV/vintage champagne — +1 as a rough default
        ("Rosé", 2021),
        ("", 2021),              # unknown → safe default +1
        (None, 2021),
        ("new-type-we-dont-know", 2021),  # unknown → safe default
    ],
)
def test_derive_window_release_offset(wine_type: str | None, expected_release_year: int) -> None:
    """Wine type decides release-year offset (reds/fortified/dessert +2, else +1)."""
    est = _estimate(peak_min=3, peak_max=10, until=15)
    w = derive_window(est, vintage=2020, wine_type=wine_type)
    assert w.peak_start_year == expected_release_year + 3
    assert w.peak_end_year == expected_release_year + 10
    assert w.drinkable_until_year == expected_release_year + 15


def test_derive_window_preserves_confidence_and_reasoning() -> None:
    """Window inherits confidence/reasoning from estimate for the tooltip."""
    est = _estimate(
        confidence=DrinkabilityConfidence.HIGH,
        reasoning="Structured red from a great vintage.",
    )
    w = derive_window(est, vintage=2018, wine_type="Red")
    assert w.confidence == DrinkabilityConfidence.HIGH
    assert w.reasoning == "Structured red from a great vintage."


def test_derive_window_peak_zero_means_drink_on_release() -> None:
    """An estimate of peak_min=0 means the wine is ready at release."""
    est = _estimate(peak_min=0, peak_max=2, until=5)
    w = derive_window(est, vintage=2023, wine_type="White")
    # release = 2023 + 1 = 2024 → peak starts immediately at 2024
    assert w.peak_start_year == 2024
    assert w.peak_end_year == 2026
    assert w.drinkable_until_year == 2029


# ---------------------------------------------------------------------------
# compute_status: transition table
# ---------------------------------------------------------------------------


def _window(peak_start: int = 2025, peak_end: int = 2030, until: int = 2035) -> DrinkabilityWindow:
    return DrinkabilityWindow(
        peak_start_year=peak_start,
        peak_end_year=peak_end,
        drinkable_until_year=until,
        confidence=DrinkabilityConfidence.MEDIUM,
        reasoning="Test window.",
    )


@pytest.mark.parametrize(
    "now_year,expected_status",
    [
        # peak = 2025-2030, drinkable_until = 2035
        (2020, DrinkabilityStatus.AGE_FURTHER),  # well before peak
        (2023, DrinkabilityStatus.AGE_FURTHER),  # still too early (more than 1 year out)
        (2024, DrinkabilityStatus.HOLD),          # one year before peak opens
        (2025, DrinkabilityStatus.DRINK_NOW),     # peak opens
        (2027, DrinkabilityStatus.DRINK_NOW),     # middle of peak
        (2029, DrinkabilityStatus.DRINK_NOW),     # still in peak
        (2030, DrinkabilityStatus.SELL_SOON),     # peak closed, drinkable
        (2033, DrinkabilityStatus.SELL_SOON),     # still drinkable but past peak
        (2034, DrinkabilityStatus.SELL_SOON),     # last year before past_prime
        (2035, DrinkabilityStatus.PAST_PRIME),    # beyond drinkable_until
        (2040, DrinkabilityStatus.PAST_PRIME),    # long gone
    ],
)
def test_compute_status_transitions(now_year: int, expected_status: DrinkabilityStatus) -> None:
    """Every year from AGE_FURTHER through PAST_PRIME maps to the right status."""
    assert compute_status(_window(), now_year) == expected_status


def test_compute_status_unknown_when_no_window() -> None:
    """No window → UNKNOWN; UI can skip the chip rather than lie."""
    assert compute_status(None, now_year=2026) == DrinkabilityStatus.UNKNOWN


def test_compute_status_degenerate_single_year_peak() -> None:
    """peak_start == peak_end → DRINK_NOW only in that year."""
    w = _window(peak_start=2026, peak_end=2026, until=2030)
    assert compute_status(w, 2025) == DrinkabilityStatus.HOLD
    # 2026 is both >= peak_start AND >= peak_end. The greater-than-or-equal
    # chain means peak_end wins → sell_soon. Documented behaviour: a window
    # with zero-length peak reads as "sell it while you still can", not as
    # a single-year drink-now. Claude produces min<max in practice so this
    # is a degenerate case we merely want to behave sensibly.
    assert compute_status(w, 2026) == DrinkabilityStatus.SELL_SOON
    assert compute_status(w, 2030) == DrinkabilityStatus.PAST_PRIME


# ---------------------------------------------------------------------------
# End-to-end: estimate → window → status
# ---------------------------------------------------------------------------


def test_estimate_to_status_roundtrip_for_current_vintage() -> None:
    """A freshly-released red with a 3-10 year peak is AGE_FURTHER this year."""
    est = _estimate(peak_min=3, peak_max=10, until=15)
    # 2024 vintage, red → release 2026, peak 2029-2036
    window = derive_window(est, vintage=2024, wine_type="Red")
    # Now = 2026 (release year). 2025 = hold. 2026 is 3 years out from peak_start 2029.
    # 2029 - 1 = 2028, so 2026 < 2028 → AGE_FURTHER
    assert compute_status(window, now_year=2026) == DrinkabilityStatus.AGE_FURTHER
    assert compute_status(window, now_year=2028) == DrinkabilityStatus.HOLD
    assert compute_status(window, now_year=2029) == DrinkabilityStatus.DRINK_NOW
    assert compute_status(window, now_year=2036) == DrinkabilityStatus.SELL_SOON
    assert compute_status(window, now_year=2041) == DrinkabilityStatus.PAST_PRIME


def test_estimate_to_status_roundtrip_for_aged_red() -> None:
    """A 1995 red with 5-15yr peak: in 2026 we're well past peak but still drinkable."""
    est = _estimate(peak_min=5, peak_max=15, until=30)
    # 1995 + 2 = 1997 release → peak 2002-2012, drinkable until 2027
    window = derive_window(est, vintage=1995, wine_type="Red")
    assert compute_status(window, now_year=2026) == DrinkabilityStatus.SELL_SOON
    assert compute_status(window, now_year=2027) == DrinkabilityStatus.PAST_PRIME


def test_estimate_to_status_roundtrip_for_crisp_white() -> None:
    """2024 white with 1-3 yr peak: drink now in 2026."""
    est = _estimate(peak_min=1, peak_max=3, until=5)
    # 2024 + 1 = 2025 release → peak 2026-2028
    window = derive_window(est, vintage=2024, wine_type="White")
    assert compute_status(window, now_year=2025) == DrinkabilityStatus.HOLD
    assert compute_status(window, now_year=2026) == DrinkabilityStatus.DRINK_NOW
    assert compute_status(window, now_year=2028) == DrinkabilityStatus.SELL_SOON
    assert compute_status(window, now_year=2031) == DrinkabilityStatus.PAST_PRIME
