# ADR 0005: Version Explicit Plan Rules Without Reinterpreting History

> Canonical English; `0005-version-explicit-plan-rules.zh-CN.md` is the equivalent Chinese review copy.

- Status: `Accepted`
- Current scope: frozen compatibility rationale; new live operations follow `SPEC-unified-plan.md`.
- Review-version amendment: [ADR 0006](0006-review-mixed-source-with-bounded-treatments.md) supersedes only new server mapping/evidence versions; historical v1 snapshots and all prompt contracts remain frozen.
- Date: `2026-09-12`
- Initiative: `F06 / R08–R12`
- Modules: `plan-domain`, `decision-engine`, `ai-plan-drafting`, `strategy-state`, `notification-outbox`, `local-web`, `backtest-engine`

## Context

At `beff0410150813e64a242a3821a299090d963e9b`, `TradePlan` supports Schema 1/2 but still mandates entry/reduction/risk/levels and CORE/TACTICAL targets. `TradePlanDraft` inherits that complete model. `EvaluationResult` and runtime/outbox consume one bucket-bound trade intent; official risk has persistent side effects. The synthetic plan requires an arithmetic mean, direct quantity 100, ordinary selling and five-minute pure risk. Treating these as another low-zone fixture would change the user's meaning.

R03 protects prompts at import-time using generated-schema digests. R04/R05 bind review to exact source and document hashes; an edited AI draft remains pending without a completed current-content re-review workflow. R07 manual risk uses that same exact plan hash. The document hash includes `version`; it must not be renamed a semantic content hash. Historical event migrations use frozen validators and cannot safely consume evolving application unions.

## Decision

1. Add Schema 3 / `EXPLICIT_RULES` / `explicit-rules-v1` as a bounded sibling model, with the fields and semantics in [the extension specification](../specifications/monitoring/SPEC-plan-domain.md). Leave the legacy `TradePlan`, its condition union and prompt-visible model graph intact. Reuse scalar types, price arithmetic, three-valued evaluation helpers, calendar/data validation and transaction participants; add typed dispatch at consumers. Do not expand the old condition union and then repair its golden hashes.
2. Preserve Schema 1/2 canonical JSON/YAML round-trips and SHA-256. Their derived read/display mode is `LEGACY_LOW_BUY`; do not inject that field into stored bytes. Current repaired low-buy execution has the implementation label `legacy-low-buy-r06` in new run/audit metadata. Historical executions with no recorded execution version remain `UNRECORDED` in external provenance; do not backfill a claim about the algorithm that originally ran.
3. V3 exact plan hashes use the same canonical-document SHA-256 convention. V3-only semantic `contentHash` uses the `plan-review-content-v1` domain and excludes exactly the four E07 metadata/identity fields. It supplements, not replaces, sourceHash, exact planHash, reviewEvidenceHash, immutable planVersionId and active revision. R04/R05/R07 historical bindings remain unchanged. Identical saves may retain semantic review only with validated same-source/evidence lineage and a server binding to the new version; edits to trading meaning always reset it.
4. Add `ExplicitEvaluationResult` and v3 alert payloads as separate tagged variants. Retain `decision-result-v1` and old alert/dedup bytes. New results use `decision-result-v2`, explicit execution version and consumed state revisions; new alerts use `explicit-rule-alert-v1`. Reuse existing result store, outbox and event log through version dispatch, with additive migration where key/CHECK/payload constraints require it. Do not force general SELL into `PRESSURE_REDUCE_READY` or five-minute risk into `RISK_BREACH`.
5. Old and new live evaluation/occurrence identities cannot collide. Add execution/activation identity for new keys without rewriting legacy rows, using additional versioned key columns/constraints or a v3-specific participant in the same unit of work. The R09 slice must select and test the smallest lossless storage change before enabling any v3 write. No use of `formula_version=ta-v1` as a surrogate execution version.
6. Partial v3 drafts are typed and persist only as inactive candidates. Only the complete executable variant can enter activation/runtime. Structural invalidity is an error; absent business meaning is an unresolved review item. Incomplete source-only extraction is a valid review outcome, not successful executable conversion.
7. Preserve existing backtest reports, run IDs, dataset hashes, result hashes, frozen migration validators and simulated-fill semantics. The current `backtest/runner.py` and `execution.py` assume singular legacy intents/buckets. V3 research-fill submission must return `UNSUPPORTED_BACKTEST_PLAN_VERSION` until a separately reviewed backtest version exists. R09–R13 may replay the pure v3 monitor and temporary SQLite path without simulated fills; that is not v3 portfolio backtesting. A new run under repaired legacy code is new evidence, not reproduction of a pre-R06 buggy historical result.

## Prompt Compatibility Matrix

These values were read from R03 and the current local source. Golden prompt values use the existing `GOLDEN_PLAN_SOURCE`, not the new synthetic source. They remain immutable.

