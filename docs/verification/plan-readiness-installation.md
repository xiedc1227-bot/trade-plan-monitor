# Plan readiness installation audit

Chinese review copy: [plan-readiness-installation.zh-CN.md](plan-readiness-installation.zh-CN.md).

## T20-A01 — Status and scope

2026-11-14, implementation base `69a977b`. **Offline engineering verified; actual read-only attempt returned NOT_READY / WAL_SIDECARS_UNAVAILABLE.** After root reviewed the frozen four files and released the user-authorized audit, one invocation ran at02:31:06–02:31:07+08:00. Its file-header preflight stopped before opening a SQLite connection. Actual schema, migration, plans, reviews, activation, evaluations and channels remain uncollected; this is not a comprehensive installation audit or a positive readiness result. No existing service was accessed. T20 completion and shared task/report updates remain with root.

The DB-only script can record persisted schema/migration, plan scope, review/activation, coverage metadata, native/legacy evaluation timestamps, liveness timestamps and delivery-attempt metadata when the read preconditions hold. It reuses the existing plan codec, `CoverageInstallation` hash-integrity validation, exact coverage trigger definitions and existing plan/channel/attempt enums. The model's `_Signed` base uses `daily_hash`, not a digital signature. It does not reconstruct readiness, source-review authority, current evaluation or send eligibility. Every report retains `PERSISTED_ONLY`, `authorityGranted=false`, `runtimeOwnership=UNKNOWN`, `notificationConfiguration=UNKNOWN` and `installationStatus=NOT_READY`. Recorded delivery does not verify the current channel or exact obligation.

## T20-A02 — Read and resource boundaries

- Existing file only: `mode=ro`, `query_only=ON`, one explicit read transaction. No application engine, lifespan, WAL configuration, migration, backup, checkpoint, provider, evaluator or HTTP client. Never use `immutable=1` for an active WAL database.
- A WAL-header file requires existing WAL/SHM companions. Missing companions return `WAL_SIDECARS_UNAVAILABLE` before opening SQLite; schema, migration and plan facts are then **not collected**. This is an incomplete installation observation, not comprehensive audit acceptance. No companion is created, repaired, removed or checkpointed.
- Fixed table/column whitelist. At most100 rows per section, at most10 active references; excess is explicit in `limitedSections`. Prioritize those exact active version IDs in plan/review/coverage samples; other samples have deterministic ordering. Report missing active plan/review records in `activeReferenceGaps`. Samples are not complete histories or latest-result claims.
- Reuse the plan codec's256KiB admission limit. SQLite values and serialized output are bounded to1MiB, queries to1,000,000 virtual-machine operations and5 seconds, connection wait to1 second. Exceeding availability/budgets does not produce READY. A SQLite value-limit failure makes the audit unavailable; it does not silently truncate a plan.
- No raw source, plan/evidence payload, message, config, endpoint, exception message or database path is emitted. Normalize UUIDs/timestamps; use existing closed enums and packaged migration names. Raw review/proof chains and delivery bindings are not revalidated; their metadata is labeled `NOT_REVALIDATED` where applicable. Schema presence or an installation marker with valid hash integrity is not current source/review/runtime proof.
- Missing/old/incompatible schema is reported without creating tables. An unreadable or interrupted collection may retain partial metadata, with `UNAVAILABLE_OR_BUDGET_EXCEEDED`; no claim of complete evidence follows. Existing `audit.json` is never overwritten.

## T20-A03 — Offline verification

From `D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_plan_readiness_audit.py -q --basetemp=.pytest_cache/pma-t20-audit-frozen-tmp
.\.venv\Scripts\ruff.exe check scripts/audit_plan_readiness.py tests/integration/test_plan_readiness_audit.py
```

Frozen selection: **16 unique tests passed in2.57s**, no failures/skips/xfail/xpass; Ruff passed. Tests use real disposable SQLite and existing temporary migration/seed tools. They cover missing/old/incompatible/corrupt files, hash-integrity marker tampering, real saved-plan scope and review, oversize plans, committed WAL visibility with unchanged main/WAL bytes, refused database writes, denied network/initialization/evaluation, missing WAL companions, persisted heartbeat/legacy evaluation without current owner, historical channel results,100-row bounds,107 saved versions with active version/review retained, CLI opt-in and non-overwrite. This is not full-project regression or actual installation evidence.

Original failures are retained: RED had1 missing-module collection error; `green1` had6 passes and1 fixture FK failure (missing parent alert, subsequently supplied). `green2` passed10; `final` passed14; `owner-final` passed16. These runs overlap and are **not added** to the frozen16. Earlier Ruff line-length/import findings were corrected without suppressions. The original three `.tmp` logs were moved, unchanged, into the ignored evidence directory after checking exact resolved source/destination paths.

