# Daily plan resume checkpoint

> Scope changed2026-10-02: the user authorized removal of daily broker order/partial/unknown tracking in favor of explicit atomic whole-lot simulation. This document records the prior scope; its completion/test conclusions do not approve the new cleanup. Follow the [current cleanup contract/tasks](2026-10-02-daily-plan-simulation-cleanup.md) and revised canonical specification. Preserve the historical evidence below.

Canonical English; paired review copy: `daily-plan-resume.zh-CN.md`.

## R01. Resumed by user

On 2026-10-01 the user paused work to shut down the computer, then explicitly resumed and revoked the pause. Work is authorized to continue under the narrowed scope below. Local uncommitted changes are preserved; nothing was committed, pushed, deployed, or activated against real data.

## R02. Scope and authority

Implement the complete daily-plan chain in `trade-plan-monitor/`. Read `SPEC-daily-plan.md`, its paired Chinese copy, the capability map, and `tasks/daily-plan-plan.md` / `daily-plan-todo.md`. Original source: `../docs/TradingAgents/reports/新提示词.txt` (relative to the repository); do not modify it or invent its missing strategy parameters. The actual historical plan remains incomplete and unactivated. `suspension_confirmation_policy` remains an explicit per-plan choice with no default.

The resumed scope removes fundamentals entirely from new daily monitoring: user review occurs only when generating the trading plan. Source fundamental/announcement clauses remain non-monitoring background and never create conditions, buy/sell gates, risk triggers, execution blockers or announcement-verification requirements. Do not relabel them as technical human facts. Tradability/suspension evidence remains. Defer index work and preserve all existing index behavior. The original template is unchanged; this explicit user scope supersedes its old three-risk requirement.

Required agent sequence for this revision: incremental contract design `gpt-6-astra/high`, implementation `gpt-6.1-sol/high`, independent fresh-context review `gpt-6-astra/high`, Sol fixes, Astra re-review until findings are resolved. The earlier design/implementation does not count as acceptance of the revised scope. No further stage permission is needed after resumption. Do not send messages to other Codex chats, commit, push, deploy, call live market/AI/notification services, or inspect production data/secrets.

## R03. Saved implementation and evidence

The working tree started clean at `b2572b6`. Changes include Schema 4 daily contracts and validation; `daily-ta-v2`; certified daily/QFQ data admission; durable signals, risk branches, actual fill accounting and additive migration `0024`; production scheduler/runtime/outbox wiring; extraction v7, separate human supplements, review-bound activation; nine new API paths; and `/daily-plans` Vue UI. Old Schema 1/2/3 and prompt v1–v6 remain compatibility boundaries. Many files are untracked: review both `git diff` and untracked contents.

Historical results reported before pause (all predate the scope revision; none certifies the revised implementation):

- Old focused compatibility: 351 passed.
- Daily test glob: 150 passed in 15.79s (includes imported existing fixtures, not 150 independent new cases).
- Independent safety-boundary file: 14 passed; migration compatibility group: 115 passed; OpenAPI snapshot group: 14 passed.
- Frontend: 824 passed; type check passed; build passed before the final display-only additions, whose final rebuild still needs confirmation.
- Real browser journey: 1 passed in 8.9s, with zero console warnings/errors or failed requests. It covers source paste, actual v7 partial extraction, missing technical condition supplementation, separate human evidence, review/activation, CORE 100 / TACTICAL 0, UNKNOWN 100 then verified cancellation, actual fills 40+60, official tradability/fundamental facts causing immediate runtime risk evaluation, expiry and source-edit invalidation.
- Ruff over `src tests`, compileall and diff whitespace checks passed before pause.
- Earlier full run: 5926 passed, 22 failed, 1 skipped, 4 deselected in 3324.78s. Failures were subsequently addressed (migration expectations/OpenAPI); this is NOT a final successful full run.
- A later fast run excluding only `tests/integration/test_backtest_acceptance.py` was stopped at pause and has no final result. Its initial old partial-extraction fixture failure was fixed with `dailyMapping: null` and passed a focused rerun. Rerun after resumption.

Pre-revision generated OpenAPI SHA-256 (historical): `aa19f9a453ddf003fd2faecdd99285e12dc41a149891abf8b35d799c6ee3aedc`; 60 paths = old 51 + new 9. Regenerate/check both contract variants if API changes.

## R04. Resume order and outstanding work

