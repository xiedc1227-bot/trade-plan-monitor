# Contract: market-linkage-p2

Status: implementation contract — 2026-10-26. Refines the six approved decisions without adding strategy thresholds.

## MLP2-C01 — Version and wire ownership

Schema 8 / condition-plan-v4 / pretrade-policy-v1. Review hash domain: plan-review-content-v5. Fixed sizing keeps quantity_policy.mode=MARKET_FACTOR and base_quantity=Q0. ATR sizing instead uses quantity_policy.mode=DERIVED_MARKET_FACTOR with no base_quantity; the other market factors/rounding/capacity/freeze fields stay explicit. pretrade_policy.sizing contains mode=ATR_RATIO_TIERS, metric=ATR14_OVER_CLOSE, base_qty and tiers[{lower,upper,multiplier}]. FIXED_Q0 contains only mode. Reject inconsistent/mixed forms. Decimal inputs must be strings; all quantities/fen are strict integers within the JavaScript safe-integer bound.

## MLP2-C02 — Fees and source evidence

Economics is a discriminated union on mode: NONE has no other fields; PREVIEW_ONLY/REQUIRED carry entry_price_mode, target_price_fen, risk_price_fen, fee_schedule; REQUIRED additionally carries gates with at least one non-null threshold. fee_schedule has schedule_id, version, currency, symbols (1–100 exact stock IDs), effective_from, effective_through, provenance, commission_rate, minimum_commission_fen, components (up to 20), buy_slippage_fen, sell_slippage_fen. Components identify id, side BUY/SELL/BOTH, kind TAX/TRANSFER/HANDLING, rate and included_in (null, COMMISSION or another component ID). Both-side inclusion requires compatible charging sides. Provenance records source, excerpt, as_of (nullable), classification=ESTIMATE. All fields are mandatory unless explicitly a union branch; absence never implies zero.

## MLP2-C03 — Evidence, API and freezing

Source bindings use existing reviewed leaf-path coverage, including P2 fields. Level evidence uses the existing source review mechanism supplemented with level, dimension (PRICE_STRUCTURE/TREND/VOLUME_OR_CANDLE/VOLATILITY), source, excerpt, as_of and indicator (nullable); MA20/BOLL_MIDDLE share TREND. Record reviewer decision through the existing explicit review receipt, never a model-provided reviewed=true. Store decision evidence as p2-pretrade-evidence-v1, cost calculations as p2-economics-v1, and consumed continuity as p2-consumed-v1; use canonical Decimal normalization. Keep old evidence byte-compatible. A derived Q0 does not rewrite source plan hashes.

## MLP2-C04 — Compatibility and sequential seams

Inventory: plan_codec/plan_hash → current draft dispatch/AI extraction/review → persisted plan readers → daily runtime/confirm_signal/exception authority → simulation transaction → web DTOs/OpenAPI/UI → replay inputs/schedules/readers → notifications. Explicit schema sets and typed unions must admit 8 only when their entire authority chain is ready. Before then the public executable loader must reject 8; isolated models/pure functions are not shipped support. Existing schema-8 rejection tests must move to a genuinely unsupported version only when public admission is enabled, preserving rejection coverage.

## MLP2-C05 — Rollback and stage evidence

No historical rewrite. Additive storage if required; rollback keeps Schema 8 records unreadable for execution on an older binary. All migration tests use disposable SQLite. T01 baseline V01: 74 passed in 0.65s on 2026-10-26, before behavioral changes. T02–T03 are split into model/pure contract and gated dispatch; public admission remains closed until T10 authority guards are complete. Broad typed-reader adaptations are separate sequential slices of at most five files each with focused tests.


