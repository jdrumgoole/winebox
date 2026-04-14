"""Trial run: ask Claude to estimate drinkability windows for 10 random X-Wines.

Samples 10 wines at random from the xwines_wines collection and asks Claude
to produce a drinkability recommendation for each. Prints the results,
token usage, cost estimate, and a set of automated plausibility checks.

No database writes. No app changes. This is purely a feasibility trial
to validate prompt structure and output quality before wiring drinkability
into background enrichment.

Usage:
    source .env && WINEBOX_USE_CLAUDE_VISION=false \\
        uv run python scripts/test_drinkability_trial.py

Options:
    --sample-size N   Number of wines to sample (default: 10)
    --model NAME      Claude model to use (default: settings.claude_matching_model)
    --seed N          Random seed for reproducibility (default: none)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Any

from winebox.config import settings
from winebox.database import close_db, get_database, init_db

logger = logging.getLogger("drinkability_trial")

# Model pricing per million tokens (input, output) as of late 2025
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-5-20251015": (3.00, 15.00),
    "claude-opus-4-1-20250805": (15.00, 75.00),
    "claude-opus-4-1": (15.00, 75.00),
    "claude-opus-4-5-20251101": (15.00, 75.00),
    "claude-opus-4-5": (15.00, 75.00),
}


def _cost_for_model(model: str, input_tok: int, output_tok: int) -> float:
    in_rate, out_rate = MODEL_PRICING.get(model, (0.80, 4.00))
    return (input_tok / 1_000_000) * in_rate + (output_tok / 1_000_000) * out_rate

ALLOWED_RECOMMENDATIONS = {"drink_now", "hold", "sell_soon", "age_further"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}

PROMPT_TEMPLATE = """You are a wine expert estimating drinkability windows for wines.

For each numbered wine below, estimate:
  - peak_years_from_release: [min, max] — years from release when the wine is at its best
  - drinkable_until_years: integer — years from release after which the wine is past its prime
  - recommendation: "drink_now" | "hold" | "sell_soon" | "age_further" — assuming release_year = 2020 (so today is 5 years post-release)
  - confidence: "high" | "medium" | "low" — based on how much the wine's data supports the estimate
  - reasoning: one sentence explaining the choice

Consider grape variety (Cabernet ages longer than Pinot Noir, Riesling longer than Sauvignon Blanc),
body (full-bodied ages longer), acidity (higher acidity = longer aging), region typical styles,
and rating/popularity as a quality proxy.

Respond with ONLY a JSON object keyed by wine number (as a string), no prose, no markdown:
{"1": {"peak_years_from_release": [3, 10], "drinkable_until_years": 15, "recommendation": "hold",
       "confidence": "high", "reasoning": "..."}, ...}

WINES:
"""


async def sample_wines(size: int) -> list[dict[str, Any]]:
    """Return `size` random X-Wines documents with the fields we need."""
    db = get_database()
    pipeline: list[dict[str, Any]] = [
        {"$match": {
            "name": {"$ne": None},
            "wine_type": {"$ne": None},
        }},
        {"$sample": {"size": size}},
        {"$project": {
            "_id": 0,
            "xwines_id": 1,
            "name": 1,
            "winery_name": 1,
            "wine_type": 1,
            "grapes": 1,
            "region_name": 1,
            "country": 1,
            "abv": 1,
            "body": 1,
            "acidity": 1,
            "avg_rating": 1,
            "rating_count": 1,
        }},
    ]
    cursor = await db["xwines_wines"].aggregate(pipeline)
    return await cursor.to_list(length=size)


def _fmt(value: Any, placeholder: str = "unknown") -> str:
    if value is None or value == "":
        return placeholder
    return str(value)


def build_prompt(wines: list[dict[str, Any]]) -> str:
    lines = [PROMPT_TEMPLATE]
    for i, w in enumerate(wines, 1):
        grapes = _fmt(w.get("grapes"), "unknown grape")
        region = _fmt(w.get("region_name"), "unknown region")
        country = _fmt(w.get("country"), "unknown country")
        abv = w.get("abv")
        abv_str = f"{abv}%" if abv is not None else "unknown ABV"
        body = _fmt(w.get("body"), "unknown body")
        acidity = _fmt(w.get("acidity"), "unknown acidity")
        rating = w.get("avg_rating")
        rating_count = w.get("rating_count") or 0
        rating_str = f"{rating} ({rating_count} reviews)" if rating else f"no rating ({rating_count} reviews)"
        lines.append(
            f"{i}. {_fmt(w.get('name'))} by {_fmt(w.get('winery_name'), 'unknown winery')}, "
            f"{_fmt(w.get('wine_type'))}, grapes: {grapes}, region: {region}, {country}, "
            f"ABV: {abv_str}, body: {body}, acidity: {acidity}, rating: {rating_str}"
        )
    return "\n".join(lines)


def parse_response(text: str) -> dict[str, dict[str, Any]]:
    """Strip markdown fences and parse JSON. Returns empty dict on failure."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` or ``` ... ``` fences
        parts = text.split("```")
        # parts = ["", "json\n...content...", "", ...]
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.startswith("json"):
                candidate = candidate[4:]
            text = candidate.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from Claude: %s", e)
        logger.error("Raw response: %s", text[:500])
        return {}


