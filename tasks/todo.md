# WineBox TODOs

## Drinkability scoring — DEFERRED

Full Claude-powered drinkability feature: estimate when each wine in a user's
cellar is at its best, surface "drink now / hold / sell soon / past prime" in
the UI, and enrich the X-Wines reference data once for shared use.

**Status**: trial complete, plan written, implementation deferred.

**Trial results** (see `scripts/trial_drinkability.py`):
- Claude Sonnet 4.5 produces well-calibrated drinkability estimates from
  X-Wines fields (grape, body, acidity, region, rating)
- Haiku 4.5 is too optimistic — over-recommends ageing for mid-market wines
  (30% agreement with Sonnet/Opus); unreliable for a user-facing feature
- Opus 4.5 agrees with Sonnet ~70% but costs 4× more — no meaningful quality
  improvement
- Sonnet cost: ~$1.74 per 1000 wines, ~$80–175 to enrich the full X-Wines
  reference dataset once

**Plan**: `/Users/jdrumgoole/.claude/plans/abundant-seeking-kazoo.md`
  Full schema, resolution function with five-tier fallback, enrichment service,
  API changes, UI integration, unit + integration + E2E test coverage, deploy
  sequence, rollback path.

**When we come back to this**:
1. Re-read the plan file — design is complete
2. Start with phase 1 (schema + pure compute + unit tests, no behaviour change)
3. Run `invoke build-drinkability-profiles` locally first, inspect output
4. Then `invoke enrich-xwines-drinkability --limit 100` on winebox_oat
5. Inspect results before running the full enrichment pass
6. Phases 2–7 follow the plan sequentially

**Open questions to settle before starting**:
- Should confidence tier downgrades be configurable, or hardcoded?
- Should the regional uplift table live in code or in a small Mongo collection
  so it can be tuned without deploys?
- Is the `user_override` confidence tier separate from `high`, or do we fold
  them together?
- Do we want a one-off "re-estimate my cellar with the latest model" action
  for users, or is it only background-driven?
