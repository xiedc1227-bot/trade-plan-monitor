# Empty WAL startup recovery verification

## Scope

Fix the local Web startup failure `SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT` caused by an empty `backtest-market.sqlite3-wal` and retained `-shm`. Market, result and job-store constructors share the startup recovery boundary. No dependency or schema changes are required.

## Recovery boundary

- Require an existing valid SQLite main file, an empty `-wal`, and no sidecars other than `-wal`/`-shm`.
- Inspect the immutable main file and fingerprint all source files before recovery. Require the complete current domain schema with no migration or metadata-correction reasons, then recheck the fingerprint.
- Use SQLite `PRAGMA wal_checkpoint(TRUNCATE)` with the configured busy timeout and close the recovery connection. Never manually delete files.
- Repeat strict inventory after recovery. Remaining sidecars, failed/busy checkpoint or unreadable source files block initialization.
- Migration inventory remains read-only and rejects every sidecar. Non-empty WAL, rollback journals, orphaned files, legacy/unknown schemas, pending extensions and UTC/invalid metadata remain outside automatic recovery.

## Automated evidence

- Before the fix, three new startup regression cases failed with the original error; the three migration-preservation cases passed.
- Focused migration and production-composition checks: `python -m pytest tests/integration/test_backtest_migrations.py tests/integration/test_backtest_production_composition.py -q` — **76 passed, 1 skipped**. The existing platform skip remains unchanged.
- Coverage includes frozen dataset/main-file preservation, market/result/job reopening, strict migration inventory, legacy/unknown/pending-extension/UTC sources, unsafe sidecars, concurrent readers/writers and FastAPI lifespan startup/shutdown.
- Inverting the current-schema recovery condition in memory caused all three successful-recovery regression cases to fail. Source files were not altered by this mutation check.
- Changed Python files pass Ruff lint checks; implementation and migration-regression files pass Ruff format checks. Unrelated existing formatting in the production-composition test is preserved. `git diff --check` passes.
- Offline functional suite: `python -m pytest -q -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py` — **6085 passed, 1 failed, 1 skipped, 4 deselected** in 1474.95 seconds. The sole failure is `test_openapi_change_requires_bilingual_spec_approval`; its isolated rerun fails identically.
- Baseline verification confirms this failure predates the startup fix: `HEAD:openapi.json` and the unchanged current snapshot both hash to `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`, while both `HEAD` language specifications record `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`. No API snapshot or specification approval was changed by this fix.
- The initial complete offline run was stopped during the ten-symbol 252-day capacity benchmark. No failure had been reported at that point; this is not a completed capacity/performance acceptance run. No test, threshold or marker was changed to bypass it.

## Local recovery evidence

The local market database copy passed recovery first. Both actual backtest databases were then backed up under `data/startup-recovery-20261006-9135cf8e/` before preparation. Both now inspect as `CURRENT` with zero sidecars, and SHA-256 comparison confirms both main files are byte-identical to their pre-recovery versions. The backup is ignored runtime data.

## Limits

Production backtest composition and lifespan were tested with temporary databases and an injected offline monitor runtime. The configured live monitor and external providers were not started. Capacity acceptance remains incomplete, and the existing OpenAPI approval failure prevents claiming an entirely green suite. Existing FastAPI test-client deprecation warnings are unrelated to this fix.
