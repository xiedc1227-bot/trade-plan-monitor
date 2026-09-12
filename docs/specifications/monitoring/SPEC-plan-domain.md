# Spec: plan-domain (Trade Plan Domain Model)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-plan-domain.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Define the system's only executable trade-plan contract. This module owns versioned plans, activation policies, price zones, position limits, allowlisted conditions, cross-field validation, and stable hashing.

When reviewing a structured plan, the user must be able to see exactly which conditions the system will evaluate. An active plan is immutable; every change creates a new draft version.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- Pydantic 2 for boundary and domain validation
- `Decimal` for user-entered prices; integer fen for comparison and storage
- YAML/JSON for portable import and export
- SHA-256 over canonical JSON for plan identity

Exact patch versions are pinned in `pyproject.toml` and the lock file during scaffolding.

## Commands

```powershell
python -m pytest tests/unit/test_plan_domain.py -q
python -m ruff check src/trade_plan_monitor/domain tests/unit/test_plan_domain.py
python -m compileall -q src/trade_plan_monitor/domain
```

## Project Structure

```text
src/trade_plan_monitor/domain/
├── plan_models.py       # Plan, activation, price, position, and condition unions
├── plan_validation.py   # Cross-field validation and activation readiness
├── plan_codec.py        # Canonical JSON and safe YAML/JSON import/export
└── plan_hash.py         # Stable content hashing
tests/unit/
└── test_plan_domain.py
config/plans/
└── 003043.SZ.sample.yaml
```

## R08 Version Scope

The following Schema 1 contract and the additive Schema 2 contract in `SPEC-plan-index-conditions.md` describe `LEGACY_LOW_BUY`. The approved R08 design adds a separate Schema 3 / `EXPLICIT_RULES` / `explicit-rules-v1` contract in [SPEC-executable-plan-extension](SPEC-executable-plan-extension.md), with exact fields, partial-draft versus executable validation, explicit action quantities, independent confirmed inventory, unresolved policies and error codes. It is not implemented by this documentation change. [ADR 0005](../../decisions/0005-version-explicit-plan-rules.md) governs old/new read/write/hash/replay compatibility; do not widen the legacy model graph or change old hashes. No unresolved concrete plan gains activation approval from this design.

## Public Contract

### Versioned Plan

```python
class TradePlan(BaseModel):
    schema_version: Literal[1]
    plan_id: str
    version: int
    symbol: str
    name: str
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: PlanMetadata
    activation: ActivationPolicy
    position: PositionPolicy
    levels: PriceLevels
    entry: EntryPolicy
    reduction: ReductionPolicy
    risk: RiskPolicy
    blockers: BlockerPolicy
    monitoring: MonitoringPolicy
```

Activation policy is a discriminated union:

- `MANUAL`: remains active until explicitly disabled by the user.
- `TRADING_DAY`: active only on one specified trading day.
- `DATE_RANGE`: active between start and end dates according to the trading calendar.

`activation_is_eligible_on` is the canonical date policy for both replay and production.
It evaluates the market date carried by the evaluation target, not the later wall-clock
time at which delayed work or restart recovery happens. `TRADING_DAY` equality and both
`DATE_RANGE` endpoints are inclusive; `MANUAL` remains eligible until explicit disablement.

At most one version is active per symbol. Editing an active version creates a new draft, and activating the new version atomically deactivates the previous one.

### Allowlisted Condition DSL

Monitoring conditions are typed data, never expression strings. Schema v1 supports:

- `PRICE_IN_ZONE`
- `NO_NEW_LOW_FOR_BARS`
- `NON_DECREASING_CLOSE`
- `VOLUME_TO_PREVIOUS_LTE`
- `VOLUME_TO_MEDIAN_LTE`
- `VOLUME_TO_MEDIAN_GTE`
- `MACD_HIST_IMPROVEMENT_GTE`
- `PRICE_RECLAIMS_INDICATOR`
- `UPPER_WICK_RATIO_GTE`
- `RETREAT_FROM_SESSION_HIGH_GTE`
- `CLOSE_IN_BAR_LOWER_HALF`
- `CONSECUTIVE_CLOSES_BELOW_LEVEL`
- `OFFICIAL_CLOSE_BELOW_LEVEL`
- `NEXT_TRADING_DAY_RECOVERY`
- `POSITION_BUCKET_AVAILABLE`
- `SELLABLE_QUANTITY_GTE`
- `MANUAL_EVENT_RISK_CLEAR`
- `DISTANCE_FROM_LIMIT_DOWN_GTE`
- `LOWER_BAND_HITS_LTE`

