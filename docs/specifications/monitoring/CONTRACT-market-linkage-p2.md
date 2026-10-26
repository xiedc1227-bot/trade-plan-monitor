# Contract: market-linkage-p2

Status: implementation contract — 2026-10-26. Refines the six approved decisions without adding strategy thresholds.

## MLP2-K01 — Version and wire ownership

Schema 8 / condition-plan-v4 / pretrade-policy-v1. Review hash domain: plan-review-content-v5. Fixed sizing keeps quantity_policy.mode=MARKET_FACTOR and base_quantity=Q0. ATR sizing instead uses quantity_policy.mode=DERIVED_MARKET_FACTOR with no base_quantity; the other market factors/rounding/capacity/freeze fields stay explicit. pretrade_policy.sizing contains mode=ATR_RATIO_TIERS, metric=ATR14_OVER_CLOSE, base_qty and tiers[{lower,upper,multiplier}]. FIXED_Q0 contains only mode. Reject inconsistent/mixed forms. Decimal inputs must be strings; all quantities/fen are strict integers within the JavaScript safe-integer bound.

## MLP2-K02 — Fees and source evidence

Economics is a discriminated union on mode: NONE has no other fields; PREVIEW_ONLY/REQUIRED carry entry_price_mode, target_price_fen, risk_price_fen, fee_schedule; REQUIRED additionally carries gates with at least one non-null threshold. fee_schedule has schedule_id, version, currency, symbols (1–100 exact stock IDs), effective_from, effective_through, provenance, commission_rate, minimum_commission_fen, components (up to 20), buy_slippage_fen, sell_slippage_fen. Components identify id, side BUY/SELL/BOTH, kind TAX/TRANSFER/HANDLING, rate and included_in (null, COMMISSION or another component ID). Both-side inclusion requires compatible charging sides. Provenance records source, excerpt, as_of (nullable), classification=ESTIMATE. All fields are mandatory unless explicitly a union branch; absence never implies zero.

## MLP2-K03 — Evidence, API and freezing

Source bindings use existing reviewed leaf-path coverage, including P2 fields. Level evidence uses the existing source review mechanism supplemented with level, dimension (PRICE_STRUCTURE/TREND/VOLUME_OR_CANDLE/VOLATILITY), source, excerpt, as_of and indicator (nullable); MA20/BOLL_MIDDLE share TREND. Record reviewer decision through the existing explicit review receipt, never a model-provided reviewed=true. Store decision evidence as p2-pretrade-evidence-v1, cost calculations as p2-economics-v1, and consumed continuity as p2-consumed-v1; use canonical Decimal normalization. Keep old evidence byte-compatible. A derived Q0 does not rewrite source plan hashes.

Current extraction is plan-extract-v11. Review candidates retain null omissions while preserving scalar and collection bounds; executable models remain strict. POST /api/v1/plan-economics-previews is read-only; occurrenceId names the exception candidate_id and authorityGranted is the literal false. Schema 8 research uses backtest-run-v9. ResearchDecisionEvent.signal_pretrade and ResearchSignalReference.pretrade_ref deduplicate frozen P2 evidence; resolving all references and revalidating full DailySignalState is mandatory before report admission. New optional fields are omitted from old records. The 32 KiB result-item budget is unchanged.

## MLP2-K04 — Compatibility and sequential seams

Inventory: plan_codec/plan_hash → current draft dispatch/AI extraction/review → persisted plan readers → daily runtime/confirm_signal/exception authority → simulation transaction → web DTOs/OpenAPI/UI → replay inputs/schedules/readers → notifications. Explicit schema sets and typed unions must admit 8 only when their entire authority chain is ready. Before then the public executable loader must reject 8; isolated models/pure functions are not shipped support. Existing schema-8 rejection tests must move to a genuinely unsupported version only when public admission is enabled, preserving rejection coverage.

## MLP2-K05 — Rollback and stage evidence

No historical rewrite. Additive storage if required; rollback keeps Schema 8 records unreadable for execution on an older binary. All migration tests use disposable SQLite. T01 baseline V01: 74 passed in 0.65s on 2026-10-26, before behavioral changes. T02–T03 are split into model/pure contract and gated dispatch; public admission remains closed until T10 authority guards are complete. Broad typed-reader adaptations are separate sequential slices of at most five files each with focused tests.



All stages, including T10 public authority guards, are complete. See the [final acceptance report](../../verification/2026-10-26-market-linkage-p2.md).
