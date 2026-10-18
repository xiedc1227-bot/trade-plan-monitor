# Per-plan result-page diagnostics (2026-10-17)

## RD-V01. Change and evidence boundary

Implemented [RD01–RD03](../../tasks/result-plan-diagnostics.md) and U18. Completed single/scheduled monitoring-loop summaries now include a read-only “逐份计划成交诊断” section. Each source shows effective date, fill count, automatic root-outcome counts, review/processing status, separate reason categories and actual-versus-required evidence. Unknown qualitative criteria remain visible without adding confirmation controls. No-buy-authority and execution/data limitations are distinct from market rejection. Desktop tables become labelled vertical comparisons at 320 px.

The optional `planDiagnostics` projection reads the original frozen reviewed versions and retained result-owned audit in one transaction. Each row/event and the exact published event-set digest must match. It does not run AI, reread changing market data, approve unknown conditions, change execution, or rewrite reports. Counts cover all retained evaluations; examples merge repeated daily criteria and exclude stale daily repetitions. Each plan has at most eight examples, with at most 256 overall, and truncation is explicit. Expired detail preserves source identities but uses null fill counts and no invented reasons. Failed preparations do not become members of a completed run.

Fixed two frontend contract mismatches exposed by the actual result: legitimate `POSITION_LIMIT_ONLY` cash was rejected, and independently reviewed library members with null `baseHash` were incorrectly required to reference the preceding extraction. Non-null predecessor matching remains enforced. Both generated OpenAPI/TypeScript profiles and bilingual contract documents are synchronized.

## RD-V02. Four actual plans

The formal local result API reads completed run `92edcbaa73bf9e445834b2c5ef5a22a4da4499d82c76fa412e05b92e62bb84d1`; report hash remains `81ef60f0279f9346a835dff69e11f1ccf3c430e0fdea40be6202bc959ffc1423`. This is a projection of the previous completed actual-data run, not a new AI call or replay. The run still has 1,468 evaluations, three replacements and zero fills.

| Source | Result-page evidence |
| --- | --- |
| 2026-09-24 | Close 25.69 versus required above 26.70; the 26.62 → 25.69 sequence fails the nondeclining alternative. Separate unresolved candle and volume definitions. |
| 2026-09-28 | No direct buy authority; latest observed prices 24.44 and 25.05 are retained. The midnight missing-basis evaluation is labelled at its own time, not treated as an extraction defect or an all-session outage. |
| 2026-09-30 | Prior recovery threshold 25.99; prior close 25.01 and later current quote 25.14 are distinct. Retest/volume/index ambiguity is separate. |
| 2026-10-09 | Prior recovery above 25.99 has not occurred; latest observed quote 25.35 is explicitly not prior-close confirmation. First/second-tranche qualitative requirements remain separate. |

Automatic buy-rule root counts (unmet / missing / satisfied) are 245 / 0 / 0, 0 / 0 / 0, 491 / 1 / 0, and 243 / 243 / 0. These include repeated evaluation times and multiple rules, not distinct trading days or fills. The first source's later nontrading-day repetitions remain in counts but do not duplicate its closing-price examples. All four versions were reviewed; none records an extraction/validation blocker. The UI does not imply that this proves all qualitative policy definitions are complete.

The result response measured 14,715 bytes and 10.272 seconds in the isolated local formal-API check, including existing frozen-input/report verification. No maximum-capacity latency certification is claimed. The production frontend decoder accepts the exported response. Artifacts are in `data/verification/2026-10-17-result-diagnostics/`: `verify_actual.py`, `actual-result.json`, `summary.json`, test logs and desktop/mobile screenshots. `web/tests/fixtures/four-plan-diagnostics.json` retains the public response for regression/browser tests, without raw originals or credentials.

## RD-V03. Verification

- Full backend unit pass: 3,214 tests. Final focused diagnostics pass: 10 tests, including added observation-mode and unsupported-condition cases.
- Result API/publication/retention checks: 45 passed in the combined run; the new missing-audit test initially expected the later digest exception, while the existing availability-count guard correctly rejected the missing row earlier. Its assertion was corrected to that explicit guard and the test passed independently. Thus all 46 selected checks passed across these runs; no production integrity guard was weakened.
- OpenAPI contract checks: 14 passed; both generated profiles are current. Total selected integration checks: 60.
- Frontend: 1,060 tests passed; TypeScript check and production build passed. Actual-result decoder, all four source cards, exact prices, missing legacy projection, expired detail, processing category, source/version identity and unsafe counts are covered.
- Isolated real Chrome: actual exported response through the production API decoder and result route, four cards, 1440/320 px layouts without document overflow, visible mobile actual-price column, no input/confirmation controls, expandable audit identifiers and no page errors. Scoped WCAG 2.1 A/AA axe check found no violations. Browser transport serves the recorded formal-API response; it does not imply a live backend browser run or new provider calls.
- Focused Ruff and generated-contract checks passed. Retained audit corruption is rejected; immutable report hashes remain unchanged. No commit, deployment or production-service restart was performed.

