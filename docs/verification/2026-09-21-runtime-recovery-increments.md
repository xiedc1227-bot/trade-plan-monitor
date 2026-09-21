# Runtime Recovery Increment Verification — 2026-09-21

> English canonical; Chinese review copy: `2026-09-21-runtime-recovery-increments.zh-CN.md`. Continuation from `f15fda9`; implementation evidence, not deployment approval or complete anytime-restart acceptance.

## Scope and remaining gates

- RR006: injected, single-use `RecoveryCoordinator` owns bounded local reconciliation, coalesced wake, fair work, stopped admission and interruptible maintenance. Typed dependency retries remain in the loop; unexpected faults propagate. The existing production lifecycle has not been replaced.
- RR008: `RecoveryService.recover_scope` fetches one symbol, filters against a frozen cutoff, rechecks queued rollover and reads back exact committed coverage. Missing prior-day history remains missing. A composed fake-provider/controller/temporary-SQLite test verifies transient failure, sibling progress and later recovery.
- Request-control boundary: `RequestNotStartedError` preserves existing recovery state when a local guard aborts before provider I/O. It must not be interpreted as a successful provider response.
- RR010: reference reuse includes plan family/content hash, persisted version, actual activation revision/time, trade date and stock semantic revision. Checks after acquisition and before deadline admission reject a changed capture. Existing evaluator identities and transaction fences are unchanged.
- RR002: paired detailed status/protocol draft plus local-Web amendment. No REST/WebSocket schema, generated types or frontend source changed. Draft review does not close C0/C4.
- The user additionally approved latest-state handling of explicit `RISK_ALERT` during this continuation: true remains potentially eligible after catch-up, false is suppressed with retained history, unknown is held. The paired recovery specification records this rule independently of evaluator repeat suppression.
- `notifications/recovery_eligibility.py` implements that rule as an injected pure policy with typed active-plan/barrier inputs. It does not persist suppression/barriers, generate a replacement intent or call a channel. The caller still must establish authoritative current facts and perform final send admission checks.
- The user also approved delivering only legacy reminders still applicable to the latest risk and target inventory, retaining superseded notices without replay. The paired specification records this approval and evidence constraints. A read-only review identified that exit-ready need not update the risk row, intraday and official-close `WAIT` differ, and recovery-time `updated_at` cannot establish source-day ordering. No legacy classifier was enabled from incomplete evidence.
- A subsequent user approval selects only the latest identical `RISK_EXIT_READY` instruction within the same proven activation, breach episode and target inventory; earlier occurrences remain auditable. The paired specification orders those occurrences by official source date, not recovery write time. This supersession rule is recorded for the still-pending legacy delivery integration, not claimed as enabled behavior.
- `notifications/recovery_provenance.py` adds a read-only origin reader, not a delivery classifier. It verifies the canonical original alert/result/ledger, deterministic publication sequence and activation/audit chain, including the current chain tip, coherent sequence high-water and original activation cutoff. Same-hash reactivation preserves the original revision. Missing, corrupt or over-budget history returns typed `UNKNOWN`; actual database faults propagate. Fresh-session checks preserve caller-owned pending/cached state. Each activation-event/audit collection is capped at 1000 rows; there is no seven-day origin cutoff.
- The full run exposed an unrelated R32 test that relied on today's real date although the execution guard permits only 2026-09-17. Only the test clock was fixed: approved-date and expired-date cases now exercise the actual guard, with config-change rejection preserved. The execution script is unchanged; no live authorization was extended.

RR004 composition, missed-close discovery/replay, complete reference/history acquisition, runtime-generation/reconfiguration integration, atomic delivery eligibility and per-plan risk barriers, default lifecycle wiring, status/UI implementation and process-restart acceptance remain open. No production database/configuration/evidence was changed; no live provider/notification request, dependency installation, deployment or service restart was performed. This continuation does not claim all RR006/RR008/RR010 acceptance criteria are complete.

## Test-first and review evidence

