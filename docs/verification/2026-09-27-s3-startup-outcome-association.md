# S3 startup outcome association

## F1-STATUS — Scope and status

F1 independent source and test-packaging review passed; six-file local commit approved. A07 and S3-04 remain OPEN. This slice implements the approved F1 contract in `runtime/service.py` and `runtime/explicit_service.py`, adds `tests/integration/test_s3_startup_outcome_association.py`, and updates five coordinator expectations in `test_explicit_runtime_production.py`. No production acquisition, recovery, scheduler, composition, database schema, UI, or API source is changed by this slice. The shared working tree contains other owners' changes; these observations do not certify an isolated committed revision. No push, deployment, live request, or real-user database access was performed.

## F1-DESIGN — Implemented boundaries

`PlanCycleIdentity` and `PlanCycleOutcome` are immutable internal values. The coordinator captures ordered candidate identity before index/stock acquisition, selects the due subset without recapturing activation, and validates the complete expected identity set before extracting real results in original order. Missing, duplicate, extra, wrong consumer/plan/activation/target identities fail closed. Represented legacy facts/result identities and explicit result identities are cross-checked. Legal legacy `INCOMPLETE` retains `facts=None`, no evaluation, no claim, and no event.

Known activation, inventory, and manual-risk guard failures directly produce a closed internal `STALE` value. No broad exception catch surrounds evaluation, storage, commit, or publication. Public legacy batch methods retain tuple results and expected-stale filtering. Standalone explicit calls retain the optional `expected_activation_revision=None` default and typed stale exceptions. Production supplies the original positive revision through strict capture and final commit. Explicit result activation identity is also checked before persistence and on the DUPLICATE path.

Accounting is per plan, not batch atomicity. A healthy sibling may commit independently, including before a later protocol/association error. Cancellation and unexpected errors propagate. Same-type exceptions from evaluation callbacks, persistence, commit, post-commit callbacks, or publication are not normal stale outcomes.

## F1-RED — Reproduction evidence

Separate pre-implementation runs established:

- Six initial cases: **3 failed, 3 passed in 10.01s**. Final-transaction activation invalidation escaped the coordinator. Internally consistent wrong activation results were accepted on both fresh and duplicate paths. Publisher-error and standalone-default controls passed.
- Four actual composition races: **4 failed in 4.56s**. A real SDK wait followed by same-plan deactivate/reactivate allowed the old 10:05 invocation to create a revision 3 ledger. Final activation, inventory, and manual-risk changes faulted the runner.
- Twelve association interface cases: **12 failed in 1.35s**, because the proposed internal identity/accounting API did not yet exist. These are interface RED evidence, not twelve additional observed production faults.

During fixture development, incorrect SQL column assumptions (`target_bucket_end` instead of ledger `target_value`, and direct `alert_event.symbol`) were corrected against the actual schema. The final alert snapshot selects the symbol from `payload_json`; no table safety assertion was removed. These fixture errors are not classified as product regressions.

## F1-VERIFY — Final candidate evidence

The final focused file contains **44 cases**: the initial 22, four error-origin controls, three legacy publisher/cancellation controls, four explicit payload controls, one mixed-consumer ordering control, one legacy stale/sibling control, and nine legacy payload controls. Final full-file execution: **44 passed in 17.48s**.

The strengthened four composition races use actual composition/controller/provider/scheduler, a fake SDK, a controlled market clock, and temporary SQLite. They seed a genuine earlier 10:00 explicit ledger as fixture setup. The tested 10:05 and 10:10 evaluations are driven only by real scheduler deadlines. They assert original revision 1 typed stale accounting, no rejected-scope business changes under either activation revision, exact preservation of pre-existing rows, independent healthy-sibling commit, unchanged runtime generation, no `RUNTIME_RUNNER_FAILED`, and successful next eligible 10:10 evaluation without replaying 10:05. Snapshot coverage includes both ledgers, explicit rule occurrence state, alert outbox, legacy results/head/risk, and pending close state. HTTP entry points are forbidden.

