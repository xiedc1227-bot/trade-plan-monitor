# Spec: source-treatment-review

## S01. Objective and compatibility

[One Trade Plan Workflow](SPEC-unified-plan.md) governs the current Schema 5 / `plan-extract-v9` source-review path. Full source spans, unresolved meaning, human supplements and exact source/content/revision binding remain visible. Fundamentals are generation-time review background, never runtime or simulation blockers. Source-defined trading and reminder-only clauses must retain their independent meaning; inventory prose never initializes holdings.

The finite `plan-mapping-v2`, `source-processing-v1` and `plan-review-evidence-v2` treatments below document frozen historical review decoding. They do not restore prompt v1–v7 or real-position write routes. Historical v1 snapshots/hashes retain their original interpretation; exact stored derivation must remain verifiable.

## S02. Finite treatment contract

The server derives typed records from full matching adjacent source clauses, preserving Unicode code-point spans. `INVENTORY_ASSERTION` accepts the finite grammar `<symbol>当前持仓<integer>股，均为测试日前已持有且当日可卖；` (whitespace between clauses permitted). Symbol and quantity are parameters, not fixed acceptance values. It records symbol, total/sellable source quantities, the asserted prior-test-date settlement basis and the independent inventory-confirmation route. A separate symbol subspan maps to the exact current `symbol`; quantity and settlement subspans remain visible. Source statements never create lots, opening balances, fills or known inventory.

`PRODUCT_GUARANTEE` accepts the full pair `提醒及确认收到提醒不代表成交，未登记成交时持仓不变。` and binds only to `alert-position-isolation-v1`: ordinary alerts, retries and acknowledgements do not mutate positions; only separate, explicitly authorized inventory commands can do so. That contract is implemented by the frozen explicit decision/outbox and current alert acknowledgement services and must have integration regression evidence. It is not a generic `CONTRACT` field-binding escape.

Every treatment contains its exact spans, kind, supported contract ID and deterministic treatment ID. The persisted list must equal server re-derivation on save/read/review. Arbitrary IDs, wrong quantities/symbol/sellability, negations, extra conditions, incomplete clause pairs, missing records and altered spans reject or remain mandatory unresolved issues. Full matching forbids a trading condition from riding inside an inventory/product clause. Unrecognized clauses containing the reserved families `当前持仓`, `均为测试日前`, `提醒及确认收到提醒`, or `未登记成交时` remain `UNRESOLVED_MIXED_SOURCE` even when a provider maps part to a plan field. This is a finite grammar, not a general Chinese semantic classifier. All remaining clauses keep the existing required field/structure mapping and semantic checks. No IGNORE or generic ACK bucket exists.

## S03. Content review and independent inventory

Source quantities remain exact integers in `0..9007199254740991`; do not round or lose Web precision. Both finite treatment kinds require `CONFIRM_SOURCE_TREATMENT`, bound via `binding_path=source_processing.treatments[index]` to the exact server-required issue/snapshot. Confirming an inventory assertion acknowledges the source and its independent inventory boundary, never ledger truth.

Current review can complete only when every mandatory omission, binding and supported human supplement is resolved against the saved version. Extraction, save, review and acknowledgement do not activate a plan or create inventory. Activation is explicit and separately validated. Current simulated inventory is initialized through `/api/v1/simulation-position-confirmations`, queried through `/api/v1/simulation-position-inventory`, and changed by an eligible `/api/v1/simulated-trades` command. Frozen actual-position readers and research records remain separate. Reminder-only rules do not require simulation inventory authority.

## S04. Persistence, API and identity

Reuse existing immutable versions, JSON mapping storage, issue/resolution records and transactional revision checks. No schema migration or inventory write is needed for a source treatment. New `plan-review-evidence-v2` hash includes the complete v2 mapping/processing snapshot, supplement values/times and mandatory issues. V1 hash preimages remain unchanged. Edits require exact new-version confirmation; old hashes, old treatment identities, forged resolved lists and tampered stored processing fail closed. Plan detail and save return typed camelCase processing records for compatible readers without inventing classifications.

V2 `REPLACED_BY_REVIEWED_CONTENT` is a requirement to save a new supported version, never a same-snapshot acknowledgement. An orphan supplement cannot discharge an unresolved source issue. Submitted invalid mappings return 422; corrupted stored evidence returns the existing secret-free 500 `INTERNAL_ERROR`. Source mapping confirmations remain human semantic decisions, not automatic proof that arbitrary prose means the submitted trading rule.

## S05. Acceptance

Keep deterministic regressions for exact Unicode spans, literal source values, source-only omissions, mixed supported/unsupported clauses, negation/extra-condition rejection, forged or missing treatments, orphan supplements, stale hashes and unresolved semantic mappings. Human review is not automatic proof of arbitrary natural-language meaning. Verify current formal review/activation and inventory APIs independently from frozen decoder tests; alerts/acknowledgements leave holdings unchanged. Use temporary SQLite and HTTP mock transports, with no live provider calls. The latest executed scope is in [local acceptance](../../verification/2026-10-03-unified-plan.md).