| Prompt | Plan contract | Generated-schema SHA-256 | Golden prompt SHA-256 |
|---|---|---|---|
| `plan-extract-v1` | Historical Schema 1 | `fbf241167c4e3960c98b59faf62e46b590185a8711ba22209720d683562d18a1` | `420e06c0a8ab136a1b95c8218474fccd7f134d1bc5c9e1365e0c6a4a099e3d8d` |
| `plan-extract-v2` | Historical Schema 2, five-index allowlist | `fd5f2f42184ea0fa5b361087f869aa73a7a8e26d961c203d80e1e506d98cc0a3` | `6d9ba53055700e508251fc62ce3a10c2c719b68874ac78aee9f27cbd40127daf` |
| `plan-extract-v3` | Existing Schema 2, six-index allowlist | `0de88a7a9bdec1a84ad0d458d2963fcdc2b68bfee591dea270b0f35bc5fa0f95` | `df606ede45e58263b669f092cfaeb575becf1ea314076823b23f275a1768ae5d` |
| `plan-extract-v4` | Explicit Schema 3 partial draft + `plan-mapping-v1`, R11 | `9461d3099a923e5f9fe172eeba010e0dbe44cbe9d8f93c9465be9626d08965a1` | `e91f6b32a69a60b1f35da3e5deee5acd17d326cecd0efcadd2aa99bdb36b4eb7` |

R09 must first prove that introducing sibling v3 domain types leaves the entire v1/v2/v3 prompt-schema graph byte-identical. Keep `_render_frozen_schema` checks active. If sharing a helper changes generated titles/defaults/definitions, isolate a historical prompt model/serializer with the exact old graph or checked-in verified snapshot and keep its independent digest/tamper check; do not update existing expected digests, bypass checks, or catch the drift exception and continue. Do not widen `TradePlanDraft` inheritance to the new union.

R11 creates a separate v4 output model and parser selected by prompt version, plus explicit prompt-to-schema support tests: v1 accepts only its historical contract; v2 retains its old index allowlist; v3 cannot return Schema 3; v4 returns only the new explicit draft contract. Model output cannot choose its own prompt identity. Keep old template text, field meanings, enum ranges and parser support intact. New fields/enums must fail a deliberately mutated-schema guard test unless a new version is declared.

The existing default remains v3 during R08–R10. R11 publishes v4 as the omitted-version default after its offline gates without modifying real configuration or replacing the extraction provider/model. Old explicit version settings keep selecting their old contract. Every new v4 extraction review records prompt version, source hash, exact draft hash, semantic content hash, mapping snapshot, review-evidence hash and unresolved issues. Historical extraction rows are not recomputed or marked approved merely because new code can read them.

## Read, Write and Rollback Matrix

| Stored/input data | Read/export | New write/execute |
|---|---|---|
| Legacy Schema 1/2 | Exact old codec and hash; old evidence remains readable | Existing strict review/date rules and legacy mode; no silent migration |
| V3 partial draft | Typed inactive draft and unresolved fields | Can save only; cannot activate/execute |
| Complete reviewed V3 | Versioned codec, content/source/review/plan identities | Only when every required consumer supports explicit-rules-v1; R09–R12 implement it |
| Unknown schema/execution/result/alert version | Explicit unsupported error; preserve raw stored evidence for controlled recovery | Reject; never interpret as the nearest supported version |
| Historical backtest result | Existing immutable reader/export/retention | No in-place recomputation or rewrite |
| V3 input to legacy backtest | Recognize and explain unsupported mode | Reject research-fill run before enqueue |

Add migrations after `0012_manual_event_risk`, never edit `0001–0012` in place. Retain old hashes/rows and verify old readers in compatibility fixtures. New deployments must read old data before any v3 write is allowed. Old application binaries cannot safely read v3 data; do not run them against an upgraded database containing new variants. A rollback disables v3 and retains history, or restores an independently verified backup under a deliberately compatible binary; it never strips new fields/approvals to make an old parser pass. Downgrade must reject if it would discard v3 review, inventory, rule-state, result or event evidence. R08 performs no database migration.

## Alternatives Considered

### Add fields to legacy entry/reduction/risk

Rejected: it keeps hidden episode/TACTICAL priority and risks old prompt/schema hashes. Direct SELL and pure risk would require misleading signal names and side effects.

### Replace the entire plan/evaluation platform

Rejected: bounded sibling models and explicit dispatch reuse the existing engine helpers and atomic pipeline. No new service, language or framework is needed.

### Choose a universal repeat/conflict default

Rejected: the source omits it. Provide finite per-rule choices and unresolved fields; safe rejection remains a support limitation, not proof that the original plan executes fully.

### Treat every edit as a new source extraction

Rejected: it obscures the original source and cannot faithfully represent trusted corrections. Preserve extraction history and add current-content review binding.

## Consequences

R09 requires more than its two original M slices: compatibility, codecs, complete inventory facts, rule occurrence state, versioned results/outbox and commit fences are separate prerequisites for faithful BUY. Follow the ordered internal slices in [R08 mapping](../../remediation/R08-mapping.md); each has its own validation and focused commit. R10 finishes SELL/risk/conflicts, R11 review/extraction, and R12 ordinary forms. An incomplete stage may prove an isolated behavior but must not enable an incomplete end-to-end capability.

## Configuration and Reversal

No real configuration, provider default, plan, holding, database or credential changes in R08. New technical version names are design decisions within the approved scope; concrete trading-policy choices remain unresolved until explicit source/user evidence exists. Rollback is removal of these documentation amendments before implementation, or the non-destructive version/capability strategy above after implementation.