def call_claude(prompt: str, model: str) -> tuple[dict[str, dict[str, Any]], int, int, float]:
    """Send the prompt to Claude. Returns (parsed, input_tokens, output_tokens, elapsed_s)."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed", file=sys.stderr)
        sys.exit(1)

    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("WINEBOX_ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: No Anthropic API key. Set WINEBOX_ANTHROPIC_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - start

    response_text = message.content[0].text
    parsed = parse_response(response_text)
    return parsed, message.usage.input_tokens, message.usage.output_tokens, elapsed


def print_results(wines: list[dict[str, Any]], recs: dict[str, dict[str, Any]]) -> None:
    print("\n" + "=" * 78)
    print("DRINKABILITY RECOMMENDATIONS")
    print("=" * 78)
    for i, wine in enumerate(wines, 1):
        rec = recs.get(str(i))
        print(f"\n{i}. {wine.get('name', 'unknown')}")
        print(f"   Winery:  {wine.get('winery_name') or '—'}")
        print(f"   Type:    {wine.get('wine_type') or '—'}  "
              f"Grapes: {wine.get('grapes') or '—'}")
        print(f"   Region:  {wine.get('region_name') or '—'}, {wine.get('country') or '—'}")
        print(f"   Body/Acidity: {wine.get('body') or '—'} / {wine.get('acidity') or '—'}  "
              f"ABV: {wine.get('abv') or '—'}%")
        if not rec:
            print("   ⚠ No recommendation returned")
            continue
        peak = rec.get("peak_years_from_release", [None, None])
        print(f"   → Recommendation: {rec.get('recommendation', '?').upper()}  "
              f"(confidence: {rec.get('confidence', '?')})")
        print(f"     Peak window:    {peak[0]}–{peak[1]} years from release")
        print(f"     Drinkable until: {rec.get('drinkable_until_years', '?')} years")
        print(f"     Reasoning: {rec.get('reasoning', '—')}")


def run_checks(wines: list[dict[str, Any]], recs: dict[str, dict[str, Any]]) -> tuple[int, list[str]]:
    """Validate structure and plausibility. Returns (pass_count, issue_list)."""
    issues: list[str] = []
    pass_count = 0

    red_windows: list[int] = []
    white_windows: list[int] = []

    for i, wine in enumerate(wines, 1):
        key = str(i)
        wine_label = f"#{i} {wine.get('name', '?')}"
        rec = recs.get(key)
        if not rec:
            issues.append(f"{wine_label}: missing from response")
            continue

        ok = True

        peak = rec.get("peak_years_from_release")
        if not (isinstance(peak, list) and len(peak) == 2
                and all(isinstance(v, (int, float)) for v in peak)):
            issues.append(f"{wine_label}: peak_years_from_release malformed ({peak!r})")
            ok = False
        elif peak[0] > peak[1]:
            issues.append(f"{wine_label}: peak_min {peak[0]} > peak_max {peak[1]}")
            ok = False

        until = rec.get("drinkable_until_years")
        if not isinstance(until, (int, float)):
            issues.append(f"{wine_label}: drinkable_until_years malformed ({until!r})")
            ok = False
        elif isinstance(peak, list) and len(peak) == 2 and isinstance(peak[1], (int, float)) and until < peak[1]:
            issues.append(f"{wine_label}: drinkable_until {until} < peak_max {peak[1]}")
            ok = False
        elif isinstance(until, (int, float)) and until > 50:
            issues.append(f"{wine_label}: drinkable_until {until} > 50 years (implausible)")
            ok = False

        if rec.get("confidence") not in ALLOWED_CONFIDENCE:
            issues.append(f"{wine_label}: confidence {rec.get('confidence')!r} not in {ALLOWED_CONFIDENCE}")
            ok = False

        if rec.get("recommendation") not in ALLOWED_RECOMMENDATIONS:
            issues.append(f"{wine_label}: recommendation {rec.get('recommendation')!r} not in {ALLOWED_RECOMMENDATIONS}")
            ok = False

        if not isinstance(rec.get("reasoning"), str) or not rec.get("reasoning"):
            issues.append(f"{wine_label}: reasoning missing or empty")
            ok = False

        if ok:
            pass_count += 1
            if isinstance(until, (int, float)):
                wine_type = (wine.get("wine_type") or "").lower()
                if "red" in wine_type:
                    red_windows.append(int(until))
                elif "white" in wine_type:
                    white_windows.append(int(until))

    # Statistical sanity: reds should average longer than whites (when we have both)
    if red_windows and white_windows:
        red_avg = sum(red_windows) / len(red_windows)
        white_avg = sum(white_windows) / len(white_windows)
        if red_avg <= white_avg:
            issues.append(
                f"Statistical anomaly: red avg drinkable_until ({red_avg:.1f}y) "
                f"≤ white avg ({white_avg:.1f}y)"
            )

    return pass_count, issues


def _short(rec: dict[str, Any] | None) -> str:
    """One-line summary of a recommendation for comparison table."""
    if not rec:
        return "— no data —"
    peak = rec.get("peak_years_from_release", [None, None])
    until = rec.get("drinkable_until_years", "?")
    return (
        f"{(rec.get('recommendation') or '?').upper():<12} "
        f"peak {peak[0]}-{peak[1]:<3}  until {until:<3}  "
        f"({rec.get('confidence', '?')})"
    )


def print_comparison(
    wines: list[dict[str, Any]],
    model_results: dict[str, dict[str, dict[str, Any]]],
) -> None:
    """Print a side-by-side comparison of multiple models' recommendations."""
    models = list(model_results.keys())
    print("\n" + "=" * 78)
    print("HEAD-TO-HEAD COMPARISON")
    print("=" * 78)

    for i, wine in enumerate(wines, 1):
        print(f"\n{i}. {wine.get('name', 'unknown')[:60]}")
        print(f"   {wine.get('wine_type') or '?'} / {wine.get('grapes') or '?'} / "
              f"{wine.get('region_name') or '?'}, {wine.get('country') or '?'} / "
              f"body {wine.get('body') or '?'}, acidity {wine.get('acidity') or '?'}")
        for model in models:
            rec = model_results[model].get(str(i))
            print(f"   {model[:30]:<32} {_short(rec)}")
            if rec and rec.get("reasoning"):
                print(f"   {'':<32} {rec['reasoning'][:100]}")


