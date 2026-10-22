# Backtest result review

## BR-OPS01. Read results

Open a completed run. Overview shows applicable facts; **Completed fills and causes** opens each fill's **View reason** panel. **Non-trade reasons** shows bounded per-plan diagnostics; selecting an example locates its exact audit sequence. **Audit events** supports identity-based parent/child navigation. Browser Back restores selection. **Plans and provenance** retains frozen versions and detailed settings.

`POSITION_LIMIT_ONLY` has no capital return or drawdown. Unknown cost and expired evidence remain explicit. Per-plan examples are representative, at most 8 per plan and 256 overall. The evidence panel shows at most 100 condition items from its currently loaded event page. No full-run reason totals or per-fill PnL are inferred.

## BR-OPS02. Old results without lookup metadata

Newly staged monitoring-loop results automatically include derived lookup metadata. Old runs can show `NOT_READY` while retaining the original fill/audit views. For an existing result database, stop the backtest service and use its normal stopped/checkpointed maintenance state, then run from the project root:

```powershell
.venv/Scripts/python scripts/rebuild_backtest_review.py --database <result.sqlite3> --run-id <runId> --limit 100
```

The output is `{"nextAfter": "<detailId>", "hasMore": true}` or `{"nextAfter": null, "hasMore": false}`. Repeat the same command with `--after <detailId>` returned by the preceding batch until `hasMore` is false. Each invocation reads at most 100 retained verified events; an unindexed continuation is rejected. The command accepts an existing result database only. This operation changes derived metadata and its optional schema, never canonical payloads/hashes, trading decisions or missing evidence. It does not repair corrupted rows. Restart the service and reopen the reason panel.

## BR-OPS03. Availability

`EXPIRED` means details were pruned; a retained fill still displays its receipt. `NOT_RECORDED` means no artifact was recorded. `NOT_READY` means lookup metadata is not complete. `PARTIAL` means at least one relation is missing or its lookup is incomplete. These states never mean a condition was false or that there were zero trades. Pagination `hasMore` is independent of known missing relations.

## BR-OPS04. Run history unavailable after initialization failure

Check `GET /api/v1/backtest-service`. `DEGRADED` with `canRead=false` and `reason=SERVICE_REPAIR_REQUIRED` means metadata preparation did not establish a readable service; the list can return `503` even when the database schema is current. Ordinary list refreshes reuse that failed generation and do not retry initialization.

When `physicallyDrained=true`, use **Service management → Prepare backtest service again** to explicitly retry metadata preparation. This does not authorize resuming a historical job or submitting a new run. Confirm `READ_READY`, `canRead=true`, and a successful `GET /api/v1/backtest-runs?limit=20`; do not interpret an error as an empty history. If preparation fails again, inspect the local `Backtest metadata preparation failed` warning: it includes exception type, a bounded uppercase migration code when available, OS error numbers, the originating function/line and generation. Raw exception messages, database paths and source lines are omitted. `UNCLASSIFIED` does not identify the root cause; watchdog expiry has its own warning. These diagnostics remain local and are not added to API responses.

An empty WAL/SHM remnant alone does not prove corruption or explain a past failure. Preserve database protection and use the existing verified maintenance procedure when preflight reports a blocker; never delete SQLite sidecars manually. If the original failure was not recorded in sufficient detail and no longer reproduces, record that limit instead of inferring a definitive cause from a later successful retry.
