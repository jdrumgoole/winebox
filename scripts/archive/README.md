# Archived one-off scripts

Scripts here were run once (or a handful of times) for a specific migration
or hotfix and are kept only for historical reference. They are not part of
the ongoing ops rotation and should not be run on current production data
without a careful review of the schema assumptions.

- `fix_oat_migration_events.py` — OAT-only fix: moved `bottle_events` rows
  into `wine_events` with a `scope` field after the initial bottle-events
  migration ran with a buggy writer.
- `migrate_to_bottles.py` — one-time migration that generated per-bottle
  `Bottle` + `BottleEvent` records from the old embedded
  `Wine.inventory.quantity` schema.
- `migrate_wine_ownership.py` — added `owner_id` to legacy Wine and
  Transaction documents back when the app was single-user.

Ongoing, versioned migrations live in `scripts/migrations/` and are tracked
by the per-version migrator (`db_migrate_N_to_M.py`). Anything new should
go there, not here.
