# Spec: backtest-index-data

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-index-data.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Freeze exact board-index history beside stock history, derive plan-specific warm-up and coverage, and replay the same snapshot/formula/evidence inputs used by monitoring without lookahead or provider access. Existing datasets and runs remain immutable compatibility artifacts.

## Commands and Structure

```powershell
python -m pytest tests/unit/test_backtest_index_data.py -q
python -m pytest tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q
python -m ruff check src/trade_plan_monitor/backtest src/trade_plan_monitor/market_index
```

```text
src/trade_plan_monitor/backtest/index_data.py      # requirements, coverage, replay snapshots
src/trade_plan_monitor/backtest/dataset.py         # additive v2 index artifact identities
src/trade_plan_monitor/backtest/market_store.py    # immutable INDEX_5M/INDEX_DAILY revisions
src/trade_plan_monitor/backtest/runner.py          # cutoff-safe snapshot injection
tests/unit/test_backtest_index_data.py
tests/integration/test_backtest_index_dataset.py
```

## Dataset Versioning and Scope

- Existing `backtest-dataset-v1` manifests, hashes, stock artifacts, and completed results are never rewritten.
- The exact immediately preceding six-table stock-only market schema is recognized explicitly and expanded in one transaction with three empty index tables and their indexes. Existing rows and dataset bytes are verified unchanged. Partial index extensions, unknown schemas, sidecars, or any mismatch still fail closed before mutation.
- A newly frozen dataset may use `backtest-dataset-v2`, which derives the unique board index for every stock symbol using `board-index-map-v1` and can contain immutable `INDEX_5M` and `INDEX_DAILY` artifacts.
- Users, AI, and API clients never choose index codes. The dataset stores derived `referenceMarketBindings` sorted by stock symbol and index code.
- Dataset scope remains 1–10 stock symbols. Derived indices are at most five and do not count as additional stock symbols.
- Index provider acquisition is a distinct capability and remains `UNVERIFIED` until separately probed. Offline fixtures and already persisted normalized artifacts are valid for tests; no real request occurs during `verify`, freeze, run, result query, or export.

`backtest-dataset-v2` hash membership includes the exact mapping version, derived bindings, normalized index artifact revision hashes, and `formulaDefinitionHash`, in addition to all existing stock facts. Operational job ids, progress, cache state, provider name, and plan conditions are excluded. Any relevant index bar correction, mapping version, or formula definition produces a different dataset hash while v1/v2 historical manifests remain readable.

## Plan-Specific Requirements and Warm-up

Index coverage is required only when the selected plan contains at least one index leaf. A plan with no index leaf follows the existing stock-only coverage/run path even if informational index history is absent or blocked.

For one plan, deduplicate the exact fact requests from all four trees. Required input before `eventStart` is the maximum of:

- `period` official open days for `INDEX_CLOSE_GTE_MA`/`INDEX_CLOSE_LTE_MA`;
- `period + lookback` official open days for `INDEX_MA_NON_DECREASING`/`INDEX_MA_NON_INCREASING`;
- `window_size + 1` official open days for `INDEX_RETURN_*` with `OFFICIAL_OPEN_DAYS`;
- `window_size + 1` completed five-minute buckets for `INDEX_RETURN_*` with `FIVE_MINUTE_BUCKETS`.

The required warm-up is plan-specific and never a global fixed number. Calendar navigation uses only certified China-market open days already frozen in the dataset. Missing predecessor facts, gaps, duplicates, future bars, wrong index identity, wrong formula hash, or a bar later than its replay cutoff are explicit blockers.

## Storage and Replay Contract

`INDEX_5M` natural identity is `(indexCode, barAt)` and `INDEX_DAILY` is `(indexCode, officialTradeDate)`. Each immutable artifact uses the same normalized `MarketIndexBar` and content hash as monitoring. Corrections append a revision; referenced content is never overwritten. Frozen reads recompute hashes before parsing and iterate by index-day in bounded batches.

