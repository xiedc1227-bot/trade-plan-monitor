# R00 remediation baseline and acceptance-oracle index

Date: 2026-09-12 (Asia/Shanghai). This is the canonical English baseline. `baseline.zh-CN.md` is the semantically equivalent Chinese review copy.

## Scope and provenance

- Repository: `D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor`.
- Rechecked branch and HEAD: `main` / `bcea43f9cdd28a7fee45cdb4db10cf63e6bbac34`.
- This R00 record adds documentation only. It does not alter business logic, plans, holdings, databases, credentials, providers, notifications, or trading behavior.
- Inputs are the immutable acceptance artifacts at `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a093fc-f8d3-73d1-b759-ad76c7451697/business-acceptance/`: `acceptance-report.md`, `scope.json`, `verification-record.json`, and `remediation/tasks/{plan,todo}.md` plus their Chinese counterparts.
- Historical acceptance evidence is an oracle and defect characterization, not a pass for this rechecked workspace version.

## Pre-existing working tree

The following twelve modified files were present before R00 and remain user-owned: `config/app.example.yaml`; `docs/specifications/monitoring/SPEC-ai-plan-drafting.md`; `docs/specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md`; `src/trade_plan_monitor/config.py`; `tests/unit/test_config.py`; `web/src/components/market-index/MarketIndexSparkline.vue`; `web/src/components/market-index/marketIndexChartOptions.ts`; `web/src/layouts/AppShell.vue`; `web/tests/e2e/accessibility.spec.ts`; `web/tests/e2e/dashboard.spec.ts`; `web/tests/unit/AppShell.spec.ts`; and `web/tests/unit/marketIndexChartOptions.spec.ts`.

R00 rechecked all fifteen important-file SHA-256 values in `scope.json`; each matched. No original changed file was overwritten, reset, staged, or included as a remediation change.

## Offline reproduction boundary

`ai-review-probes.py` and `market-review-probes.py` were inspected before execution and rerun with `PYTHONDONTWRITEBYTECODE=1` and `.venv\\Scripts\\python.exe -B`. They use `TemporaryDirectory`, fake AI/SDKs, virtual time, and synthetic/sample data. They neither read production configuration nor call AI, market, webhook, or trading services. Their temporary SQLite databases are removed on exit. The Playwright B1/B2 defect probes were inspected but not rerun because the two Python probes provide the focused R00 confirmation; their historical result remains defect evidence only.

## Finding-to-evidence map

| Finding | Acceptance oracle / reproduction | R00 result and successor focus |
|---|---|---|
| F01 P0 expired plans act | M2 in `market-review-probes.py`: 2026-09-01 end date still produces `BUY_CORE_READY` quantity 100 and persistent `RISK_BREACH` on 2026-09-08 | Reconfirmed offline; R01 must enforce eligibility at selection, context, and commit. |
| F02 alert recovery misses display | B1/B2 Chromium counterexamples: `snapshot -> alert` and `snapshot.required` advance to LIVE without an alert refresh | Historical isolated browser evidence retained; R02 owns regression conversion. |
| F03 review can be bypassed | A1: semantically unsupported fake extraction saves with omitted issues and activates | Reconfirmed offline; R04 owns server-side provenance and review binding. |
| F04 edits retain approval | A2: changing low price 6300 to 6200 retains resolved review and activation eligibility | Reconfirmed offline; R05 owns invalidation by content hash. |
| F05 manual risk is unresolvable | M1: `False` permits `BUY_CORE_READY`; `None` yields `BLOCKED_DATA` before and after restart | Reconfirmed offline; R07 owns persistent, scoped manual input. |
| F06 plan-expression gap | S01/S04 require arithmetic mean of five completed bars, five-minute risk, explicit actions/quantities/repetition; current contract cannot encode them faithfully | Not repaired or reinterpreted; R08 defines the contract, R09/R10 implement it. |
| F07 ANY gains hidden blocker | M3: a satisfied price alternative plus an unsatisfied volume alternative still yields `BLOCKED_RISK` / `BEARISH_VOLUME_EXPANSION` | Reconfirmed offline; R06 owns explicit mandatory blockers only. |
| F08 ordinary correction requires JSON | Static evidence: nine JSON textareas and incomplete execution preview | No UX change; R12 owns ordinary forms and complete preview. |
| F09 prompt contract drift | A3/current unit oracle: v2 SHA-256 `795a3d...1fe9`; removing only `399107.SZ` in memory restores `6d9ba...27daf` | Reconfirmed offline; R03 owns explicit prompt/schema versioning. |

## Scenario oracle map

| Scenario | Immutable expected business meaning | Baseline status |
|---|---|---|
| S01 | Completed five-minute close in [9.80,10.00] AND current volume >= 1.5 x arithmetic mean of preceding five completed bars -> buy 100 | Not executable faithfully (F06); do not substitute median. |
| S02 | Both price endpoints are inclusive; exact 1.5 ratio is accepted | Existing components confirm inclusive ranges and equality only; not mean-volume support. |
| S03 | Incomplete five-minute bars do not trigger a completed-bar reminder | Historical offline component/integration evidence; retain as regression oracle. |
| S04 | [10.80,11.00] -> sell 100; completed five-minute close < 9.50 -> risk | Not executable faithfully (F06); do not substitute TACTICAL or daily-close behavior. |
| S05 | Ambiguous wording must not invent parameters | F03 A1 fails closedness; real-model semantic accuracy remains unverified. |
| S06 | AI failure, malformed output, and material omissions do not activate or damage active plan | Partial historical offline coverage; F03 leaves a review-bypass gap. |
| S07 | Stale, unordered, duplicate, disconnected, or partial data does not fabricate a signal | Partial historical offline coverage; F02 leaves browser-recovery gap. |
| S08 | Retries/restart deduplicate; acknowledgement never changes actual holding | Historical offline/browser evidence; external delivery is at-least-once, not recipient exactly-once. |
| S09 | Updates, disablement, or expiry stop new actionable alerts | F01 re-confirmed failure; queued-old-alert presentation remains unconfirmed. |

## R00 acceptance status

R00-A is complete: the actual baseline, user-owned modifications, defect evidence, scenario oracles, and offline boundary are indexed without changing business behavior. The source checklist under the external acceptance artifact is intentionally preserved; this local record is the executable-chain completion evidence. No F01-F09 remediation is claimed complete.
