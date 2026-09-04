# ADR 0002: Use Asia/Shanghai for All Backtest Time

> Canonical agent-facing English version. The human-review Chinese version is `0002-use-asia-shanghai-for-backtest-time.zh-CN.md`; both documents must remain semantically equivalent.

- Status: `Accepted`
- Date: `2026-08-26`
- Initiative: `backtest`
- Modules: `backtest-data`, `backtest-engine`, `backtest-results`, `backtest-jobs`, `backtest-api`, `backtest-web`

## Context

The product serves one local user and has no cross-environment or multi-region time-display requirement. A-share market facts, trading sessions, event-time replay, and the existing live contracts already use the China-market timezone. The local uncommitted backtest MVP nevertheless normalizes some market-store metadata, result rows, summary JSON, and fill CSV timestamps to UTC. That behavior is an implementation baseline to migrate, not an approved public convention. Introducing the same UTC rule into new backtest job and REST fields would create two observable time conventions inside one local product.

Mixed offsets can also change canonical request bytes, cursor signatures, idempotency hashes, ordering, filters, and exports even when two values denote the same instant. Naive local datetimes would instead depend on the process or browser environment and could silently reinterpret a trading day.

## Decision

1. Every backtest datetime uses the aware IANA business timezone `Asia/Shanghai` internally. This covers market facts, replay events, simulated fills/outcomes/equity, dataset metadata, job lifecycle, authorization, audit/idempotency records, lease/heartbeat deadlines, result publication, database values, API inputs/outputs, cursors, exports, and Web display.
2. RFC 3339 inputs accept only `+08:00` with 0–6 fractional-second digits and normalize before any identity operation. Canonical persistence, hashing, cursor encoding, output, and export text is exactly `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`. `Z`, offsetless datetime text, more than 6 fractional digits, and any other offset fail validation.
3. Date-only values such as event scope, `tradeDate`, `warmupStart`, and `acquiredTradeDate` remain `YYYY-MM-DD` China-market calendar dates. Durations and elapsed limits such as 30-second leases, 10-second heartbeats, 14-day retention, and 90-day retention remain duration semantics; an implementation may use a monotonic clock for elapsed scheduling, but any persisted or public deadline is `Asia/Shanghai`/`+08:00`.
4. Time normalization occurs before canonical request serialization, `requestHash`, idempotency comparison, cursor/HMAC encoding, ordering keys, persistence, and export generation. The browser validates `+08:00` and displays China time without converting through the host/browser timezone.
5. Semantic event timestamps retain their existing identity rules. `receivedAt`, `openAt`, `signalAt`, `filledAt`, `resolvedAt`, `eventAt`, and `markedAt` may contribute to fact/result/report identity where their owning contract already requires it. Operational job/audit timestamps do not enter `run_id`.
6. Existing `backtest-run-v1`, `dataset_hash`, and `backtest-report-v1` semantic identities remain byte-identical because their approved event timestamps already carry China-market semantics. The current UTC-normalized `backtest-run-summary-v1`, `backtest-fill-record-v1`, `backtest-detail-record-v1`, summary-JSON, and fill-CSV projections become immutable legacy compatibility inputs. New China-time result publication uses explicitly versioned v2 result/content-set/export domains and never silently reinterprets or overwrites v1 bytes. A legacy v1 row is not a verified reusable/public result under the new API until a separately approved adoption migration produces independently verified v2 content.

## Alternatives Considered

### Use UTC `Z` for job and audit fields

Rejected because this local China-market product has no cross-environment requirement, and the split convention would add conversion and contract complexity without user value.

### Accept any aware offset and normalize it to China time

Rejected because alternate offsets for one intent can drift canonical request hashes, cursor signatures, cache keys, and idempotency behavior before normalization is applied consistently. Fractional-second spellings within the allowed 0–6 digits are normalized to the one fixed six-digit canonical representation before those operations.

### Use offsetless local datetime text

Rejected because its meaning depends on ambient process/browser configuration and cannot prove the intended China-market instant.

## Consequences

- All backtest screens, API resources, databases, and exports show one China-time convention.
- Boundary validators must reject `Z`, missing offsets, offsets other than `+08:00`, and more than 6 fractional digits; canonical output/storage always has exactly 6 fractional digits.
- Sort/filter/cursor/idempotency code receives one canonical timestamp representation.
- Date-only market scope and elapsed-duration thresholds keep their existing meanings and numeric values.
- Existing UTC-normalized v1 result/export projections remain immutable compatibility artifacts; active v2 publication and public APIs expose only canonical China time.
- Changing the public timestamp convention later requires a superseding ADR, generated-contract migration, cursor/idempotency compatibility plan, and data/export migration evidence.

## Security and Operational Effects

Fail-closed timestamp validation prevents an untrusted request from shifting a trading event into another date or producing ambiguous filter, cursor, retention, or idempotency behavior. Logs and diagnostics may use the same canonical China time but must retain existing secret-redaction and bounded-text rules. Monotonic elapsed-time measurement remains appropriate for lease and timeout enforcement and is not exposed as a wall-clock timestamp.

## Reversal and Migration

The backtest REST/job design is implemented under the frozen 42-path OpenAPI contract. Removing the rejected UTC proposal therefore requires a reviewed, generated-contract change only if a future public field actually changes; WEBF13 makes no such change. Before any schema mutation, migration takes verified backups and inventories UTC market metadata and v1 result/export artifacts read-only. Market metadata excluded from `dataset_hash` may be converted to the equivalent canonical China time only through a tested migration that proves dataset identities unchanged. Identity-bearing v1 result/export bytes are preserved, while the active path writes versioned v2 China-time projections. If a future implementation changes timezone representation again, it must preserve existing `run_id`, `dataset_hash`, `reportHash`, request/idempotency behavior, and cursor traversal, and retain or explicitly migrate every versioned export identity.

## Review Status

The user explicitly directed on 2026-08-26 that the product has no cross-environment time requirement and that all backtest time use the China timezone. This ADR is therefore `Accepted` with decision date `2026-08-26`. The corrected API/engine/results/jobs clauses are implemented, including the single `Asia/Shanghai`/`+08:00` public contract. WEBF13 documents route wiring only and does not change this decision, the generated API, or any time representation. Commit, push, dependency installation, and any real network call remain separately authorized actions.
