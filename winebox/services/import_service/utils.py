"""Utility functions for the import service."""

import itertools
from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def chunked(iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    """Group an iterable into fixed-size list chunks.

    The final chunk may be shorter than *size*.

    Args:
        iterable: Any iterable to chunk.
        size: Maximum number of items per chunk (must be >= 1).

    Yields:
        Lists of up to *size* items from the iterable.

    Raises:
        ValueError: If size < 1.
    """
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    it = iter(iterable)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            return
        yield chunk
