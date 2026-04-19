"""CLI: enrich `XWinesWine` reference docs with Claude drinkability estimates.

Thin wrapper around `winebox.services.drinkability_enrichment.enrich_xwines_drinkability`.
Pulls credentials and DB target from the standard `WINEBOX_*` env vars so the
local-dev recipe in CLAUDE.md (point `WINEBOX_DATABASE` at `winebox_oat`) just
works.

Usage:
    uv run python -m winebox.cli.enrich_drinkability [--limit N] [--model NAME]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from winebox.database import close_db, init_db
from winebox.services.drinkability_enrichment import enrich_xwines_drinkability

logger = logging.getLogger("enrich_drinkability")


def _make_progress_printer(target: int) -> "callable":
    last = {"shown": -1}

    def _cb(enriched: int, total: int) -> None:
        # Only print when the integer percentage changes — keeps long runs readable.
        pct = int(100 * enriched / total) if total else 100
        if pct != last["shown"]:
            print(f"  [{enriched}/{total}] {pct}%", flush=True)
            last["shown"] = pct

    return _cb


async def _run(limit: int | None, model: str) -> int:
    print("→ Initialising database connection...", flush=True)
    await init_db(skip_indexes=True)
    try:
        target_str = f"{limit} wine(s)" if limit else "all unenriched wines"
        print(f"→ Enriching drinkability for {target_str} using {model}", flush=True)
        totals = await enrich_xwines_drinkability(
            limit=limit,
            model=model,
            progress_callback=_make_progress_printer(limit or 0),
        )
        print(
            "\nDone."
            f"\n  Considered: {totals['considered']}"
            f"\n  Enriched:   {totals['enriched']}"
            f"\n  Failed:     {totals['failed']}",
            flush=True,
        )
        return 0 if totals["failed"] == 0 else 3
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich XWinesWine docs with Claude drinkability estimates.",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Cap total docs considered (0 = no cap)",
    )
    parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-5",
        help="Claude model to use (default: claude-sonnet-4-5)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    limit = args.limit if args.limit > 0 else None
    try:
        return asyncio.run(_run(limit=limit, model=args.model))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