def compute_agreement(
    model_results: dict[str, dict[str, dict[str, Any]]],
    num_wines: int,
) -> dict[str, float]:
    """Compute agreement metrics between models on the recommendation field."""
    models = list(model_results.keys())
    if len(models) < 2:
        return {}

    agreements: dict[str, float] = {}
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]
            matches = 0
            compared = 0
            for k in range(1, num_wines + 1):
                r1 = model_results[m1].get(str(k))
                r2 = model_results[m2].get(str(k))
                if not r1 or not r2:
                    continue
                compared += 1
                if r1.get("recommendation") == r2.get("recommendation"):
                    matches += 1
            if compared > 0:
                agreements[f"{m1} vs {m2}"] = matches / compared
    return agreements


async def main_async(
    sample_size: int,
    models: list[str],
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"→ Initialising database connection...")
    await init_db(skip_indexes=True)

    try:
        print(f"→ Sampling {sample_size} random X-Wines...")
        wines = await sample_wines(sample_size)
        if not wines:
            print("ERROR: no wines found in xwines_wines collection", file=sys.stderr)
            return 1
        print(f"  Got {len(wines)} wines")

        prompt = build_prompt(wines)

        model_results: dict[str, dict[str, dict[str, Any]]] = {}
        model_stats: dict[str, tuple[int, int, float, float]] = {}

        for model in models:
            print(f"→ Calling Claude ({model})...")
            recs, in_tok, out_tok, elapsed = call_claude(prompt, model)
            if not recs:
                print(f"  ⚠ {model}: no parseable recommendations", file=sys.stderr)
                continue
            model_results[model] = recs
            cost = _cost_for_model(model, in_tok, out_tok)
            model_stats[model] = (in_tok, out_tok, elapsed, cost)

        if not model_results:
            print("ERROR: no model returned usable output", file=sys.stderr)
            return 2

        if len(models) == 1:
            # Single model: show the detailed view
            model = models[0]
            print_results(wines, model_results[model])
            in_tok, out_tok, elapsed, cost = model_stats[model]
            print("\n" + "-" * 78)
            print(f"Model:      {model}")
            print(f"Elapsed:    {elapsed:.2f}s")
            print(f"Input:      {in_tok} tokens")
            print(f"Output:     {out_tok} tokens")
            print(f"Est. cost:  ${cost:.5f}")

            pass_count, issues = run_checks(wines, model_results[model])
            print("-" * 78)
            print(f"Checks: {pass_count}/{len(wines)} passed structural + plausibility checks")
            if issues:
                print("Issues flagged:")
                for issue in issues:
                    print(f"  ⚠ {issue}")
            else:
                print("✓ No issues flagged")
            print()
            return 0 if pass_count == len(wines) else 3

        # Multi-model: comparison view
        print_comparison(wines, model_results)

        print("\n" + "-" * 78)
        print("PERFORMANCE & COST")
        print("-" * 78)
        print(f"{'Model':<35} {'Time':>8} {'In':>8} {'Out':>8} {'Cost':>12}")
        for model in model_results:
            in_tok, out_tok, elapsed, cost = model_stats[model]
            print(f"{model:<35} {elapsed:>7.2f}s {in_tok:>8} {out_tok:>8} {'$' + format(cost, '.5f'):>12}")

        print("\n" + "-" * 78)
        print("PLAUSIBILITY CHECKS")
        print("-" * 78)
        for model, recs in model_results.items():
            pass_count, issues = run_checks(wines, recs)
            print(f"{model:<35} {pass_count}/{len(wines)} passed, {len(issues)} issues")
            for issue in issues[:3]:
                print(f"  ⚠ {issue}")
            if len(issues) > 3:
                print(f"  ... and {len(issues) - 3} more")

        print("\n" + "-" * 78)
        print("AGREEMENT BETWEEN MODELS (recommendation field)")
        print("-" * 78)
        agreements = compute_agreement(model_results, len(wines))
        for pair, score in agreements.items():
            print(f"  {pair:<60} {score * 100:.0f}%")

        print()
        return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description="Wine drinkability trial with Claude")
    parser.add_argument("--sample-size", type=int, default=10,
                        help="Number of wines to sample (default: 10)")
    parser.add_argument("--model", type=str, action="append", default=None,
                        help="Claude model to use (repeat for head-to-head comparison)")
    parser.add_argument("--compare", action="store_true",
                        help="Run Haiku, Sonnet and Opus on the same sample")
    args = parser.parse_args()

    if args.compare:
        models = ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"]
    elif args.model:
        models = args.model
    else:
        models = [settings.claude_matching_model]

    return asyncio.run(main_async(args.sample_size, models))


if __name__ == "__main__":
    sys.exit(main())
