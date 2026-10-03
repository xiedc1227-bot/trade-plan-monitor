# ADR 0003: Share Board-Index Data and Let Trade Plans Own Its Usage

> Canonical agent-facing English version. The human-review Chinese version is `0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md`; both documents must remain semantically equivalent.

- Status: `Accepted`
- Date: `2026-09-02`
- Initiative: `market-index-context`
- Modules: `index-identity`, `index-data`, `plan-index-conditions`, `monitor-index-view`, `backtest-index-data`, `backtest-index-view`
- Approved design: [`PROPOSAL-market-index-context.md`](https://github.com/xiedc1227-bot/trade-plan-monitor/blob/030075c4946bf34833a0155fde6b4deda3c79055/docs/proposals/PROPOSAL-market-index-context.md)

## Context

Board-index conditions are important inputs for A-share timing, but the product needs an explicit boundary between supplying market data and deciding a trade. A tool-level mandatory market judgment would apply one interpretation to every plan, hide behavior outside the plan document, and make it difficult to explain why two strategies should react differently to the same market.

Monitoring and backtesting also need to show the same reference-index data without fetching and calculating an identical index separately for every stock. At the same time, sharing the data must not cause plans to share condition outcomes or final decisions.

The accepted proposal evaluates automatic board mapping, shared immutable data, plan-owned condition trees, Web projections, deterministic backtesting, migration, and provider capability as one architecture. This ADR records the central boundary and the alternatives that were rejected.

## Decision

1. The tool owns reference-index identity, fetching, validation, reusable numeric facts, health, cutoffs, revisions, and hashes. It does not publish one universal market classification and does not add a hidden trade gate.
2. Each trade plan owns whether and how index data affects it. The approved index conditions may appear under `entry`, `reduction`, `risk`, or `blockers`, using the existing `ALL`/`ANY` tree rules. A plan may contain no index condition.
3. Stocks mapped to the same board index at the same cutoff use one immutable `MarketIndexSnapshot`. Condition evidence and final decisions remain specific to each plan.
4. Mapping version `board-index-map-v1` uses these exact bindings:
   - SSE Main Board → SSE Composite `000001.SH`;
   - SZSE Main Board → Shenzhen Component `399001.SZ`;
   - ChiNext → ChiNext `399006.SZ`;
   - STAR Market → STAR 50 `000688.SH`;
   - BSE → BSE 50 `899050.BJ`.
5. Phase 1 permits `INDEX_CLOSE_GTE_MA`, `INDEX_CLOSE_LTE_MA`, `INDEX_MA_NON_DECREASING`, `INDEX_MA_NON_INCREASING`, `INDEX_RETURN_GTE`, and `INDEX_RETURN_LTE` with the bounds approved in the proposal.
6. Monitoring and backtesting display shared index facts separately from plan-specific condition outcomes. Browser code does not determine mappings, calculate conditions, or alter policy priority.
7. Index binding and conditions require an explicit Schema v2 plan. Existing Schema v1 plans and historical results remain unchanged.
8. Intraday evidence uses certified completed five-minute buckets. Implementation approval depends on a read-only provider capability check for the approved index codes and fields. Provider tokens must not enter reports or logs.
9. Phase 1 covers board indices only. Industry-index classification and rules require a separate approved design because their data source and mapping are not yet decided.

## Alternatives Considered

### Apply one mandatory market gate inside the tool

Rejected because it would create behavior that is not written in the trade plan. It would also force different strategies to use one interpretation and would make monitoring evidence less direct.

### Calculate and fetch the same index separately for every stock

Rejected because identical board data would be duplicated, provider quota would be wasted, and timing or normalization differences could make stocks on the same board see different facts.

### Let the user or AI choose any reference index

Rejected for Phase 1 because arbitrary selection weakens repeatability and can produce inconsistent or invented bindings. The stock code and versioned mapping determine the board reference.

### Include industry indices in Phase 1

Rejected because no authoritative industry-classification source, classification date rule, or versioned industry-to-index mapping has been approved. Adding it now would make backtests difficult to reproduce.

## Consequences

- One index snapshot can serve several stocks while every plan remains independently explainable.
- The same snapshot may produce different outcomes for different plans; this is intended behavior.
- Removing all index conditions from a plan removes index influence from that plan's decisions.
- API and Web designs must not expose a shared field that implies one automatic market conclusion or trade effect.
- Plan Schema v2, path-level evidence, formula identities, historical coverage, and hashes add implementation work, but they make monitoring and replay auditable.
- A plan with no index condition continues its original behavior when index data is missing. A plan that uses index data receives `MISSING_INPUT` only on affected paths.
- Module specifications and offline implementation were separately authorized on `2026-09-02` in the recorded dependency order.

## Security and Operational Effects

Index-provider responses are untrusted and must be validated at the adapter boundary. Mixed stock/index identities, duplicate bars, noncanonical decimals, bad cutoffs, gaps, future data, and formula mismatches fail closed. Failure of one board index is isolated from other boards.

Shared snapshots are immutable and content-addressed. Logs, errors, APIs, reports, and exports must not expose provider tokens or unnecessary raw provider responses. A real provider request requires separate authorization even when the configuration already contains a project token.

## Reversal and Migration

Changing the responsibility boundary so the tool again controls trades would require a superseding ADR, a new plan-schema version, API and evidence changes, and a migration that preserves existing plan and result hashes. Changing a board binding requires a new mapping version and new plan versions; an active plan cannot change silently.

Schema v1 plans remain readable and executable with `referenceMarket=null`. Schema v2 drafts add the automatic binding and only the index conditions present in the source plan or explicitly reviewed by the user. Historical results are not rewritten with later index data or conclusions.
