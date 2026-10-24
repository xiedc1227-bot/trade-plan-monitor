# Specification: market-regime

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).

## MR01 — Objective and dependencies

Provide source-defined market state for a linked ordinary BUY. Reuse `market_index/identity.py`, `models.py`, `formulas.py`, `snapshots.py` and the admitted daily/calendar pipeline. Classification belongs in the decision domain, not in shared provider facts or informational index display. Depends on existing index identity/data; supplies immutable evidence to `relative-strength` and `confirmation-selection`.

## MR02 — Identity and daily evidence

Use the verified stock board and existing server mapping: SSE_MAIN → `000001.SH`; SZSE_MAIN → `399001.SZ`; CHINEXT → `399006.SZ`; STAR_MARKET → `000688.SH`; BSE → `899050.BJ`. Never substitute an industry index, `399107.SZ`, or a provider's alternate instrument. Validate mapping at extraction composition, review, activation and replay admission. An unavailable scope stays blocked; resolving a symbol is not certification.

Define D as the exact latest exchange session completed at the evaluation cutoff, not whichever bar happened to arrive last. Require an official D close and the continuous scheduled index history ending at D, with all consumed revisions available by the cutoff. At least 60 observations are needed for the complete state calculation. No partial intraday bar, stale D-1 substitution, synthetic fill, mixed-provider fragments or future revision is eligible. Source/provider basis and formula identity accompany every result.

## MR03 — Exact state calculation

Let I be D close; M20 and M60 be close SMAs ending at D; M20_5 be MA20 ending five exchange sessions before D; L20 be the minimum daily low across the 20 sessions immediately before D, excluding D. Use exact Decimal comparisons with no display rounding. Add a versioned rolling-low fact without changing old fact/hash definitions.

Evaluate in order:

1. `BROKEN` when `I < L20 AND I < M60`.
2. `WEAK` when BROKEN is definitively false and `I < M20 AND M20 < M20_5`.
3. `NORMAL_TRANSITION` when necessary evidence is complete and both higher states are false.
4. `UNKNOWN` when required evidence is unavailable or a higher-priority state cannot be excluded.

An equality does not satisfy a strict inequality. Known decisive results may survive irrelevant missing operands, but the complete-state view lists all missing facts. UNKNOWN never means NORMAL_TRANSITION. State is plan-bound research policy, not a universal market opinion.

## MR04 — Output and integration

`MarketRegimeEvidence` records `regime`, `decision_session`, `evidence_cutoff`, `reference_market`, I/M20/M60/M20_5/L20, every predicate outcome, `source_hashes`, `formula_version` and reason codes. Missing numeric values are null, never zero. Preserve the exact evidence set used, including the difference between data timestamp and availability timestamp.

Acquire only requested index evidence, share immutable snapshots across symbols referencing the same index/cutoff, and recheck plan/review/activation identity before committing. A missing index affects only rules that depend on it. Read-only overview access does not acquire data or grant decision authority. P0 adds no polling-frequency increase or second worker.

## MR05 — Acceptance and verification

| ID | Required evidence |
| --- | --- |
| MR-A01 | All board mappings match; mismatches, unavailable BSE scope and alternate benchmarks never substitute silently. |
| MR-A02 | Hand-constructed sequences prove all operands, exclusion of D from L20, five-session offset and 60-observation requirement. |
| MR-A03 | All four states, strict equalities and priority ambiguity produce the specified result. |
| MR-A04 | Missing D, gaps, provisional bars, later-received revisions and future data cannot produce a false pass; correction preserves old evidence. |
| MR-A05 | Shared acquisition and actual runtime composition use the evidence; unlinked rules remain independent and activation races reject stale results. |

Focused verification command from `trade-plan-monitor/`: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_regime.py tests/integration/test_market_linkage_runtime.py -q`. Paths are implemented tests. Follow MLP07 style and full verification; tests use deterministic providers and independent expected values.
