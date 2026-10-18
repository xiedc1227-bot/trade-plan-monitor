# Run-record filter verification — 2026-10-18

Chinese review copy: [2026-10-18-run-record-filters.zh-CN.md](2026-10-18-run-record-filters.zh-CN.md). Task: [RF-01–RF-03](../../tasks/run-record-filters.md).

## RF-V01 — Delivered semantics

Historical first delivery: the advanced/legacy controls below were subsequently removed at the user's request; RF-V05 records the current interface and URL behavior.

The common area contains stock, backtest cutoff dates and pin status. Dataset hash is in advanced filters; the single-plan version ID is in legacy-record lookup, with a warning that it cannot search a continuous chain by one member plan. Active URL conditions and validation errors reveal their panels. Native disclosures remain keyboard accessible. Sorting is a text explanation; the table labels its existing timestamp as result time.

The inclusive dates always compare coverage end `eventEnd`. New `eventEndFrom` / `eventEndTo` accept actual calendar dates in `YYYY-MM-DD`, combine with other filters using AND, execute before SQL pagination and belong to the signed cursor context. The response and frontend independently validate the returned coverage. Invalid dates, reversed intervals and cursor/filter mismatches are rejected. Unused new fields are omitted, retaining old payload/cursor compatibility.

Old `completedFrom` / `completedTo` URLs retain their existing result-time conditions, shown under legacy lookup only when present. They are not converted into coverage dates. For continuous replay, historical `completedAt` is evidence cutoff, not actual task completion. The fixed `completedAt:desc,runId:desc` ordering, retention, immutable reports and hashes remain unchanged; actual job completion is a separate fact. No historical timestamp is fabricated or rewritten.

## RF-V02 — Automated evidence

The initial query regression failed on the missing date contract. A subsequent API failure exposed strict date-string parsing; a dedicated validator now admits only valid calendar dates without relaxing other strict fields. The old fixture's coverage end is 2024-01-05 while its result timestamp is in 2026: the corrected test explicitly queries 2024-01-05, rather than changing the fixture. Frontend regressions prove disclosure state, URL submission/restoration and rejection of response items outside coverage filters. The table accessibility assertion now also checks the explicit non-completion explanation.

| Check | Outcome |
| --- | --- |
| Full frontend suite | 71 files / 1091 passed |
| Type checking / production build | Passed |
| Backend query and run API final recheck | 60 passed |
| Selected backend result/query/API coverage | 128 distinct cases passed across the initial run and corrected recheck; not a claim of one fully green invocation |
| OpenAPI snapshot checks | 14 passed |
| Both generated-contract checks / changed Python lint | Passed |
| Focused Chrome journey | 1 passed: inclusive coverage dates distinct from result time, advanced/legacy disclosures, keyboard, 1440/390/320 layouts, accessibility and existing request audits |

Logs and captures are local under `data/verification/2026-10-18-run-filters/`: `unit-final.log`, `build-final.log`, `http.log`, `openapi.log`, `browser.log` and `browser-results/`. Local generated evidence remains ignored. Existing Starlette/httpx deprecation warnings do not change the result.

## RF-V03 — Actual local-service check

Before restarting the service at `http://127.0.0.1:8765`, the existing control API confirmed no unfinished or authorized jobs and physical drain. The updated service and production assets then served the actual stored results. No extraction, market request, replay or report edit was needed. Browser checks used the visible controls and inspected the actual API responses:

| Conditions | Actual result |
| --- | --- |
| Stock 002240.SZ; cutoff 2026-10-09 through 2026-10-09 | 4 records, all with that coverage end |
| Same stock; cutoff 2026-10-10 through 2026-10-10 | 0 records |
| Restore 2026-10-09; unpinned only | 4 records, all unpinned |
| Add exact four-plan dataset hash | 1 record, the retained four-plan run |
| Add a valid but unrelated legacy version UUID | 0 records; no false chain-member match |
| Clear advanced/legacy conditions | 4 records again |

The retained run is `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2`; its dataset is `b983a206bce80882c2ac2fe10f25acbafb680f36f6f9ffeacd0b111e5b0446b1`. The unmatched legacy UUID was `123e4567-e89b-42d3-a456-426614174000`. All reads returned 200. At 1440, 390 and 320 pixels there was no horizontal overflow, runtime error or browser write request. Desktop and mobile screenshots were inspected. Evidence: `actual-checks.json`, `actual-browser-final.log`, `actual-page.txt` and `actual-filters-{width}.png` in the same local directory.

## RF-V04 — Boundaries

Production CSP correctly blocked inline accessibility-tool injection during the first local check. It was not weakened; the isolated Chrome journey performs the accessibility audit, while the final production check verifies real controls, responses, layout and runtime errors without injection. This does not claim a production-injected accessibility audit.

The whole browser suite and capacity tests were not recertified. Previously reproduced baseline navigation-abort and preparation-progress read failures remain recorded in [SC-V04](2026-10-18-compact-backtest-service.md#sc-v04--remaining-verification-limits); no audit assertion, timeout or acceptance threshold was reduced. This increment covers read-only filtering and presentation, not new AI, market evidence, trading policy or replay correctness. The [functional acceptance record](2026-10-18-backtest-functional-acceptance.md) keeps its original scope.

## RF-V05 — Remove technical lookup conditions

The user requested removing dataset hash and plan version ID from the page entirely. Both inputs and their advanced/legacy entrances are now absent. Common stock, inclusive cutoff dates, pin status and the sort explanation remain. Old `datasetHash` / `planVersionId` page parameters are removed before the first read, together with their bound cursor; page 1 retains the other supported conditions. Valid, invalid and individually present old parameters all have regression coverage. Explicit old timestamp links still show their own time controls, without restoring either removed input. Internal API filters, detail identifiers, frozen records and reports are unchanged.

The removal regressions first failed on the old controls and retained cursor. Final frontend verification passed 71 files / 1094 tests, including 20 run-list cases; type checking, build and the updated focused Chrome journey passed. Keyboard submission, date behavior, accessibility and 1440/390/320 layout checks remain enforced. No backend contract changed in this follow-up.

On the actual production service, a link containing both old identifiers and a cursor was normalized before any list request. It returned 4 unpinned 002240.SZ records for cutoff 2026-10-09, 0 for 2026-10-10 and 4 after restoring the date. No browser list request contained either removed condition or its cursor. A separate direct internal dataset API lookup still returned 1 record. Desktop/mobile screenshots were inspected at 1440, 390 and 320; there was no overflow, runtime error or write request. One earlier attempt encountered a 503 while restoring the date and correctly showed the existing read-error message; the final repeat passed. This does not claim to fix that existing temporary service-read failure.

Evidence under the same local directory: `unit-removal.log`, `build-removal.log`, `browser-removal.log`, `browser-removal-results/`, `removal-actual.json`, `removal-actual.log`, `removal-actual-failure.json` and `removed-filters-{width}.png`. RF-V02–RF-V03 remain the initial delivery evidence; their older test count and now-removed UI controls are not the current page. RF-V04 limits remain in force.
