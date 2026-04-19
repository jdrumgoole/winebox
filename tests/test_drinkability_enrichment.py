"""Unit tests for the drinkability enrichment service.

Mocks the Anthropic client so these run in-process with no API key. The
focus is on prompt shape, response parsing, validation rules, and the
batch loop / bulk_write contract — not Claude's behaviour itself, which
is covered by the trial script.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from winebox.models.drinkability import DrinkabilityConfidence, DrinkabilityEstimate
from winebox.services import drinkability_enrichment as svc


def _xwines_doc(xid: int = 1, name: str = "Test Wine", **overrides: Any) -> dict[str, Any]:
    base = {
        "_id": f"oid-{xid}",
        "xwines_id": xid,
        "name": name,
        "winery_name": "Test Winery",
        "wine_type": "Red",
        "grapes": "Cabernet Sauvignon",
        "region_name": "Napa",
        "country": "USA",
        "abv": 14.5,
        "body": "Full-bodied",
        "acidity": "Medium",
        "avg_rating": 4.2,
        "rating_count": 1500,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# build_prompt — every wine numbered, every field rendered
# ---------------------------------------------------------------------------


def test_build_prompt_numbers_each_wine_and_includes_fields() -> None:
    """Prompt lists each wine with a 1-based index and every field we care about."""
    wines = [_xwines_doc(1, "Wine A"), _xwines_doc(2, "Wine B", grapes=None)]
    prompt = svc.build_prompt(wines)

    assert "1. Wine A" in prompt
    assert "2. Wine B" in prompt
    assert "Cabernet Sauvignon" in prompt
    # Missing fields render as 'unknown grape', not as 'None' or empty
    assert "unknown grape" in prompt
    # Header instructs JSON-only output
    assert "ONLY a JSON object" in prompt


def test_build_prompt_handles_no_rating() -> None:
    """A wine with no avg_rating renders 'no rating' (not '0' or 'None')."""
    wines = [_xwines_doc(1, avg_rating=None, rating_count=0)]
    prompt = svc.build_prompt(wines)
    assert "no rating" in prompt


# ---------------------------------------------------------------------------
# parse_response — handles Claude's various output shapes
# ---------------------------------------------------------------------------


def test_parse_response_strips_markdown_json_fence() -> None:
    """Claude often wraps JSON in ```json fences; we strip them."""
    text = '```json\n{"1": {"foo": 1}}\n```'
    assert svc.parse_response(text) == {"1": {"foo": 1}}


def test_parse_response_strips_bare_fence() -> None:
    text = '```\n{"1": {"foo": 1}}\n```'
    assert svc.parse_response(text) == {"1": {"foo": 1}}


def test_parse_response_returns_empty_on_bad_json() -> None:
    """Malformed JSON → {}; we skip the batch rather than crash the run."""
    assert svc.parse_response("definitely not json") == {}


def test_parse_response_returns_empty_for_non_object() -> None:
    """A JSON list is technically valid JSON but not what we asked for."""
    assert svc.parse_response("[1, 2, 3]") == {}


# ---------------------------------------------------------------------------
# _coerce_estimate — validation rules for a single record
# ---------------------------------------------------------------------------


def _good_rec() -> dict[str, Any]:
    return {
        "peak_years_from_release": [3, 10],
        "drinkable_until_years": 15,
        "confidence": "high",
        "reasoning": "Structured tannins and high acidity.",
    }


def test_coerce_estimate_happy_path() -> None:
    est = svc._coerce_estimate(_good_rec(), model="claude-sonnet-4-5")
    assert est is not None
    assert est.peak_years_from_release_min == 3
    assert est.peak_years_from_release_max == 10
    assert est.drinkable_until_years == 15
    assert est.confidence == DrinkabilityConfidence.HIGH
    assert est.model_used == "claude-sonnet-4-5"


def test_coerce_estimate_rejects_inverted_peak() -> None:
    rec = _good_rec(); rec["peak_years_from_release"] = [10, 3]
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_rejects_until_before_peak_max() -> None:
    rec = _good_rec(); rec["drinkable_until_years"] = 5  # peak_max=10
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_rejects_unknown_confidence() -> None:
    rec = _good_rec(); rec["confidence"] = "definitely"
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_rejects_user_override_from_claude() -> None:
    """`user_override` is reserved for manual entry — Claude can't claim it."""
    rec = _good_rec(); rec["confidence"] = "user_override"
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_rejects_empty_reasoning() -> None:
    rec = _good_rec(); rec["reasoning"] = "   "
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_rejects_missing_peak_field() -> None:
    rec = _good_rec(); rec.pop("peak_years_from_release")
    assert svc._coerce_estimate(rec, model="x") is None


def test_coerce_estimate_truncates_long_reasoning() -> None:
    """Pydantic max_length is 500 — we trim before constructing."""
    rec = _good_rec(); rec["reasoning"] = "A" * 800
    est = svc._coerce_estimate(rec, model="x")
    assert est is not None
    assert len(est.reasoning) == 500


# ---------------------------------------------------------------------------
# estimate_drinkability_batch — uses anthropic, returns dict keyed by xwines_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_estimate_batch_returns_empty_when_no_api_key() -> None:
    """No key → graceful skip, not a crash."""
    with patch.object(svc.settings, "anthropic_api_key", None):
        result = await svc.estimate_drinkability_batch([_xwines_doc(1)])
    assert result == {}


@pytest.mark.asyncio
async def test_estimate_batch_returns_empty_for_empty_input() -> None:
    assert await svc.estimate_drinkability_batch([]) == {}


@pytest.mark.asyncio
async def test_estimate_batch_parses_response_keys_by_xwines_id() -> None:
    """Claude returns keys '1','2'; we map those to the input xwines_ids."""
    wines = [_xwines_doc(101, "Wine A"), _xwines_doc(202, "Wine B")]
    fake_payload = json.dumps({
        "1": _good_rec(),
        "2": {**_good_rec(), "confidence": "medium"},
    })

    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=fake_payload)]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_message)

    fake_module = MagicMock()
    fake_module.AsyncAnthropic = MagicMock(return_value=fake_client)

    with patch.object(svc.settings, "anthropic_api_key", "test-key"), \
            patch.dict("sys.modules", {"anthropic": fake_module}):
        result = await svc.estimate_drinkability_batch(wines, model="claude-sonnet-4-5")

    assert set(result) == {101, 202}
    assert isinstance(result[101], DrinkabilityEstimate)
    assert result[202].confidence == DrinkabilityConfidence.MEDIUM
    fake_client.messages.create.assert_awaited_once()
    kwargs = fake_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-5"
    assert kwargs["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_estimate_batch_skips_invalid_records() -> None:
    """One good + one bad record → only the good one comes back."""
    wines = [_xwines_doc(101), _xwines_doc(202)]
    fake_payload = json.dumps({
        "1": _good_rec(),
        "2": {"peak_years_from_release": [10, 3], "drinkable_until_years": 5,
              "confidence": "high", "reasoning": "x"},
    })
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=fake_payload)]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_message)
    fake_module = MagicMock()
    fake_module.AsyncAnthropic = MagicMock(return_value=fake_client)

    with patch.object(svc.settings, "anthropic_api_key", "test-key"), \
            patch.dict("sys.modules", {"anthropic": fake_module}):
        result = await svc.estimate_drinkability_batch(wines)

    assert list(result.keys()) == [101]


@pytest.mark.asyncio
async def test_estimate_batch_returns_empty_on_api_error() -> None:
    """Anthropic raises → empty dict, caller treats it as failed batch."""
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))
    fake_module = MagicMock()
    fake_module.AsyncAnthropic = MagicMock(return_value=fake_client)

    with patch.object(svc.settings, "anthropic_api_key", "test-key"), \
            patch.dict("sys.modules", {"anthropic": fake_module}):
        result = await svc.estimate_drinkability_batch([_xwines_doc(1)])
    assert result == {}
