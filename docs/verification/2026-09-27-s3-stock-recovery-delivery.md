# S3 repaired explicit facts and final delivery admission

## SRD-01 — Scope and status

Base `5e56c41` plus the uncommitted F3-C source candidate. This tests-only connected representative uses `tests/integration/test_s3_stock_recovery_delivery.py` and this paired report. It proves real scheduled repair → legal explicit evaluation → durable claim → actual `CurrentDeliveryAdmission`. **Final independent source/test review passed without remaining P1/P2; report parity approval passed.** No source change is attributed to this representative. No commit/push/deployment/real service/user database is used.

The fixture uses a temporary SQLite database, valid certification, real composition/scheduler/controller/provider/evaluator/dispatcher, a legal current-bar explicit BUY rule and registered inventory. HTTP is forbidden. Only the physical SDK and external CONSOLE channel are fake; this is not IN_APP and sends no real notification. The actual final admission callable is preserved, not replaced. Existing committed helpers supply plan/configuration/clock; no untracked A07 helper is imported.

## SRD-02 — Connected controls

Both cases begin with an empty startup response. The real scheduler later invokes STOCK_RECOVERY; inside the actual SDK call the test asserts the deadline kind, owning runtime task and exact `stock-prefix:{symbol}` schedule entry `in_progress`. Repaired minutes are committed before the next legal evaluation, while explicit ledger/alerts are still absent. No test directly calls recovery/evaluation, pre-seeds alert/ledger rows or mocks the evaluator.

At actual target 10:05 evaluated at 10:05:12, the legal explicit result commits initial delivery eligibility HOLD. The real dispatcher commits CLAIMED first, verified through another connection, before either mutation:

- Metadata positive: rewrite certification metadata through the existing helper and assert the on-disk `semanticRevision` and installed `semantic_revision` remain identical. Final real admission allows exactly one fake CONSOLE send and DELIVERED.
- Reactivation negative: real repository deactivate revision 1 then activate expected revision 2 produces current activation revision 3. Real final admission suppresses the old event, sends zero messages, and sets eligibility SUPPRESS. The already legally committed CLAIMED attempt may remain and is explicitly retained; attempts are not falsely required to be zero.

At claim time the test snapshots every column of `explicit_evaluation_ledger`, `explicit_rule_occurrence_state`, `alert_event` and `minute_bar`. All four sets remain byte-value equivalent after delivery/suppression; original hashes, activation revision 1 and event provenance are unchanged. The result still has exact target 10:05 and actual evaluated_at 10:05:12. Runtime generation is unchanged and no runner fault occurs.

## SRD-03 — Evidence and limits

This is a newly added acceptance representative, not a baseline product RED. Initial fixture corrections covered calendar setup, the composition admission wrapper, the actual rule-state table name and JSON camel-case `semanticRevision`; they are not product fixes. No failing product assertion was weakened.

After the final hard oracles and date/fatal source fixes, the following author command passed **43 tests, 1 warning, 26.18s**, including these two delivery cases:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
```

The earlier standalone two-case run was 2 passed, 1 warning, 3.09s before the extra hard oracles; it is not the final evidence. The final source differs from the 43-case window only by expression line wrapping. Author full `.venv/Scripts/python.exe -m ruff check src tests scripts` passes. Source/tests remain frozen after independent review. This representative does not claim all notification channels, all explicit rule variants, cross-day requirements or C1 permission scheduling.

## Final independent validation

Independent Sol ran the following exact command from `trade-plan-monitor` on the final frozen source/tests:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**. All 11 SHA256 values (four source files and seven test files) matched the final freeze before and after the run. Ruff and diff checks passed. The final F3-C/A07 source/tests have no remaining P1/P2; the startup fatal-masking P2 is closed. The earlier independent 155/28.47s window crossed the AD22→38608 line-wrap-only change and is not final fixed-revision acceptance; it is superseded by this 159-case run, not added to it. Author and independent windows remain separate. All five report pairs passed independent parity review; overall C1/C3 are not declared closed. No source/test changes or commit accompany this documentation update.
