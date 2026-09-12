# Spec: source-treatment-review (R11 mixed-source completion)

Canonical English; `SPEC-source-treatment-review.zh-CN.md` is the equivalent Chinese copy. Date: 2026-09-12. Authorized correction to R08 C01/C02/C09/C10 and E04/E07; see ADR 0006.

## S01. Objective and compatibility

Complete the existing source → partial draft → current-content review workflow for mixed trading, inventory and product-boundary prose. Keep `plan-extract-v1/v2/v3/v4` output graphs, templates and frozen digests unchanged. New API saves use `plan-mapping-v2` with a server-derived `source_processing` snapshot (`source-processing-v1`). V4 extraction still returns `plan-mapping-v1`; this is a server review extension, not a new model-output permission. Historical v1 review snapshots keep their original interpretation and evidence hash.

## S02. Finite treatment contract

The server derives typed records from full matching adjacent source clauses, preserving Unicode code-point spans. `INVENTORY_ASSERTION` accepts the finite grammar `<symbol>当前持仓<integer>股，均为测试日前已持有且当日可卖；` (whitespace between clauses permitted). Symbol and quantity are parameters, not fixed acceptance values. It records symbol, total/sellable source quantities, the asserted prior-test-date settlement basis and the independent inventory-confirmation route. A separate symbol subspan maps to the exact current `symbol`; quantity and settlement subspans remain visible. Source statements never create lots, opening balances, fills or known inventory.

`PRODUCT_GUARANTEE` accepts the full pair `提醒及确认收到提醒不代表成交，未登记成交时持仓不变。` and binds only to `alert-position-isolation-v1`: ordinary alerts, retries and acknowledgements do not mutate positions; separate position commands do. That contract is implemented by the existing explicit decision/outbox, alert acknowledgement and position services and must have integration regression evidence. It is not a generic `CONTRACT` field-binding escape.

Every treatment contains its exact spans, kind, supported contract ID and deterministic treatment ID. The persisted list must equal server re-derivation on save/read/review. Arbitrary IDs, wrong quantities/symbol/sellability, negations, extra conditions, incomplete clause pairs, missing records and altered spans reject or remain mandatory unresolved issues. Full matching forbids a trading condition from riding inside an inventory/product clause. Unrecognized clauses containing the reserved families `当前持仓`, `均为测试日前`, `提醒及确认收到提醒`, or `未登记成交时` remain `UNRESOLVED_MIXED_SOURCE` even when a provider maps part to a plan field. This is a finite grammar, not a general Chinese semantic classifier. All remaining clauses keep the existing required field/structure mapping and semantic checks. No IGNORE or generic ACK bucket exists.

## S03. Content review and runtime readiness

Source quantities are exact integers in `0..9007199254740991`, never rounded to board lots; larger values remain unresolved instead of crossing the Web boundary with lost precision. This bound does not waive the independent registration endpoint's own rules.

Both kinds require `CONFIRM_SOURCE_TREATMENT`, bound via `binding_path=source_processing.treatments[index]` to a server-required issue and exact snapshot. For inventory, this confirms the extracted assertion and its routing to independent registration, **not ledger truth**. Its visible instruction is to choose an as-of date, register/identify the full ledger, and confirm through `POST /api/v1/position-inventory-confirmations`. Date, activation, repeat, conflict and volume history policies remain explicit human choices. Source-only missing choices never get a reviewId.

After all current mappings, treatments and supplied policies are reviewed, a complete draft obtains a valid reviewId and content `canActivate=true`. The public activation endpoint still rejects under R12's forms capability gate. `executionReadiness=NOT_EVALUATED` explicitly remains separate: consumers query `GET /api/v1/position-inventory?symbol=...&asOfTradeDate=...`; no independent confirmation means UNKNOWN and null quantities, blocking only dependent BUY/SELL. Pure RISK_ALERT does not require inventory. Content review does not expire when actual holdings change; runtime consumes the current ledger revision/cutoff on every evaluation. A registration, retry or new-key reconfirmation must never double-count the same opening balance.

## S04. Persistence, API and identity

Reuse existing immutable versions, JSON mapping storage, issue/resolution records and transactional revision checks. No schema migration or inventory write is needed for a source treatment. New `plan-review-evidence-v2` hash includes the complete v2 mapping/processing snapshot, supplement values/times and mandatory issues. V1 hash preimages remain unchanged. Edits require exact new-version confirmation; old hashes, old treatment identities, forged resolved lists and tampered stored processing fail closed. Plan detail and save return typed camelCase processing records so R12 can render them directly without inventing classifications.

V2 `REPLACED_BY_REVIEWED_CONTENT` is a requirement to save a new supported version, never a same-snapshot acknowledgement. An orphan supplement cannot discharge an unresolved source issue. Submitted invalid mappings return 422; corrupted stored evidence returns the existing secret-free 500 `INTERNAL_ERROR`. Source mapping confirmations remain human semantic decisions, not automatic proof that arbitrary prose means the submitted trading rule.

## S05. Acceptance source and verification

A new fixture stores the coordinator-provided literal Chinese source, including line breaks. The sole substitution is `测试股票` → `003043.SZ`, recorded explicitly beside the source. Earlier `_ORIGINAL_SOURCE` is a derived shorthand fixture, not that literal source; retain its historical tests and correct its description.

Verify source-only missing choices; completed current review and public activation denial; independent inventory UNKNOWN → known100 with idempotent retry/reconfirmation; risk with unknown inventory; alerts/acknowledgements leave holdings unchanged; extra conditions/negations/wrong values/omitted clauses/treatments/contract forgery and stale reviews. Preserve 69 prior focused tests and frozen golden checks. Use `.venv/Scripts/python.exe -m pytest` with the new targeted files plus existing AI, plan API, inventory and explicit runtime groups; do not run long capacity suites. Run `.venv/Scripts/python.exe -m ruff check` on changed files and `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`.

## S06. Implementation order and boundaries

1. Typed server processing and finite recognition; focused adversarial unit tests.
2. Versioned review issues/hash, persistence/API integration, exact complete-source acceptance.
3. Relevant compatibility/runtime regressions, generated API contract, bilingual report and handoff.

Use existing Python 4-space/snake_case conventions and strict Pydantic boundary models. Keep domain recognition under `ai/`, transport under `web/`, durable resolution validation under `state/`; add no dependencies. Only synthetic data and temporary SQLite. No live AI/market/network/notification/trading/production data, push, R12 task or forms. Stage only this correction, preserving existing user hunks.