## RD-V04. Use and limits

Restart the updated service and refresh a completed result. No re-extraction or new backtest is required to obtain this section while its audit details remain available. The section explains that run's frozen rules; older runs cannot silently adopt later extraction fixes. A new rule interpretation still requires new review and a new run. An unavailable diagnostic response has an explicit fallback instead of invented zero-fill reasons. Full available evidence remains accessible through the existing details tab.

## RD-V05. Live local service follow-up

At the user's subsequent request, restarted the installed application at `http://127.0.0.1:8765` with its existing `config/app.yaml`. The local web result store had no runs; the real four-plan result previously existed only in the verification store. Backed up the web result database using SQLite backup, then copied the frozen input through `record_loop_input`, validated the 2,956 original audit events through `stage_loop_report`, and published through `verify_job_publication` / `publish_verified_publication`. Existing databases were not replaced. The run ID and report hash in RD-V02 remain unchanged; no fresh AI call, market download, or replay was performed.

Opened `/backtests/92edcbaa73bf9e445834b2c5ef5a22a4da4499d82c76fa412e05b92e62bb84d1?tab=summary` in the user's Chrome against the actual service and packaged production assets, without response interception. An initial request during lazy service preparation returned 503; after the service reported readable history, the page's explicit retry loaded successfully. A separate live HTTP result read returned all four diagnostics in 10.11 seconds with the original report hash.

Visually inspected all four cards and their actual/required columns. The first shows 25.69 versus above 26.70 and 26.62 → 25.69; the second shows no direct buy authority with 24.44 / 25.05; the third distinguishes prior close 25.01 from current quote 25.14 against 25.99; the fourth shows current quote 25.35, explicitly not prior-close confirmation, against above 25.99. All four show no recorded extraction/validation blockage. Qualitative uncertainty and midnight-only basis unavailability remain separate; no manual-confirmation fields appear. Expanded the fourth card's audit references successfully. Saved `live-first-plan.png` through `live-fourth-plan.png`, `live-result.json`, and `web-publication.json` in the evidence directory. Service remains running and the real result page remains open. This live check supplements the isolated browser test in RD-V03.

## RD-V06. Second-plan cancellation versus inheritance

Rechecked the first two original files against the input actually frozen in the web result store. Source 1 lines 37–40 authorize a first 100-share entry after stabilization and close above 26.70, but also cancel the left-side low-buy plan after a close below 25.99. Source 2 lines 3 and 33 explicitly cancel the old 26.40–26.70 low-buy plan; line 34 says a recovery of 25.99 still does not permit an immediate purchase; line 35 requires re-establishing a zone and evaluating the first 100 shares. That final statement is an observation/reassessment instruction, not automatic restoration of the old entry authority.

The published frozen first version contains one 100-share BUY rule; the second contains no ordinary BUY rules, a null low-buy zone, a 26.40–26.70 pressure zone, maximum 300 shares and the ordinary risk branch. Its reviewed mapping binds both explicit cancellation clauses to the null low-buy zone. The second version was independently reviewed (`base_hash=null`, empty change list), so this historical result does not prove that an AI successor extraction inherited and revoked the first rule. Nevertheless, direct comparison with the predecessor and current source confirms that restoring that particular BUY rule would contradict the second source. No missing-buy inheritance fix or report rewrite is warranted. This finding does not assert that every observation instruction became an executable alert.

The frozen source text preserves each original and appends previously resolved source evidence (first maximum position and second ordinary-exit scope); those supplements do not supply or change the cancellation conclusion. Ran `tests/unit/test_unified_preparation_updates.py`, `tests/unit/test_preparation_source_resolution.py`, and `tests/unit/test_loop_diagnostics.py`: 69 passed. Coverage includes explicit natural-language cancellation, exact predecessor-zone matching, wrong-side/ambiguous cancellation rejection, unchanged-rule retention, and no-buy diagnostics. No AI call, new replay, or service restart was needed for this read-only audit. The report hash in RD-V02 is unchanged.
