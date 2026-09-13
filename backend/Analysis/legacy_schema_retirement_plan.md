# Retirement plan â€” legacy local schema repair

Owner: backend maintainer. Review checkpoint: 1 October 2026.

Stage 7 moves the original SQLite repair from main.py into
app/infrastructure/persistence/legacy_schema.py without changing SQL/backfill
semantics. Startup still executes create_all, then repair, then four workers.
The refactor task does not run this startup against local user data.

Retire repair only in a separately approved migration/operations task:

1. Inventory supported existing SQLite databases and Alembic revision state.
2. Verify migrations represent every column/index and chronological legacy
   turn backfill currently repaired by startup, using anonymized temporary copies.
3. Define backup, upgrade command, rollback, maintenance window and ownership.
4. Prove fresh install + oldest supported database + interrupted upgrade paths.
5. Upgrade supported installations and verify their tracked Alembic head.
6. Remove automatic repair and create_all only after explicit rollout approval;
   Alembic becomes the sole schema path at that point.

Those last changes intentionally alter startup/migration behavior and must not
be smuggled into the structural refactor. Existing migration files, schema,
database contents and revision markers are untouched here.
