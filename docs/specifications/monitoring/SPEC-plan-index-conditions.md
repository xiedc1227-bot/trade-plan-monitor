# Spec: plan-index-conditions

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-plan-index-conditions.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Add explicit Schema v2 reference-market binding and six allowlisted board-index condition leaves to the existing plan trees, then evaluate those leaves from a shared index snapshot with path-addressed evidence. Plans, not the tool, own whether and where index data affects a decision.

## Commands and Structure

```powershell
python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py tests/unit/test_decision_engine.py -q
python -m pytest tests/replay/test_decision_replay.py -q
python -m ruff check src/trade_plan_monitor/domain src/trade_plan_monitor/decision src/trade_plan_monitor/market_index
```

```text
src/trade_plan_monitor/domain/plan_models.py       # Schema v1/v2 and condition union
src/trade_plan_monitor/domain/plan_validation.py   # migration/binding/placement checks
src/trade_plan_monitor/decision/models.py          # optional snapshot and index evidence
src/trade_plan_monitor/decision/conditions.py      # six pure evaluators and paths
src/trade_plan_monitor/market_index/requirements.py
tests/unit/test_plan_index_conditions.py
```

## Exact Schema v2 Contract

The existing Schema v1 shape and field names remain unchanged. Schema v2 is additive:

```yaml
schema_version: 2
symbol: 688001.SH
reference_market:
  selection: AUTO_BOARD
  mapping_version: board-index-map-v1
  index_code: 000688.SH
entry:
  condition:
    type: ALL
    conditions:
      - type: NON_DECREASING_CLOSE
      - type: INDEX_CLOSE_GTE_MA
        index_role: BOARD_REFERENCE
        period: 20
```

- Schema v1 forbids `reference_market` and every index leaf.
- Schema v2 requires exactly one backend-derived `reference_market`, even when it contains zero index leaves, so monitoring can show the informational board reference.
- Import, AI draft acceptance, save, activation, and backtest submission recompute the binding from `symbol` and reject mismatch.
- The user and AI cannot submit `index_code`, `mapping_version`, another role, or another benchmark as free choice. Draft composition owns the generated binding.
- AI may return an index leaf only when the source plan explicitly states the corresponding rule and parameters; otherwise it remains unmapped text or a warning.

## Allowed Leaves and Parameters

All leaves use `index_role: BOARD_REFERENCE` and may appear under `entry`, `reduction`, `risk`, or `blockers`, within the existing maximum depth 4 and total 50 leaves.

| Type | Exact fields | Outcome test |
|---|---|---|
| `INDEX_CLOSE_GTE_MA` | `period: 2..250` | completed index close `>= SMA(period)` |
| `INDEX_CLOSE_LTE_MA` | `period: 2..250` | completed index close `<= SMA(period)` |
| `INDEX_MA_NON_DECREASING` | `period: 2..250`, `lookback: 1..60` | current SMA `>=` lookback SMA |
| `INDEX_MA_NON_INCREASING` | `period: 2..250`, `lookback: 1..60` | current SMA `<=` lookback SMA |
| `INDEX_RETURN_GTE` | `window`, `window_size: 1..250`, `threshold_ratio` | return `>= threshold_ratio` |
| `INDEX_RETURN_LTE` | `window`, `window_size: 1..250`, `threshold_ratio` | return `<= threshold_ratio` |

`window` is exactly `FIVE_MINUTE_BUCKETS|OFFICIAL_OPEN_DAYS`. `threshold_ratio` is a finite canonical decimal ratio in inclusive `[-1, 10]`; JSON binary floats, exponent text, redundant noncanonical decimal text at external boundaries, NaN, and Infinity are rejected.

Unknown parameters, formulas, roles, paths, scripts, expressions, provider fields, and industry identities remain invalid.

## Stable Plan Paths

Paths use the stored snake-case plan shape and zero-based array indices:

- policy root: `entry.condition`, `reduction.condition`, `risk.condition`, or `blockers.condition`;
- logical child: append `.conditions[N]` for each stored child;
- example: `entry.condition.conditions[1].conditions[0]`.

Paths are generated during deterministic tree traversal, never accepted from AI/browser input. Every Schema v2 index leaf evidence has one exact path. Reordering children changes the path and the plan hash.

## Evaluation and Evidence

`EvaluationContext` gains nullable `reference_market_snapshot`. The field is absent from canonical v1 result serialization when null, preserving all v1 hashes. A Schema v2 plan with an index leaf evaluates only against a snapshot whose `indexCode`, `mappingVersion`, cutoff, formula hash, and plan binding agree.

`IndexConditionEvidence` is attached only to an index leaf and contains:

- `plan_path`, `condition_type`, `index_code`, `mapping_version`, `snapshot_hash`;
- `decision_cutoff`, `data_cutoff`, `formula_id`, `formula_definition_hash`, and parameters;
- exact `actual_value`, `comparison_value`, `unit=POINTS|RATIO`;
- `outcome=SATISFIED|UNSATISFIED|MISSING_INPUT` and ordered unique missing codes.

Closed missing codes are `INDEX_SNAPSHOT`, `INDEX_IDENTITY`, `INDEX_CUTOFF`, `INDEX_HEALTH`, `INDEX_FACT`, `INDEX_HISTORY`, and `INDEX_FORMULA`. `MISSING_INPUT` has no guessed values and lists at least one code. Non-missing evidence has both compared values and no missing code.

The existing `ALL`/`ANY` three-valued rules combine stock and index children without change. Placement determines effect through existing policy priority. The evaluator never adds an index predicate outside a stored tree. A plan with no index leaf produces no index condition evidence, performs the original evaluation, and cannot change because a snapshot is null, stale, gapped, or blocked.

## Hash and Migration Rules

- `plan_sha256` continues to hash canonical plan JSON. Schema v2 binding and leaves participate naturally; Schema v1 bytes/goldens stay unchanged.
- `IndexConditionEvidence` participates in `decision-result-v1` only when present. Optional v1 fields use omit-when-null serialization, so historical v1 result hashes remain byte-identical.
- A Schema v2 replay uses the plan hash plus snapshot/formula hashes in evidence; changing any relevant binding, condition, cutoff, fact, or index bar changes the decision/report identity.
- No migration rewrites existing plan rows, active versions, result rows, exports, or fixtures. Schema v2 is always a new immutable plan version.

## Testing Strategy

- RED/GREEN boundary tests for all six leaves, both equality directions, and every minimum/maximum parameter.
- Reject each leaf in Schema v1; require and recompute the binding in Schema v2.
- Prove leaves work in all four policy roots and retain exact nested paths.
- Prove stale, gapped, missing, future, mismatched, or wrong-formula snapshots return path-local `MISSING_INPUT`.
- Prove two plans reading one snapshot can return different outcomes and final decisions.
- Prove removing all index leaves removes index influence and preserves no-condition behavior.
- Golden-test unchanged Schema v1 plan/result hashes and deterministic Schema v2 evidence bytes.

## Boundaries and Success Criteria

- Always: generate bindings server-side, preserve plan paths, and use only shared validated facts.
- Ask first: add a condition, role, range, path grammar, schema version, or formula.
- Never: mutate v1, invent an AI rule, let the browser evaluate, or add a hidden global gate.
- Every index-caused decision effect is traceable to one stored plan path and exact snapshot/formula hashes.

## Review Status

Approved for implementation and offline verification on `2026-09-02`; no commit, push, deployment, dependency installation, or real provider request is authorized.