| Artifact | Observed RED | Observed GREEN / review |
|---|---|---|
| Coordinator | Missing class at initial collection; later monotonic-ceiling regression failed with `timeout=None`; forward-clock regression raised `ValueError` | 12 new tests; independent Astra/xhigh review closed after three cycles |
| Scoped acquisition | Initial 9 tests failed because `recover_scope` did not exist | Expanded to 20 integration cases, including a composed recovery loop |
| Local abort | Queued rollover reset a prior transient backoff: next failure used 30 rather than 60 seconds | Regression now retains the 60-second progression; independently reviewed |
| Reference identities | Explicit-to-legacy switch missed limits/history, refresh accepted reactivation, and deadline admitted the old capture: 3 behavioral failures | 7 new integration cases; independent review found no substantive issue within this slice |
| Status draft | Independent review found command submission before protocol preflight and insufficient per-rule validity for mixed explicit BUY/risk results | Both paired drafts corrected; second review found no new substantive issue; no protocol implementation claim |
| Explicit risk delivery | Missing module at first collection; independent review then identified original rule/action mismatch returning HOLD rather than SUPPRESS; four normally validated event cases reproduced the mismatch | 50 policy cases, including canonical composite three-valued semantics; independent second review found no remaining material issue |
| Legacy origin proof | 16 missing-module failures; 6 chain-tip regressions; 1 reused-session regression; 7 high-water/activation-cutoff regressions | 45 integration cases; final independent review found no remaining material issue |
| R32 test clock | Original test failed on 2026-09-21; expanded approved/expired-date test gave 1 failed, 1 passed before freezing time | Entire R32 file: 25 passed; independent review confirmed unchanged execution guard and isolated test clock |

Review findings were reconciled against the contracts: explicit event-loop yielding, clear-before-snapshot wake ordering, monotonic maintenance ceiling, single-use ownership, configuration-sensitive requirement revisions, forward-clock retry normalization and abort-without-success were actionable and addressed. Cancellation of the coordinator is not claimed to join provider threads; lifecycle still must await controller cleanup before persistence shutdown. Extra cross-model review was not added, following the user's earlier choice.

Coding child tasks used `gpt-6-astra` / `high`; the protocol draft and independent boundary reviewers used `gpt-6-astra` / `xhigh`. The parent task's active model/effort is not attested by these child settings.

## Executed verification

Run from `trade-plan-monitor`:

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_recovery_coordinator.py tests/unit/test_runtime_reconciliation.py -q --tb=short` | 24 passed |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_coverage.py -q --tb=short` | 20 passed in 2.44 seconds |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_activation_fences.py tests/integration/test_production_semantic_gate.py tests/unit/test_r17_failure_diagnostics.py -q` | Coding agent: 40 passed in 8.31 seconds; one existing Starlette warning |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_recovery_delivery_eligibility.py tests/unit/test_explicit_rules.py tests/unit/test_notification_outbox.py -q` | Coding agent: 120 passed in 0.76 seconds after review fixes; reviewer independently reran all 50 policy cases successfully |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_provenance.py tests/unit/test_notification_outbox.py tests/integration/test_live_monitor_projection_migration.py -q --tb=short` | Coding agent: 112 passed in 7.45 seconds after final review fixes, including 45 new origin cases |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_r32_ai_transient_acceptance.py -q --tb=short` | 25 passed, 1 existing warning, 2.91 seconds after the test-clock correction |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | Existing OpenAPI snapshot and generated frontend types are current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short` | 3006 passed, 5 failed, 1 skipped, 4 live deselected, 1 existing warning; 3002.35 seconds |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Final functional run: 3095 passed, 4 known failures, 1 skipped, 4 live deselected, 1 existing warning; 441.10 seconds |

The full-suite gate is not green. Four failures match the earlier record in `2026-09-21-runtime-recovery-foundations.md`: canonical index-head update time, pending-close index-error reference health, provider TIMEOUT versus TRANSIENT, and the R14 mock payload rejected by the temperature guard. The additional `test_r32_execution_snapshot_detects_config_change` failure was traced to its real-date dependency: both script and test initially matched HEAD, originating in `7df47b78`. The test-only correction subsequently passed its whole file; the full-run counts above remain the actual pre-correction result. No failing test was deleted, skipped or weakened to claim success; the skip is the pre-existing Windows/POSIX ownership boundary.

The full offline run collected before the new explicit-risk policy and legacy-origin test files existed; their 50 and 45 cases are covered by the separately recorded focused runs and the final functional run. That final run includes the R32 clock correction and all current new tests, but does not rerun the unchanged heavy backtest acceptance file that already passed in the full run. All four remaining failures match the pre-existing records; the gate remains blocked. Whitespace checks passed. Paired documents have matching heading counts and technical literals after normalizing translated explanatory placeholders and paired document paths; the four runtime-status fenced JSON examples are identical between languages. The final high-confidence secret-pattern scan covered all 22 changed files and found no match. This is a scoped hygiene check, not a credential audit.

## Changed surfaces

`runtime/reconciliation.py`, `runtime/recovery.py`, `runtime/request_control.py`, `runtime/production.py`, new `notifications/recovery_eligibility.py` and `notifications/recovery_provenance.py`; five new focused test files and the isolated R32 test-clock correction; paired runtime-recovery/runtime-status/local-Web specifications, task index and this report. No generated contract or UI change is hidden in this increment.
