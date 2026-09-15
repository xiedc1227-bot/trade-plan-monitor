# R21 reference-transient diagnosis and fail-stop remediation

Canonical English; `R21-reference-transient-remediation.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_PASS / HISTORICAL_REMOTE_CAUSE_UNPROVED / PROGRAMMATIC_FAIL_STOP_FIXED / LIVE_NOT_AUTHORIZED**.

## 1. Scope and preserved evidence

R21 was offline only. It did not call Tushare, DeepSeek, a balance/model-list endpoint, a webhook, a broker, or any other external service. It did not change the real plan, holdings, credentials, `config/app.yaml`, either preserved database, the R20 claim, or any earlier evidence.

The immutable R20 facts remain: the session was claimed at `2026-09-15T10:40:25.420+08:00`; exactly one `trade_cal` physical start returned `REFERENCE_TRANSIENT`; AI and every other market endpoint remained at zero; the isolated business tables remained empty; an external safety stop released port 18766 no later than `10:43:05.864+08:00`. The port being closed proves only that the listener ended. It does not prove graceful shutdown. There is no R20 `audit.json`; the preserved `termination.json` truthfully records `EXTERNAL_SAFE_STOP` and incomplete normal cleanup.

Preserved artifact SHA-256 values used in this review are:

- R18 `audit.json`: `7EA21447A5280B8D839FCB280FA24BB88856532E5B8391D219180B54B8EA48FF`.
- R20 `termination.json`: `80A2761AFE8504339B978A05E1E70B803069E2822C013C096B2A725768D93287`.
- R18 isolated database: `2C09E29F86EC48DE9A73059497E4D4E2B44C562985B76DE141E0584F65C5C9F7`.
- R20 isolated database: `541C241DE35D1E3CCDA2CD53E415D2E469838B5E9821507D0388270A31099159`.

Read-only counts reconfirmed 399 R18 calendar rows and zero R20 calendar rows. Both databases had zero plan sources/versions/extraction reviews/activation states, positions, minute/five-minute bars, evaluations, alerts, and delivery attempts except for R18's calendar rows.

## 2. Actual calendar call chain

The R20 path was:

| Layer | File and function | Relevant behavior |
| --- | --- | --- |
| Authorized launcher | `scripts/r20_bounded_acceptance.py:119-120` | Selects the R20 bounded lifecycle; the claim and authorization remain consumed. |
| Shared bounded server | `scripts/r14_bounded_acceptance.py:672` | Owns the loopback listener, physical budgets, cleanup, and audit. |
| Web lifespan | `src/trade_plan_monitor/web/lifespan.py:119` | Starts the monitor runtime before exposing the AI and plan services. |
| Startup orchestration | `src/trade_plan_monitor/runtime/service.py:2778` | Calls reference refresh first; a caught reference error makes ordinary production degraded/read-only rather than terminal. |
| Reference health boundary | `src/trade_plan_monitor/web/monitor_composition.py:532` | Maps request, missing-data, and storage failures to sanitized `REFERENCE_*` codes. |
| Production reference refresh | `src/trade_plan_monitor/runtime/production.py:398` | Always requests SSE from `trade_date - 366 days` through `trade_date + 32 days`, verifies the current date, then persists rows. Empty plan state does not skip this calendar request. |
| Request controller | `src/trade_plan_monitor/runtime/request_control.py:538` | Admits one live request, applies its 15-second controller timeout and zero in-cycle retries, then maps adapter errors. |
| Tushare adapter | `src/trade_plan_monitor/market_data/tushare.py:330`, `:553`, `:589` | Calls `trade_cal`, validates the frame, normalizes rows, and sanitizes provider exceptions. |
| SDK/direct HTTPS transport | `src/trade_plan_monitor/market_data/tushare_client.py:37`, `:51` | With configured `connect_ip`, connects directly to that literal address while retaining the endpoint hostname for SNI, certificate assertion, and `Host`; requires CA validation, disables urllib3 retries and redirects, and does not use an environment proxy. |

The current configuration was inspected only through safe fields. Its SHA-256 is `89923ea019712573B0F8118164EDA1EE2A8371C4EE57FAF2A2AD48FD6B8AB428` (case-insensitive). The market host is `api.quicksync.cn`; a `connect_ip` is present with SHA-256 `8d1ba852627d0eade60ccdabd94e5bbc0f7b2e6d6163dad1b3511e25a8bf171a`; the configured transport timeout is 30 seconds; Tushare SDK is 1.4.29. No R18/R20 per-run configuration or `connect_ip` hash was preserved, so the current hash cannot prove byte-for-byte configuration identity at either historical start.

## 3. Confirmed defect and historical evidence boundary

The confirmed classification defect was that the direct client converted an urllib3 timeout to `requests.Timeout`, but `TushareMarketDataProvider._safe_provider_error` then grouped both `requests.Timeout` and `requests.ConnectionError` into `TushareErrorCode.TRANSIENT`. Consequently, the controller's existing `TIMEOUT` branch was unreachable through the real provider adapter. TLS and other urllib3 connection failures were also both represented as connection errors. Separately, HTTP 408/5xx and provider application messages containing bounded transient markers also mapped to `TRANSIENT`.

Therefore R20's preserved `REFERENCE_TRANSIENT` proves that the failure occurred before usable calendar data, date-window validation, or persistence, but it does not distinguish among:

- transport timeout;
- TLS failure or direct-IP connection failure;
- HTTP 408/5xx;
- a provider application status classified as transient.

R18 succeeded earlier the same day with 399 rows. The market adapter, direct client, request controller, and reference composition had no code change between R18 commit `c74a718` and R20 commit `4f62110`; R20 changes in that interval were launcher/AI-contract work. This makes an intermittent external condition reasonable to suspect, but it does not identify which external condition occurred. The earlier success cannot be reused as R20 success.

Calendar date availability, response normalization, and SQLite persistence are not reasonable explanations for the preserved `REFERENCE_TRANSIENT`: after R17 those stages have distinct `REFERENCE_DATA_UNAVAILABLE`, `REFERENCE_INVALID_RESPONSE`, and `REFERENCE_STORAGE_ERROR` categories. They remain generally possible failure stages, but the R20 code is not evidence that one of them failed.

## 4. Remediation

- `TushareErrorCode.TIMEOUT` now survives the adapter and reaches `RequestControlErrorCode.TIMEOUT`, so health reports `REFERENCE_TIMEOUT` for a real provider timeout.
- Fixed `TushareFailureKind` values distinguish `TRANSPORT_TIMEOUT`, `TRANSPORT_TLS`, `TRANSPORT_CONNECTION`, `HTTP_STATUS`, `PROVIDER_STATUS`, `RESPONSE_DECODE`, `RESPONSE_SCHEMA`, `DOMAIN_VALIDATION`, and `UNCLASSIFIED`. HTTP metadata is restricted to `HTTP_3XX`, `HTTP_4XX`, or `HTTP_5XX`. No raw exception, remote message, response body, header, query string, token, or source text is retained.
- The R20 policy now opts into programmatic stop at the first `trade_cal` physical failure and at the higher reference boundary. The higher hook also catches successful-HTTP response/domain failures, missing current-date data, and storage failures. Ordinary production and historical launch defaults do not opt in and keep their existing recovery behavior.
- One shared stop event closes both AI and market admission. After the first reference failure, later AI, concurrent/queued market work, and background retries are denied before another physical start. The live controller remains zero-retry; no global production retry policy was changed.
- `physical-attempts.json` is atomically updated before each allowed physical start. It contains only proposal/run IDs, fixed caps/counters, stop state, the first bounded market failure, and the sanitized reference code. If journal persistence fails, the admission is rolled back and denied before network. A normal cleanup atomically writes `audit.json`, deactivates any isolated test plan, closes the listener, restores the provider factory, and then marks `normalAuditPresent=true` in the journal.
- A forced process kill, power loss, or OS failure can still prevent normal cleanup and `audit.json`; no userspace implementation can guarantee a final write after such termination. The pre-call journal makes the already-admitted physical count recoverable and explicitly leaves `normalAuditPresent=false`; it does not relabel a hard stop as graceful.

The observability questions are deliberately narrow: whether a physical call started, which bounded layer failed, whether all later admission stopped, and whether normal cleanup completed. The journal and final audit answer those questions without a new general logging framework or high-cardinality data.

## 5. Offline verification

Regression tests first failed on the missing timeout classification, missing R20 failure-stop policy, missing durable journal, incorrect success exit code after reference failure, and journal-write failure behavior. The final checks were:

| Check | Result |
| --- | --- |
| Focused diagnostic and R20 tests | 57 passed; one pre-existing Starlette/httpx deprecation warning |
| Production composition, lifecycle, Tushare contracts, R14 wiring, and R20 fail-stop selection with `-m "not live"` | 252 passed; one pre-existing Starlette/httpx deprecation warning |
| Targeted Ruff check | Passed |
| `git diff --check` | Passed; only Git's existing LF-to-CRLF worktree notices |

The induced launcher test starts one simulated calendar request, returns a sanitized timeout, verifies AI 0 and market `trade_cal=1` with every other endpoint zero, observes programmatic server exit, confirms isolated-plan state `INACTIVE`, writes a `REFERENCE_FAILED` audit with `REFERENCE_TIMEOUT`, and marks the journal's normal audit present. Separate tests cover TLS, connection, HTTP status family, provider status, response decode/schema, calendar-domain, storage, concurrent admission stop, journal-write denial, and successful historical production wiring. These are controlled offline proofs, not evidence that Tushare is currently available.

The real ignored `config/app.yaml` hash remains `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428` after verification. No real configuration or database was modified.

## 6. Next separately authorized live step

No new candidate, claim, time gate, automation, or external-call authorization was created in R21. The recommended staged option is one fresh, isolated calendar diagnostic candidate after preparation is complete and a morning date is agreed:

- exactly one `trade_cal` physical start; zero retries; AI cap 0; every other market endpoint cap 0;
- fresh one-shot claim, fresh SQLite database, fresh loopback port, IN_APP only, no plan/holding mutation, webhook, broker, order, or trade;
- 15-second controller bound plus at most 20 seconds cooperative cleanup; first reference failure stops all admission and writes the journal/audit described above;
- retain only fixed diagnostic enums/status family and counts; do not retain provider content;
- market-data fee, if any, remains unknown; AI cost is zero.

This adds one market call if it succeeds, but isolates calendar health before reopening up to three AI starts and 105 market starts. Directly reopening the full run saves that one preliminary call on success, while risking immediate re-entry into the expensive workflow before the intermittent prerequisite is characterized. Either option requires fresh explicit approval.

At the time of R21, the stock certificate remains locally valid only through `2026-09-16T14:48:40.405317+08:00`; the five-index certificate remains valid through `2026-09-18T10:20:44.522358+08:00`. Expired evidence must be reported and separately recertified rather than silently refreshed. A calendar diagnostic success would prove only that invocation's calendar path. It would not prove R19's real v5/8,192 extraction, semantic correctness, review/save/activation, market-window evaluation, natural BUY/SELL/RISK triggers, or visible IN_APP delivery.