Each condition has its own Pydantic model and bounded parameters. Logical composition allows only `ALL` and `ANY`, with maximum depth 4 and at most 50 leaf conditions per plan.

`VOLUME_TO_MEDIAN_LTE` uses `max_ratio`; `VOLUME_TO_MEDIAN_GTE` uses `minimum_ratio`. Both compare the latest completed-bar volume with the median of the specified number of preceding completed bars. `SELLABLE_QUANTITY_GTE` requires both an explicit `bucket` (`CORE` or `TACTICAL`) and a board-lot `quantity`, so one bucket can never satisfy another bucket's sellability rule.

`PRICE_IN_ZONE` uses the latest valid normalized complete minute close. `PRICE_RECLAIMS_INDICATOR` scans every adjacent pair in the exact current 5-minute bucket against one selected current-date indicator value, requires `previous_price < indicator <= current_price` for at least one pair, and also requires the bucket-ending price to remain at or above the indicator; entering the bucket already above is not a reclaim. `LOWER_BAND_HITS_LTE` compares each selected complete 5-minute close with the `ta-v1` 5-minute lower-band point of the same identity and counts equality as a hit. `CONSECUTIVE_CLOSES_BELOW_LEVEL` itself requires the configured number of adjacent complete closes to be strictly below the named level. Pressure-specific after-touch eligibility is imposed later by T023 orchestration and is not a hidden leaf parameter.

The four configured pressure rejection alternatives together are the complete definition of failure to hold; Schema v1 adds no fifth pressure condition.

Unknown conditions, arbitrary formulas, scripts, SQL, field paths, dynamic imports, and external calls are invalid input.

### Validation Rules

Validation covers:

- A-share symbol format and exchange consistency;
- valid tick size, price precision, and board-lot quantities;
- `0 < core_target_qty + tactical_target_qty <= max_qty`;
- non-overlapping actionable price zones with explicit boundary inclusion;
- risk line and pressure reference values within reasonable configured bounds;
- positive, bounded windows, ratios, timeouts, and bar counts;
- supported indicator formula versions and timeframes only;
- complete activation date fields;
- all market evidence required by each condition is available from `market-data`;
- no unresolved material AI warning or unmapped source text at activation.

Every validation result contains `code`, `path`, `severity`, `message`, and `activationBlocking`. Errors prevent saving. Ordinary warnings allow draft saving, while activation-blocking warnings must be resolved first.

## Code Style

```python
class PriceZone(BaseModel):
    low_fen: int = Field(gt=0)
    high_fen: int = Field(gt=0)
    include_low: bool = True
    include_high: bool = True

    @model_validator(mode="after")
    def validate_order(self) -> "PriceZone":
        if self.low_fen > self.high_fen:
            raise ValueError("price zone lower bound cannot exceed upper bound")
        return self
```

Python uses `snake_case`, explicit enums, and immutable value objects where practical. This module contains no market-data, database, or network I/O.

## Testing Strategy

- Table-driven unit tests for every condition type and boundary.
- Property tests for price zones, canonical serialization, and hash stability.
- Safe YAML/JSON round-trip import and export tests.
- A golden fixture for the Huaya Intelligent plan.
- Verify that changing a price by one fen or quantity by one share changes the plan hash.
- Cover unknown fields, arbitrary expressions, excessive nesting, NaN/Infinity, oversized text, and dangerous YAML tags.

## Boundaries

- Always: validate at import, API, AI-output, save, and activation boundaries.
- Always: apply the canonical activation policy at production selection, context assembly,
  and the final transaction fence using the target market date.
- Always: preserve source text and draft provenance without making either executable.
- Ask first: add a condition type, schema version, or activation mode.
- Never: execute user- or AI-supplied code, formulas, or SQL.
- Never: infer a fill from an alert or acknowledgement.
- Never: mutate an active plan in place.

## Success Criteria

- The sample plan round-trips without precision loss and produces a stable hash.
- The database can transactionally guarantee one active version per symbol.
- A plan with a material AI omission cannot activate.
- Every executable rule maps to a typed allowlisted condition.
- Boundaries such as 64.50 and 68.80 have exactly one owner.
- No import path can instantiate dangerous objects or execute code.

## Open Questions

None blocking. The approved 2026-08-21 correction adds `VOLUME_TO_MEDIAN_GTE` and makes the `SELLABLE_QUANTITY_GTE.bucket` field mandatory in the unreleased Schema v1 contract. After Schema v1 is released, adding condition types requires a schema upgrade and renewed review.