`MarketIndexReplaySeries` supplies only bars whose `barAt <= decisionCutoff`. For each plan/cutoff it calls the same `market-index-facts-v1` calculator and the same snapshot builder used by monitoring. Snapshots for equal `(indexCode, cutoff, requestSetHash, datasetRevision)` are interned and shared across stock runs/readers inside one replay process; plan evidence remains separate.

`datasetRevision` is only an in-process replay-residency fence. The replay snapshot's content `revision` is derived from the exact selected bars' provider revisions, so a local SQLite row id never enters `snapshotHash`; identical live/replay bars, requests, and cutoff therefore remain byte-identical.

An intraday stock decision uses only completed index five-minute buckets and official daily facts already available at that cutoff. An official-close stock decision uses the canonical same-day official index close only if its observed/certified time is not later than the decision input. Warm-up bars participate in `marketIndexDataHash` but never create fills or visible event-period returns.

## Identities

- `marketIndexDataHash = SHA256("backtest-index-data-v1\0" + UTF8(canonicalJson(sorted exact index artifact memberships)))`.
- `indexRequirementHash = SHA256("backtest-index-requirements-v1\0" + UTF8(canonicalJson(sorted plan fact requests and exact paths)))`.
- A Schema v2 plan with index leaves uses `backtest-run-v3`; its preimage includes the existing normalized run input plus binding, `marketIndexDataHash`, `indexRequirementHash`, and `formulaDefinitionHash`.
- `backtest-run-v1` and `backtest-run-v2` preimages remain byte-for-byte unchanged for all existing stock-only inputs.

Changing any decision-relevant index bar, path, condition, threshold, cutoff, mapping, or formula changes the appropriate dataset/run/report hash. Changing display range, job metadata, or pagination does not.

## Coverage Projection

`BacktestReferenceMarketCoverage` contains binding, condition paths, exact required/available five-minute and official-day counts, warm-up start/end, ordered blockers, `marketIndexDataHash`, and `formulaDefinitionHash`. Coverage is computed server-side. It blocks submission/replay only when the plan uses index leaves; otherwise `required=false`, paths are empty, and missing index artifacts are informational.

Coverage uses the selected stock's frozen certified open-day calendar. It requires the exact trailing plan-specific warm-up dates/buckets and every official-day/five-minute index observation in the event range. Missing observations are reported with stable `GAPPED_INDEX_OFFICIAL_WARMUP`, `GAPPED_INDEX_FIVE_MINUTE_WARMUP`, `GAPPED_INDEX_OFFICIAL_EVENT`, or `GAPPED_INDEX_FIVE_MINUTE_EVENT` blockers; raw row counts cannot conceal a missing predecessor or event bucket.

## Testing Strategy

- Prove exact dynamic warm-up for every condition and combined maximum.
- Prove v1 dataset/run/result goldens stay unchanged and v2 index corrections are append-only.
- Prove no lookahead at five-minute and official-close cutoffs, including same-timestamp observed-time ordering.
- Prove monitor and replay create byte-identical snapshots/evidence for identical bars, requests, and cutoff.
- Prove two plans share one replay snapshot but produce independent/different outcomes.
- Prove index coverage blocks only plans with index leaves and that provider/network calls during offline replay are exactly zero.
- Prove any artifact tampering, identity mix, gap, duplicate, future bar, or formula mismatch fails closed.

## Boundaries and Success Criteria

- Always: keep old artifacts immutable, derive indices from stock codes, include warm-up in identity, and reuse the live formulas/evaluator.
- Ask first: enable a real provider, change dataset/run domains, historical timestamp semantics, mapping, or formula.
- Never: rewrite history, use future/unfinished data, synthesize an index, mix industry data, or call a provider during replay.
- Identical live/replay inputs produce identical snapshot and condition evidence bytes; no-condition plans retain original behavior.
