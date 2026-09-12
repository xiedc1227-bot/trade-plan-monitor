# R01 follow-up handoff: alert active-plan return contract

Date: 2026-09-12 (Asia/Shanghai). Canonical English; `R01-followup.zh-CN.md` is the semantically equivalent Chinese review copy. Task: `01a09521-cfc7-7921-922c-c5d848d5ba29`; coordinating task: `01a093fc-f8d3-73d1-b759-ad76c7451697`.

## Completion and commits

The authorized R01 regression follow-up is complete within the reminder active-plan query contract. It is a necessary correction to the existing validity enforcement, not a new product capability and not R09 work.

- Baseline: `main/b16523723c6cd4e1acc90c13f61fce1094706289`.
- Implementation and regression commit: `2f0b1b407faac80574e0752b311b07e06984e78f`, `fix: 修复提醒活动计划返回契约`.
- This bilingual handoff is a subsequent documentation-only commit. Its identity is the commit containing this pair, resolvable with `git log -1 --format=%H -- remediation/handoffs/R01-followup.md`; no circular self-hash is embedded.

The implementation commit changes exactly:

1. `src/trade_plan_monitor/notifications/outbox.py`
2. `tests/integration/test_notification_delivery.py`
3. `tests/integration/test_alert_production_composition.py`

This handoff commit adds only this file and `remediation/handoffs/R01-followup.zh-CN.md`. No specification was changed because the repair restores the already documented R01 contract rather than changing it.

## Root cause and corrected behavior

`AlertOutbox._active_plan_for_event` declares `TradePlan | None`, while R01 commit `099e41e119d9bca05b7cbf6834a696e0b1a9b6ed` introduced `False` returns for both “no active-plan row” and “active identity does not match the retained alert.” Both public consumers test only for `None`; therefore `False` passed the guard and `.activation` raised `AttributeError` in the real `GET /api/v1/alerts` composition and in delivery policy checks.

The two normal absence branches now return `None`, matching the declared boundary. Consequently:

- an alert with no active plan is retained but is neither currently actionable nor deliverable;
- an alert whose immutable plan identity has been replaced is retained as historical, with `currentActionable=false`, and is neither actionable nor deliverable;
- a currently active target-date-valid plan remains actionable and deliverable, including both inclusive endpoints of the existing date-range policy;
- an expired ordinary queued alert remains retained but cannot be sent;
- the bounded historical exception remains unchanged: a cross-day-created `RISK_BREACH` is deliverable only when its original target trading date was eligible;
- malformed active-plan JSON or a payload/hash inconsistency still raises `OutboxStorageError`; no exception was swallowed and no permissive fallback was added.

Alert queries and acknowledgements do not modify positions. The existing atomic acknowledgement/position-isolation regression remained green.

## RED and GREEN evidence

All commands used `.venv/Scripts/python.exe -B`, isolated temporary SQLite/configuration, fake providers or local TestClient, and `-p no:cacheprovider`.

- Existing production-composition RED: the focused `GET /api/v1/alerts` regression failed with `AttributeError: 'bool' object has no attribute 'activation'`: `1 failed, 1 warning in 1.79s`.
- Added regression RED: missing and replaced plans across both public policy methods plus missing/replaced alert-query paths: `6 failed, 1 warning in 2.40s`.
- Minimal-fix GREEN for those six cases: `6 passed, 1 warning in 1.72s`.
- Final notification-delivery and production alert-composition files: `40 passed, 1 warning in 4.42s`. This includes valid/expired/current delivery boundaries, the historical official-close risk exception, malformed plan storage, acknowledgement isolation and the real alert query composition.
- R01 production-validity integration files (`test_live_pipeline_acceptance.py`, `test_ten_symbol_runtime.py`): `67 passed in 21.41s`.
- Plan-domain validity policy: `148 passed in 0.20s`.
- Ruff lint passed for all three implementation files. `git diff --check` passed. Format-only checking reports existing baseline formatting differences outside the new hunks in `outbox.py` and `test_alert_production_composition.py`; they were not rewritten. The newly expanded `test_notification_delivery.py` is formatter-clean.

The RED record is `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a09521-cfc7-7921-922c-c5d848d5ba29/R01-followup-red.md`.

## Complete offline backend result and unrelated failures

After inspecting the test boundary, the full command `.venv/Scripts/python.exe -B -m pytest -m "not live" -q -p no:cacheprovider` completed in 39 minutes 17 seconds with:

- `2390 passed`
- `1 skipped` (the platform-specific POSIX-owner case on Windows)
- `4 deselected` (the explicitly authorized live Tushare/AI contract tests)
- `2 failed`

The two failures are unrelated pre-existing R07 OpenAPI gate omissions and were reproduced alone as `2 failed in 1.99s`:

1. `test_openapi_change_requires_bilingual_spec_approval`: generated digest `fe3305aaf31db3eb8314675ab74790b40fc6e3ea08f44f69679127434bb001e3` is absent from the local-Web bilingual specification.
2. `test_openapi_contains_only_approved_paths_and_public_error_schemas`: R07 routes `/api/v1/manual-event-risk` and `/api/v1/manual-event-risk-confirmations` are absent from `APPROVED_PATHS`.

Both routes and their OpenAPI output originate from R07 commit `beff0410150813e64a242a3821a299090d963e9b`; this follow-up changes no router, generated contract, OpenAPI snapshot, or local-Web specification. R07's broader `pytest -x` stopped earlier at the R01 alert regression repaired here, so these later gate failures were not exposed in that handoff. They remain for the coordinator to schedule; this narrowly authorized task did not expand into an unrelated OpenAPI repair. Therefore the focused R01 follow-up is green, but the whole backend is not claimed fully green.

The two slowest offline capacity nodes also completed successfully. The ten-symbol/252-day node took about 23 minutes versus the recorded historical 25.2 minutes; the traced-heap node took about 10 minutes versus the recorded historical 12.0 minutes. No real AI, market-data quota, external notification, broker/trading call, production database, real plan/position, configuration, or credential was used.

## Workspace preservation and review

The twelve user-owned modified files retained their exact starting bytes; the ordered path/SHA-256 manifest at final recheck is `00ac48879c89c722f538e88e84e1d6dccb82b2860fd08252199164a6a934eee7`. The four R00 untracked documents also retained exact bytes and remain untracked; their manifest is `f52aeaf1269d09a3f9807de2c5ae18faff06b3f5577a5f2aee1ee1f0cf88e408`. No stash, reset, checkout, push, release, real-data write, or unrelated staging occurred.

Five-axis review found no correctness, security, architecture, performance, or readability blocker in the repair. It adds no dependency or query, preserves explicit corrupt-storage failures, and confines behavior to the declared optional return boundary. The larger test diff is deliberate behavioral coverage, not production complexity.

## Next step

The coordinating task owns successor creation under the explicit completion-callback protocol. After verifying this handoff and the implementation commit, it may start the already approved R09 task with `gpt-5.6-sol` / `high`. This worker creates no successor. R09 must reread the actual HEAD/workspace, R08's bounded explicit-plan design and this pair before implementation. The unrelated R07 OpenAPI gate omissions remain visible and must not be mistaken for an R09 semantic change. R14 real calls still require separate bounded authorization.
