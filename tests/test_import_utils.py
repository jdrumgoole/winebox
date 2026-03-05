"""Tests for import service utility functions."""

import pytest

from winebox.services.import_service.utils import chunked


def test_chunked_basic() -> None:
    """Test basic chunking of a list."""
    result = list(chunked([1, 2, 3, 4, 5], 2))
    assert result == [[1, 2], [3, 4], [5]]


def test_chunked_exact_multiple() -> None:
    """Test chunking when length is exact multiple of size."""
    result = list(chunked([1, 2, 3, 4], 2))
    assert result == [[1, 2], [3, 4]]


def test_chunked_single_item() -> None:
    """Test chunking with single-item chunks."""
    result = list(chunked([1, 2, 3], 1))
    assert result == [[1], [2], [3]]


def test_chunked_larger_than_input() -> None:
    """Test chunking when size is larger than input."""
    result = list(chunked([1, 2], 10))
    assert result == [[1, 2]]


def test_chunked_empty() -> None:
    """Test chunking an empty iterable."""
    result = list(chunked([], 5))
    assert result == []


def test_chunked_generator_input() -> None:
    """Test chunking a generator (not just lists)."""
    gen = (x for x in range(7))
    result = list(chunked(gen, 3))
    assert result == [[0, 1, 2], [3, 4, 5], [6]]


def test_chunked_invalid_size() -> None:
    """Test that size < 1 raises ValueError."""
    with pytest.raises(ValueError, match="chunk size must be >= 1"):
        list(chunked([1, 2, 3], 0))

    with pytest.raises(ValueError, match="chunk size must be >= 1"):
        list(chunked([1, 2, 3], -1))
