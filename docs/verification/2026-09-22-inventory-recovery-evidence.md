# Inventory Recovery Writer Evidence — 2026-09-22

> Canonical English; paired Chinese review copy. Continuation from `e08b219`; writer-only RR009 prerequisite, not anytime-restart acceptance.

## Scope and preserved boundaries

Future manual confirmations preserve full raw before/after rows and any newly created opening balance. Opening reductions preserve full raw snapshots, accepted effective trade date and per-operation board lot. Lot buys/reductions and opening reductions append separate `POSITION_INVENTORY_CHANGED` audits, binding source audit and inventory revisions to complete confirmation snapshots. `MISSING`/`STALE` record revision advances without changing confirmation. `SYNCED` retains quantity/clamping semantics, confirmation time and member references.

`position_inventory_audit.py` enumerates stored fields and hashes revision-plus-confirmation objects with canonical SHA-256. Inventory audit IDs use UUID5 derived from source audit ID; timestamps are copied from that source. A frozen source value avoids reloading expired ORM state. No application ID or clock call is added. Existing confirmation/opening hashes and strict version 1 lot audit payloads remain unchanged. New opening snapshots retain raw timestamp strings; legacy opening hashes retain DTO serialization. No new writer size limit is imposed on accepted member lists.

Evidence shares the caller transaction with positions, inventory revisions, monitor events and application receipts. Audit ID collisions fail visibly, never overwriting old rows. No migration, backfill, live provider, real notification, replay or production default switch is included. These hashes establish stored consistency, not authenticity against a database writer. Stored snapshots do not establish historical completeness or grant replay/send permission.

## Test-first and independent review

Implementation used `gpt-6-astra` / `high`; independent design and final reviews used `gpt-6-astra` / `xhigh`. These settings do not attest the parent task's model/effort. Extra cross-model review remains skipped per the user's earlier choice.

Initial writer tests failed 14 cases for missing confirmation/opening evidence and inventory receipts, then passed after implementation. Independent service tests, run after the confirmation slice but before transition receipts, failed 10 and passed 6. They cover eight scenarios across engine/service recreation and failure injection after evidence and completed idempotency receipts. Three additional UUID collision cases prove preservation of the existing row and complete command rollback.

Design review clarified raw UTC `+00:00` versus DTO `Z`, raw member JSON preservation, missing/stale revision advances and variable board lots (`100 → 93 → 90`, using `7` then `3`). Final review found a compatibility regression: reparsing a stored timestamp loses timezone/fold. Three tests reproduced rejection of an otherwise accepted Shanghai `fold=1` clock. The fix forwards the original datetime while retaining the raw audit string; all three pass. Independent final review found no remaining actionable issue within the writer contract.

Two old tests assumed every audit was a lot audit. Lot assertions/cloning now scope to `POSITION_LOT`; the writer test additionally checks total audit count and one-to-one inventory/source linkage. A third notification transaction test expected one audit after buying; it now expects both audit actions and compares every stored audit column after rollback. No test is skipped, removed or weakened. One run overlapped the multi-file clock correction and observed a temporary signature mismatch; the stable-tree rerun passes.

## Executed verification

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_recovery_audit.py -q` | 18 passed after clock correction |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_position_inventory_recovery_transactions.py tests/integration/test_position_inventory_recovery_audit.py tests/integration/test_position_lot_recovery_audit.py tests/integration/test_position_lot_history.py tests/integration/test_position_inventory.py tests/integration/test_position_production_composition.py -q --tb=short` | 168 passed, 1 existing warning; 20.23 seconds |
| Independent final writer/transaction/lot-audit selection | 48 passed, 1 existing warning; 7.27 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py -q --tb=short` | 38 passed; 5.84 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3653 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 461.17 seconds |

The final stable-tree regression includes all 37 new tests with no new failure. The four baseline failures remain: canonical index-head update time (10:36 versus 10:38), pending-close index-error reference health (LIVE versus BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request missing required temperature and being rejected before its fake transport. They are not fixed or waived here. The unchanged heavy backtest file and live-provider tests are outside this run; this is not a full-suite or final acceptance pass. The existing skip is the Windows/POSIX ownership boundary; the warning is Starlette/httpx deprecation.

Paired heading and technical-literal parity checks passed, as did staged whitespace checks. A scoped high-confidence secret-pattern scan across all 13 changed files found no matches; this is not a comprehensive credential audit. Changes are saved as one local increment; no push, merge or deployment is included.

## Remaining work

RR009/C2 remain open. Next implement strict bounded decoders for these three evidence shapes, preserving unknown for legacy/missing/malformed data; then establish source linkage, unique chains and complete historical inventory under an explicit cutoff/late-registration policy. A confirmation root has no monitor publication, so the single-lot root rule must not be copied blindly. Risk source-effective semantics, chronological execution, final per-channel admission, lifecycle/status/UI integration and actual process-restart acceptance remain separate requirements. This is not completion of stage 3 or authorization to enter production recovery. Remote synchronization and deployment remain separate.

A read-only follow-up scoped those decoder boundaries but did not approve a new reader contract. Reader budgets must explicitly cover outer UTF-8 content and nested member lists without restricting writer admission. Preserve raw strings for hashes/state comparison and do not assume all stored quantities are multiples of 100, all IDs are UUIDs, or reconfirmation always changes the confirmation ID. Single-record validation cannot prove source existence, exchange dates, member completeness or historical applicability; cross-record proof and cutoff policy remain separate.
