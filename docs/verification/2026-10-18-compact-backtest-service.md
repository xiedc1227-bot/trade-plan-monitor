# Compact backtest service verification — 2026-10-18

Chinese review copy: [2026-10-18-compact-backtest-service.zh-CN.md](2026-10-18-compact-backtest-service.zh-CN.md). Task: [SC-01–SC-03](../../tasks/compact-backtest-service.md).

## SC-V01 — Delivered behavior

Normal backtest routes show one compact service status and the `服务管理` button. The button is keyboard accessible and exposes its expanded state and associated panel. Refresh, pending-job lookup, service stop, update time, explanations and the return link are inside the panel. Faults, unknown controls, stopping/stopped/disabled state and a detected interrupted job expand it. Users can collapse it without changing any service or job state.

The component retains one presentation responsibility; `useBacktestService` owns status/history reads and explicit controls. No new API or execution mechanism is introduced. Once `canRead=true`, and only without a currently authorized job, a bounded list request inspects `QUEUED`, `RUNNING` and `CANCEL_REQUESTED` with `limit=1`. A successful check is reused until `epoch`, `revision`, `generation`, state or `authorizedJobIds` changes. Before readability there is no history scan. A running authorized job does not trigger an interrupted-job prompt.

Passive `SERVICE_UNAVAILABLE` / 503 waits for the existing status poll rather than turning ordinary metadata contention into an expanded fault banner. Other lookup failures and explicit manual failures remain visible. Late history responses must match the current service identity and mounted lifetime; controls abort outstanding lookups. Viewing, expanding or discovering pending history never resumes it. A pending task still needs checkbox confirmation and the explicit resume button. Existing control-body/key replay, physical drain, source unknown-result confirmation and task cancellation guards remain.

## SC-V02 — Automated checks

New regressions first failed against the old always-expanded interface and missing automatic detection. Separate regressions reproduced false expansion on a passive busy response and redundant history scans on every status poll. They passed after the changes.

| Check | Outcome |
| --- | --- |
| Service transport/composable/component suite | 32 passed |
| Full frontend suite | 71 files, 1088 passed |
| Type checking / production build | Passed |
| Focused real Chrome journeys | 3 passed: compact disclosure/keyboard/desktop/mobile/axe; interrupted jobs and service faults without automatic controls; task progress/read refresh/cancel confirmation/same-body-and-key retry while management is collapsed |
| Existing request/DOM/polling/chart bounds | Passed in one recorded run; a later repetition hit the navigation-abort audit described in SC-V04 |
| Production-path integration | `test_mounted_upload_retry_review_worker_and_causal_result_use_only_market_facts`: 1 passed, with the existing Starlette/httpx deprecation warning |
| Existing unknown-extraction cancellation browser case | Passed; navigation, explicit ended confirmation and retained task ownership remain checked |

The full frontend suite still includes task progress, cancellation confirmation, failed reads, unknown cancellation and same-request/key retry cases. No such assertions were removed. The browser contract fixture needed its existing required `Cache-Control: no-store`, the current plan-library read and a valid, canonically sorted unfinished-job page. Existing API/request/layout assertions and time limits were preserved; route navigation waits for preceding network activity to settle.

Logs and captures are local under `data/verification/2026-10-18-compact-service/`: `unit-final.log`, `build-final.log`, `service-browser-focused.log`, `service-browser-final.log`, `production-integration.log`, `production-browser-final.log` and `service-focused-results/`. Provider credentials, local databases and these generated files remain ignored.

## SC-V03 — Actual four-plan result

The actual service at `http://127.0.0.1:8765` loaded the new production assets. The existing four-plan run `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` was read without re-extraction, replay or changing its report. Its profit summary, plan diagnostics and comparisons remain available.

At widths 1440, 390 and 320, the normal service strip measured 60.75 pixels high. Only status and the disclosure remained visible. Enter expanded the management controls and Space collapsed them; the page had no horizontal overflow. No service-control or other write request and no page runtime error occurred. The initial real read reproduced passive metadata contention; it led to the regression in SC-V02, not a hidden service repair. The final check used the corrected build.

Evidence: `actual-browser.json`, `actual-browser-final.log`, `actual-page.txt`, `actual-compact-{width}.png`, `actual-expanded-{width}.png` and `actual-status-{width}.png` under the same local directory. This verifies presentation over the retained actual report; it is not new AI, market-provider or return certification.

## SC-V04 — Remaining verification limits

Broader browser checks are not all green. The existing 320/768/1024/1440 and 200% layout journey reached its strict request-failure audit with navigation-aborted reads. The same journey also failed that audit on an isolated archive of the unchanged `e7ead0c` baseline, using the same corrected contract fixture. A keyboard journey intermittently reported aborted result/detail reads; it passed in the baseline comparison. No request-failure assertion was disabled or reclassified.

The older complete upload/retry/edit/review/run Chrome journey also failed its unchanged 10000 ms candidate-ready checkpoint: the page retained the last extracting state with a read error, while the temporary backend record had already reached `CANDIDATE`. An explicit progress reread did not resolve that run within the same gate. The same failure reproduced with the prior service component/composable on the isolated `e7ead0c` baseline; the corresponding production-path integration passed. This is retained as existing browser/progress-read verification work, not evidence that the full end-to-end suite passed or that this simplification repaired it.

Initial failures remain in `browser.log`, `browser-final.log`, `browser-canonical.log`, `existing-browser.log`, `production-browser.log` and `production-browser-rerun.log`. Baseline outputs remain in `baseline/baseline-browser.log` and `baseline/baseline-production.log`. No capacity test or new actual-source extraction/replay was needed for these interface changes. The [functional acceptance record](2026-10-18-backtest-functional-acceptance.md) retains its baseline and declared limits; this increment does not widen that certification.