Adjacent run: **133 passed in 74.12s**, comprising the then-current 35 focused cases plus `test_ten_symbol_runtime.py`, `test_market_index_runtime.py`, and `test_explicit_runtime_production.py`. The subsequent nine legacy payload cases separately passed **9 in 2.34s** before the final complete-file run. These overlapping runs are recorded separately, not added together as a final suite count. Ruff and whitespace checks passed; the existing Starlette/httpx deprecation warning remains.

The following five existing coordinator cases now assert `results == ()` instead of an escaping `StaleExplicitDecisionError`:

- `test_real_sell_scheduler_rejects_concurrent_inventory_revision_change`.
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[deactivation]`.
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[rotation]`.
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[inventory]`.
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[manual-risk]`.

Their existing zero-alert, zero-rule-occurrence, inventory, and publication assertions remain. This implements the approved normal-stale coordinator semantics; it does not remove the safety checks. The new composition cases add sibling, generation, and next-deadline guarantees. Standalone typed-raise controls remain enabled.

## F1-TRANSITION — Original A07 matrix

The unchanged original 13-case file produced **3 failed, 10 passed in 11.94s**. Both incomplete-prefix runner-fault regressions now pass. Both progress cases now fail because their missing startup prefix remains unrecovered by 10:10:12 after F1 removes accidental supervisor-restart recovery. The frozen-cutoff case still fails by persisting 10:01 after capturing 10:00. Safety, complete-prefix restart, future-row/fresh-acquisition, and all three oracle controls remain passing. No skip, xfail, relaxed time bound, forced restart, or fabricated INCOMPLETE was introduced. F2/F3 remain required before claiming A07 completion.

## F1-REVIEW — Independent review and self-contained test correction

Independent Sol review found no source P1/P2. Separate runs passed **44 tests in 17.46s** and **98 adjacent tests in 58.21s**. The original A07 matrix again had **3 failed, 10 passed in 11.86s**, with the same two progress failures and frozen-cutoff failure. Four additional in-memory checks confirmed that explicit evaluator/commit-admission and legacy public/strict evaluator exceptions of the stale type propagate without business writes. Source and dependency hashes were stable during those runs. These results are separate, overlapping evidence, not an aggregate pass.

One P2 concerned packaging: the new test imported `_DeadlineClock` from the untracked A07 test file, which was not part of this six-file slice. The coordinator reproduced **one collection error** by rejecting that module through `builtins.__import__`, without moving or editing A07 files. An earlier `sys.meta_path` attempt did not exclude pytest's rewriting hook and is not RED evidence. The correction keeps the same small clock fixture locally, inheriting the already tracked `ControlledClock`; deadline parking, the 64-wake bound and actual scheduler progression are unchanged. Independent helper inspection confirmed equivalence and no remaining untracked test import.

With that module still forbidden, the final focused-plus-adjacent run passed **142 tests, 1 warning in 74.90s**. The two reviewed runtime sources were unchanged; the shared `production.py` dependency was under another writer, so this is not a clean-revision integrated gate. Focused Ruff and whitespace checks passed. Final paired-report review closed P2 with no remaining P1/P2; only the six F1 files may be committed, not the still-RED A07 matrix.

The isolation command is below. To reproduce the pre-fix collection failure, the pytest argument list contained only the focused path, `--collect-only` and `-q`.

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest
original_import = builtins.__import__
def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'test_s3_startup_minute_coverage':
        raise ModuleNotFoundError('Uncommitted A07 test is unavailable in the F1 commit')
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = isolated_import
raise SystemExit(pytest.main(['tests/integration/test_s3_startup_outcome_association.py', 'tests/integration/test_ten_symbol_runtime.py', 'tests/integration/test_market_index_runtime.py', 'tests/integration/test_explicit_runtime_production.py', '-q', '--tb=short']))"
```

## F1-COMMANDS — Reproduction

Run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_outcome_association.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_outcome_association.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_market_index_runtime.py tests/integration/test_explicit_runtime_production.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/service.py src/trade_plan_monitor/runtime/explicit_service.py tests/integration/test_s3_startup_outcome_association.py tests/integration/test_explicit_runtime_production.py
git diff --check
```