## T20-A04 — Frozen evidence

Logs are local, ignored files under `.pytest_cache/pma-t20-audit/`; do not commit temporary databases/logs.

| Artifact | SHA-256 |
| --- | --- |
| `scripts/audit_plan_readiness.py` | `8d9f60464198a6b478530939833c5136b7fc71dff389d6028fd585b0f1ebc1c1` |
| `tests/integration/test_plan_readiness_audit.py` | `73a8d031a739f044e7b4dc9addb63942d4b07d42e423e11fa0600a057648445d` |
| `t20-audit-red.log` | `5aeacfd196c052edfba15b540d4f7b03b7ab8c93920e2439c3cae2b163b57f05` |
| `t20-audit-green1.log` | `26f03ba96b11e4c685304023b2ac814b142d3d831a1b7a96b3248c5cae964aef` |
| `t20-audit-green2.log` | `dd6e1707a63cadabc8ca035b174c242388bfe6b46507fbe5cde611840082553d` |
| `t20-audit-frozen.log` | `b4a7fa4547ef331d727aaa51ba05b2c8c76786db66f0a51ba21bd2d23e210086` |
| `t20-audit-ruff.log` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |

## T20-A05 — Actual read-only attempt and observation limit

Known database: `D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor/data/monitor.sqlite3`. No config or credential was read. Root's pre-execution review is recorded locally at `.pytest_cache/pma-t20-audit/root-review-before-actual.json`. After root release, the following exact command ran once from the project directory; the default output did not need a replacement directory:

```powershell
.\.venv\Scripts\python.exe scripts/audit_plan_readiness.py --database data/monitor.sqlite3 --read-only --output-dir .pytest_cache/pma-installation-audit
```

Start: `2026-11-14T02:31:06.0368654+08:00`; finish: `2026-11-14T02:31:07.2404409+08:00`; report `computedAt`: `2026-11-14T02:31:07.104418+08:00`. Actual exit: **2**; stdout: `PERSISTED_ONLY NOT_READY`. Result: `database=WAL_SIDECARS_UNAVAILABLE`, `installationStatus=NOT_READY`, `runtimeOwnership=UNKNOWN`, `notificationConfiguration=UNKNOWN`, `authorityGranted=false`.

The existing file has a WAL header but the required WAL/SHM pair was not fully present at preflight. The script did not open SQLite. Schema and migration arrays, all record lists, `limitedSections` and `activeReferenceGaps` are empty because collection never began: **zero collected records is not a claim that the database contains zero records or has no gaps**. Coverage installation remains UNKNOWN. Current-owner snapshot, current notification configuration and current data/evaluation/exact bindings remain missing. No inference about migration head, saved-plan count or actual channel health is possible from this attempt. No repair or repeat invocation was performed.

| Local actual evidence | SHA-256 |
| --- | --- |
| `.pytest_cache/pma-installation-audit/audit.json` | `a45c6d578c96c8aa5ad21c0b2ec6afdf73e4053e32eb790e441bf5bbe9a07db3` |

Exact command, start/finish, exit, output location and frozen code hashes are retained in `.pytest_cache/pma-t20-audit/t20-actual-receipt.json`; stdout is retained in `t20-actual-stdout.log` in that directory. These local files are not committed. Exit2 deliberately accompanies NOT_READY; it is not an actual-installation PASS. Existing outputs are preserved; any future run needs an explicitly identified fresh location and root coordination. This attempt does not authorize restoring sidecars, checkpointing, migration or service startup.

There is no explicitly configured existing service address. The current public `GET /api/v1/plan-versions/{version_id}/monitor-readiness` already supplies owned readiness; a future explicitly configured read can use it. This slice neither probes a default port nor builds an optional HTTP platform. Persisted timestamps cannot replace that owner's current snapshot. Actual migration, review/activation, inventory/cost confirmation, acquisition and test delivery remain outside this audit.

## T20-A06 — Remaining gates

The authorized actual attempt is recorded, but the missing WAL-companion prerequisite left required installation facts uncollected. **T20 actual evidence collection remains incomplete.** Offline audit engineering passed; the actual read-only attempt ran; actual schema/plan/evaluation/channel facts were not obtained; operational readiness remains unproven. Root retains that incomplete status and may continue T21 independent engineering under P07, without treating this NOT_READY as complete actual-installation acceptance. The script/test bytes are unchanged from root's pre-execution review. Provider attempts remain0/48; original03/04 positive acceptance, C05 and final gates remain unresolved. No commit, protected task edit, user migration, default service, real notification or extraction was performed. Root owns final review, shared reporting and completion decisions; this slice does not advance another task.
