# Frozen result rule comparisons

## RC-01 — Contract

Continuous result pages list every scheduled source and its immediate predecessor. Expand a source to load `GET /api/v1/backtest-runs/{run_id}/rule-changes/{source_id}`. Each response contains one complete comparison, bound to the run, manifest, source and version. It compares final frozen snapshots by stable rule ID (risk branch kind), not mutable preparation records or a new AI interpretation. Initial rules are ADD; equal values RETAIN; changed values MODIFY; absent rules REVOKE. Independent legacy versions are explicitly labelled, while still comparing adjacent snapshots. Account descriptions never reset the account.

## RC-02 — Presentation and bounds

Show all four groups, full before/after fields, meaningful labels, prices in yuan and quantities in shares. Retained content is expandable; no raw JSON is required to understand rules. One source loads at a time, without a fixed source count. Failed loads show an explicit retry; switching runs cancels stale responses. Existing summary size bounds and frozen report hashes remain unchanged. No AI call, replay, publication or database migration is part of this read.

## RC-03 — Acceptance

Test initial/retained/modified/added/revoked rules, identity-preserving reorder, independent versions, missing sources, stale requests and unsafe source text. Verify the four actual frozen plans in the live browser, including source 2 entry cancellation, source 3 retained exit, source 4 modified first entry/new second entry/cancelled exit. Update English and Chinese operations and verification records together.

Completed on 2026-10-17: 52 backend and 8 final focused frontend tests passed, with type checking, production build and four-source browser/API verification. See [verification record](../docs/verification/2026-10-17-result-rule-comparisons.md).