1. Inspect the current working tree without discarding changes. Read this checkpoint, the revised paired specifications and P06/T04. Old agent/process IDs describe the pause checkpoint only; do not assume they remain usable. Finish the Astra incremental contract revision before Sol modifies implementation.
2. Sol high implements P06/T04: narrow unpublished Schema 4/v7 to two technical branches; remove fundamental/announcement facts, runtime/UI/API gates and source-review blockers; preserve exact excluded source spans and technical mixed-clause coverage; update generated contracts and fixtures. Preserve old schemas/prompts/index behavior. Incompatible development drafts retain raw source/audit evidence and require re-extraction/new review, with no automatic conversion or broader migration. The prior review freeze no longer blocks this authorized revision.
3. After revised implementation and focused checks, start a fresh independent Astra high review. The prior `/root/final_review` was interrupted without a verdict; no review approval exists. Check exclusion boundaries (including preview, mixed clauses, nested facts and bulk human supplements), retained technical/tradability behavior, independent-event reuse, risk scope/reassessment, late/revised closes and adjustment basis, source/value binding, send-time quantities/quotes, target completion and API/UI validation. Resolve findings through Sol high and re-review through Astra high.
4. Finish paired README/entry links, task checkboxes and verification report with exact revised DP-A01–DP-A20 test mapping. DP-A15/DP-A19 are now reverse tests proving fundamentals and announcement checks are absent; do not reuse their former positive-risk oracles. Implementation agent had begun documentation but no final daily verification report was confirmed. Never mark planned or interrupted tests passed.
5. Once review fixes are stable, run final complete `.venv/Scripts/python.exe -m pytest -m 'not live' -q`, including `tests/integration/test_backtest_acceptance.py` (heavy capacity cases; earlier full run about 55 minutes). Do not weaken skips, assertions, thresholds or markers. Run appropriate frontend/type/build/browser and generated-contract checks after relevant changes, and document actual results.
6. Recheck English/Chinese parity and provide a concise final Chinese report. No live-provider certification or actual-plan approval is implied by offline synthetic fixtures.

## R05. Local evidence locations

Browser screenshots are in `C:/Users/xiedc/AppData/Local/Temp/trade-plan-monitor-playwright-results/daily-plan-daily-user-revi-e730d--and-expiry-use-real-SQLite-chrome/`: `daily-current.png`, `daily-review.png`, `daily-official-risk.png`. Temporary artifacts may disappear after shutdown; rerun the browser test if needed.

At the pause checkpoint, both active agents were interrupted and the task's fast pytest processes were identified for termination; existing user application and editor processes were left alone. This is historical process information, not a current pause. Old tool session IDs are not reliable after shutdown.

## R06. Frozen implementation after resumed review

The 2026-10-01 scope revision and complete chain are implemented. Fresh Astra/high review closed F1–F11 after Sol/high fixes and independent rechecks, including the actual sparse-calendar production recovery (1500-day request, 1044 runtime dates, 500 certified bars). Source is frozen; do not restart development from R03/R04 or assume their old verdict/process state remains current. The unchanged original template is a missing-parameter negative case, not an activated plan.

Current evidence is in [verification](../docs/verification/2026-10-01-daily-plan.md) and the [independent review](../docs/verification/2026-10-01-daily-plan-independent-review.md). Fresh focused results: compatibility 351/3.75s, daily-unit290/5.14s, critical group 88/23.55s, accounting 2/0.99s, OpenAPI 14/8.80s; overlapping groups are not new-case counts. Latest coordinator frontend:60 files/828 passed/6.55s, type check and both builds. Both real Chrome journeys passed. Ruff, compileall and both generated checks passed. Public SHA-256:v1 `69109c2620cca5c6467753a459e9c033faaa22862d7f68ba8dec19b8c717220b`, v2 `027cafb61579a33e006bcf5874524c54e976715e166d6eea6029a5503513f484`.

Final complete offline backend result: **6065 passed, 1 skipped, 4 deselected, 1 warning in 3208.19s (0:53:28), exit 0**, command `.venv/Scripts/python.exe -m pytest -m 'not live' -q`; log `$env:TEMP/daily-plan-final-backend.log`. The only warning is the existing StarletteDeprecationWarning. Afterward `tests/integration/test_daily_sparse_calendar_regression.py` separately passed 1 test/5.94s with Ruff; it was not collected in the 6065 full run. DPT09/C4 and the final T04 row are checked; paired documentation is complete. No live call, production-secret/database read, commit, push, deployment or original-plan approval was performed. This work is complete; do not resume old fast process IDs or repeat the full run without a new change or failure.

## R07. Current simulation cleanup checkpoint

The authorized 2026-10-02 cleanup supersedes broker accounting in the R03–R06 historical records. The current implementation uses isolated aggregate POSITION/SIMULATION records, fixed 100-share whole transactions, current authority fences and no shared real-position synchronization. C1–C7 are independently closed. Current focused daily coverage passed 229 tests/53.08s; the final safe single-field/aggregate transport bound and model group passed 8 tests/1.56s. OpenAPI checks passed 14 tests/8.94s after current path/summary expectations and bilingual fingerprints were updated. These overlapping groups are not added test counts.

Latest frontend after the final parser and schema: 62 files, 865 passed/6.21s; type check and standard/runtime-status-preview/legacy-test builds passed; real Chrome source/reload and full-simulation journeys passed 2 tests/14.0s with no console errors or failed requests. Both generated contracts are current; v1 `fd241fa2d7d804ca66ed8277014720795b47044fb143e3076146a5b8a81e80f5`, v2 `6216e2992e10532d3d83989ab1a3cebf61d78e2b36deb7bb3d728a190a709f99`. The coordinator completed the current coverage gate: first full6081 passed/1 failed/1 skipped/4 deselected/1 warning in3279.22s; a strict three-line test-only contract correction passed160 targeted tests; final non-capacity recheck6074 passed/1 skipped/4 deselected/1 warning in1204.62s, with the eight unchanged capacity tests already passed in the full run. See [final verification](../docs/verification/2026-10-02-daily-simulation-cleanup.md). Do not reuse R06's6065 or call these two runs a single full green run. Business source is frozen pending a genuine new finding.
