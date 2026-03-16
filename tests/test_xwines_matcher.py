"""Tests for the Claude-powered wine matching service."""

import os
from unittest.mock import MagicMock, patch

import pytest

from winebox.config import settings
from winebox.services.xwines_matcher import (
    _build_prompt,
    _parse_response,
    match_wines_batch,
)

has_anthropic_key = bool(
    settings.anthropic_api_key
    or os.getenv("WINEBOX_ANTHROPIC_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
)
skip_no_key = pytest.mark.skipif(
    not has_anthropic_key,
    reason="No Anthropic API key available",
)


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_single_query() -> None:
    """Prompt includes query and candidates in expected format."""
    queries = ["Chateau Margaux"]
    candidates = {
        "Chateau Margaux": [
            {"name": "Chateau Margaux", "winery_name": "Chateau Margaux", "country": "France"},
            {"name": "Margaux AOC", "winery_name": "Other Producer"},
        ],
    }
    prompt = _build_prompt(queries, candidates)
    assert 'Query 1: "Chateau Margaux"' in prompt
    assert "1. Chateau Margaux by Chateau Margaux (France)" in prompt
    assert "2. Margaux AOC by Other Producer" in prompt


def test_build_prompt_multiple_queries() -> None:
    """Multiple queries are numbered sequentially."""
    queries = ["Wine A", "Wine B"]
    candidates = {
        "Wine A": [{"name": "Candidate A"}],
        "Wine B": [{"name": "Candidate B", "region_name": "Bordeaux", "wine_type": "Red"}],
    }
    prompt = _build_prompt(queries, candidates)
    assert 'Query 1: "Wine A"' in prompt
    assert 'Query 2: "Wine B"' in prompt
    assert "from Bordeaux" in prompt
    assert "[Red]" in prompt


def test_build_prompt_no_candidates() -> None:
    """Query with no candidates shows (no candidates)."""
    queries = ["Unknown Wine"]
    candidates = {}
    prompt = _build_prompt(queries, candidates)
    assert "(no candidates)" in prompt


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_valid_json() -> None:
    """Valid JSON response is parsed correctly."""
    result = _parse_response('{"1": 2, "2": null, "3": 1}', 3)
    assert result == {"1": 2, "2": None, "3": 1}


def test_parse_response_markdown_wrapped() -> None:
    """JSON wrapped in markdown code blocks is parsed."""
    result = _parse_response('```json\n{"1": 3}\n```', 1)
    assert result == {"1": 3}


def test_parse_response_malformed_json() -> None:
    """Malformed JSON returns empty dict."""
    result = _parse_response("not json at all", 1)
    assert result == {}


def test_parse_response_non_dict() -> None:
    """Non-dict JSON returns empty dict."""
    result = _parse_response("[1, 2, 3]", 1)
    assert result == {}


def test_parse_response_invalid_values_skipped() -> None:
    """Invalid values (non-int, zero, negative) are skipped."""
    result = _parse_response('{"1": 0, "2": -1, "3": "abc", "4": 5}', 4)
    assert result == {"4": 5}


def test_parse_response_empty_json() -> None:
    """Empty JSON object returns empty dict."""
    result = _parse_response("{}", 0)
    assert result == {}


# ---------------------------------------------------------------------------
# match_wines_batch — edge cases (no API call needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_wines_batch_empty_queries() -> None:
    """Empty queries list returns empty dict."""
    result = await match_wines_batch([], {})
    assert result == {}


@pytest.mark.asyncio
async def test_match_wines_batch_no_candidates() -> None:
    """Queries with no candidates return None for each."""
    result = await match_wines_batch(["Wine A", "Wine B"], {})
    assert result == {"Wine A": None, "Wine B": None}


@pytest.mark.asyncio
@patch("winebox.services.xwines_matcher.settings")
async def test_match_wines_batch_disabled(mock_settings: MagicMock) -> None:
    """Returns empty dict when Claude matching is disabled."""
    mock_settings.use_claude_matching = False
    result = await match_wines_batch(
        ["Wine A"],
        {"Wine A": [{"name": "Candidate"}]},
    )
    assert result == {}


# ---------------------------------------------------------------------------
# match_wines_batch — real Claude calls
# ---------------------------------------------------------------------------


@skip_no_key
@pytest.mark.asyncio
async def test_match_wines_batch_picks_correct_wine() -> None:
    """Claude correctly picks the matching candidate from a list."""
    result = await match_wines_batch(
        ["Chateau Lynch-Bages, Pauillac"],
        {
            "Chateau Lynch-Bages, Pauillac": [
                {"name": "Yellow Tail Shiraz", "winery_name": "Yellow Tail", "country": "Australia", "wine_type": "Red"},
                {"name": "Pauillac (Grand Cru Classe)", "winery_name": "Chateau Lynch-Bages", "country": "France", "wine_type": "Red"},
                {"name": "Kendall-Jackson Chardonnay", "winery_name": "Kendall-Jackson", "country": "USA", "wine_type": "White"},
            ],
        },
    )
    # Claude should pick candidate 2 (Lynch-Bages)
    assert result.get("Chateau Lynch-Bages, Pauillac") == 2


@skip_no_key
@pytest.mark.asyncio
async def test_match_wines_batch_returns_null_for_no_match() -> None:
    """Claude returns null when no candidate is a reasonable match."""
    result = await match_wines_batch(
        ["Domaine de la Romanee-Conti"],
        {
            "Domaine de la Romanee-Conti": [
                {"name": "Yellow Tail Shiraz", "winery_name": "Yellow Tail", "country": "Australia"},
                {"name": "Barefoot Merlot", "winery_name": "Barefoot", "country": "USA"},
            ],
        },
    )
    assert result.get("Domaine de la Romanee-Conti") is None


@skip_no_key
@pytest.mark.asyncio
async def test_match_wines_batch_multiple_queries() -> None:
    """Claude handles multiple queries in a single batch."""
    result = await match_wines_batch(
        ["Chateau Margaux", "Opus One"],
        {
            "Chateau Margaux": [
                {"name": "Chateau Margaux", "winery_name": "Chateau Margaux", "country": "France", "wine_type": "Red"},
                {"name": "Margaux AOC Blend", "winery_name": "Some Producer", "country": "France"},
            ],
            "Opus One": [
                {"name": "Opus One", "winery_name": "Opus One Winery", "country": "USA", "wine_type": "Red"},
                {"name": "Overture by Opus One", "winery_name": "Opus One Winery", "country": "USA"},
            ],
        },
    )
    # Should pick exact matches
    assert result.get("Chateau Margaux") == 1
    assert result.get("Opus One") == 1
