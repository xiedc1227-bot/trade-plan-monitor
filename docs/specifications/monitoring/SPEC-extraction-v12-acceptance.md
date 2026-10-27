# Specification: extraction-v12-acceptance

Status: APPROVED FOR IMPLEMENTATION — 2026-10-27. Module of [plan-monitor-assurance](SPEC-plan-monitor-assurance.md), dependent on [source-condition-coverage](SPEC-source-condition-coverage.md). This document runs no AI service. [Chinese copy](SPEC-extraction-v12-acceptance.zh-CN.md).

## EVA-S01 — Purpose and evidence classes

Evaluate whether the exact current extractor produces a complete, faithful, reviewable monitoring candidate from full trading-plan sources. Do not infer extraction accuracy from a schema accepting a preconstructed response or from runtime/backtest tests passing.

Report evidence classes separately: `SYNTHETIC_TRANSPORT` (mock/memory Provider), `RECORDED_RESPONSE_REPLAY`, `REAL_PROVIDER_EXTRACTION`, and `REAL_INSTALLATION_READINESS`. A test named “real extraction” using a prebuilt `RawAIResponse` remains transport/contract evidence. Existing v9 alert-only observations are historical references, not current v12 full-plan acceptance or a population success-rate estimate.

## EVA-S02 — Frozen corpus and independent truth

Freeze12 source cases before provider execution. The manifest owns case ID, source origin, original/redacted source hashes, exact source text and A/B boundaries, language, predecessor if applicable, prompt/version/hash, expected plan family, expected `PASS_FOR_HUMAN_REVIEW` or `BLOCKED`, required atomic obligations/relations, permitted product defaults, allowed scope exclusions, expected human-only steps and per-case resource configuration. Keep originals unchanged. Redact credentials/account identifiers before approved external transmission; redaction must not remove strategy clauses or alter thresholds. Preserve a local redaction record without secrets in committed evidence.

Include at least4 original user-source cases and4 natural-language cases in total, allowing overlap; at least one original case must be a complete supported trading plan expected to pass. Distinguish `ORIGINAL_NATURAL_LANGUAGE`, `CONSTRUCTED_NATURAL_LANGUAGE` and `FIELD_FORMAT_A` and report each separately. If available originals are only reminder/unsupported plans, prepare the remaining samples and request a concrete source/truth decision; do not relabel synthetic or field-format cases as real trading originals.

Truth is prepared independently of extraction output and `source_mapping(draft)`. Independently review its atom spans, polarity, graph, periods, windows, quantities, permissions, blockers and source boundaries before freezing. The extraction provider cannot be its own judge. Ambiguous actual-source intent is resolved by the user before running that case; model voting is not truth. Corrections after viewing responses create a new manifest revision and retain earlier results; no silent case replacement or reclassification to make a failure expected.

## EVA-S03 — Required12-case matrix

| ID | Required content | Expected outcome / independent oracle |
| --- | --- | --- |
| PMA-X01 | Schema5 observation-only price/technical alert, explicit no ordinary or liquidation rules | Reviewable reminder only; zero invented BUY/SELL, no inventory/capital requirement |
| PMA-X02 | Schema5 BUY/SELL and technical risk, mixed ALL/ANY, daily and independent five-minute branches, explicit dates | Exact graph, direction, scope, cycle/offset, quantity and validity; risk/reminder distinction preserved |
| PMA-X03 | Schema6 board-derived index, four market states, aligned5/20-session strength and S0/S1/S2 | Complete source policies, fixed Q0 intent, no inferred exception permission |
| PMA-X04 | Schema7 both explicitly permitted exception routes | Exact minimum condition and separately entered Qe; permission never becomes occurrence approval/default Qe |
| PMA-X05 | Schema8 ATR14/close contiguous tiers and PREVIEW_ONLY economics | Exact tiers/base/units, Q0 derivation before market factor, preview never converted to a gate |
| PMA-X06 | Schema8 REQUIRED economics with explicit fees, gates, target/risk and independent evidence | Exact fees/thresholds/evidence; no invented fee defaults or duplicate evidence dimensions |
| PMA-X07 | Schema9 OPEN_COST_CAP plus CAPITAL_ONLY and explicit applicable buy-cost schedule, including economics NONE | No fake max_qty/cash/opening costs; retained-cost meaning and whole-quantity constraint preserved |
| PMA-X08 | Schema9 MARKET_VALUE_CAP plus QUANTITY_AND_CAPITAL | Exact all-holdings valuation and share ceiling; no historical-cost prerequisite or amount-derived quantity |
| PMA-X09 | Mixed A/B, historical/account/background and forward instructions, negation, exception and expiry | Only proven context excluded; every forward remainder/relation retained; moving a mandatory condition from A to B causes a partition conflict, not omission or unauthorized B execution |
| PMA-X10 | Mandatory turnover>3% or another explicitly unsupported prerequisite; independent omission/background-label mutations include same-sentence partial mapping | Unsupported obligation visibly blocks; no “background” waiver or passing partial graph |
| PMA-X11 | Missing mandatory parameter, contradictory cycle/window or ambiguous monetary meaning | Visible exact blockers, preserved incomplete candidate; no inferred parameter or older-schema downgrade |
| PMA-X12 | Follow-up update with a frozen reviewed predecessor | Unmentioned obligations/permissions preserved, stated changes exact, old source/review binding invalidated |

X01–X09/X12 use complete sources for declared supported positives; X10/X11 are predetermined blocking cases. Mutations are additional offline oracles, not extra calls secretly added to the real budget. Cover Chinese and English, raw/normalized line endings, compact and prose sources across the corpus without claiming equivalent natural-language difficulty.

## EVA-S04 — Versions, attempts and external authorization

Baseline is the exact `plan-extract-v12` instruction/template/output-schema contract, pinned by a contract hash and each complete assembled prompt SHA-256, provider/model identifier, secret-free configuration, input/output bounds and server coverage rules version. Different source/case/predecessor payloads naturally produce different assembled hashes and do not themselves change the instruction version. Changes in the server coverage guard are recorded independently. Do not call revised instruction/template/schema content v12. If implementation genuinely needs a new prompt/output version, assign the next owned version at T01/T15 and report baseline and deployed candidate separately.

Subject to approved PMA-D05 plus explicit implementation instruction: run each of12 cases twice, retaining all24 planned baseline outcomes. If instruction/template/schema bytes remain v12, do not waste a second set merely to fill budget. If those contract bytes change, a separate12×2 candidate set is required; total physical provider attempts across both sets is at most48. Disable automatic retries, including SDK/transport retries. Timeouts, provider errors and incomplete responses consume attempts when a request was sent. Local preflight rejection makes that planned case fail without pretending a provider call occurred. No hidden “best of” selection or failed-run replacement. Additional attempts, a different service/judge or further prompt revisions beyond this budget require approval.

Atomically reserve an attempt in the shared campaign ledger before sending. Concurrent commands and process restart cannot reset or overspend the48 ceiling. Crashes, timeouts and uncertain delivery never refund a reserved send; only a local preflight with proven zero I/O is not a physical attempt. Keep planned-run, reserved-send and received-response counts separate.

Use the existing configured extraction service, no new account/model shopping. Keep current resource/admission settings in the frozen manifest, including the existing50000-character default input budget where applicable; do not truncate source, remove bindings, raise limits or change expected positives merely to pass. If a full plan cannot fit or complete under the declared configuration, record that capability/resource failure and present any proposed limit/cost change for review. Capture cancellation/timeout honestly; a transport timeout is not proof that no request reached the provider.

All response artifacts and grading occur in a dedicated isolated acceptance directory/store. No actual plan save/review/activation, inventory/capital mutation, migration, market acquisition or notification sending is part of these extraction calls. Commit only approved redacted evidence; never provider keys, full sensitive configuration or unapproved original material.

## EVA-S05 — Scoring and signoff

For every planned run record raw response/protocol result, exact version/hashes, finish reason, physical attempt count, elapsed time and available usage; unavailable usage is null. Preserve original response and failure diagnostics. Score independently before any repair:

- Mandatory atom recall and relation correctness: missing atom, wrong AND/OR, negation, date, unit, cycle/offset, quantity, permission or occurrence counts as a semantic failure even if parsing/review succeeds.
- Unsupported/ambiguous cases: whether the expected precise blocker appears and prevents new review/activation, while a valid incomplete candidate remains visible.
- Inventions: unrequested condition, price, quantity, fee, approval, inventory/budget basis, or new authority outside the finite product defaults is a failure.
- Complete supported positives: whether they are reviewable without manual correction; unjustified blocking is recorded as a false block, not converted into a safe success.
- Separately report parse/provider/truncation failures, correct blockers, raw automatic passes, human-assisted passes and every changed field/source. Assisted passes never replace the original automatic outcome.

Signoff requires zero silent mandatory omissions, inventions or relation changes in the frozen matrix, correct blocking of X10/X11 and complete supported positives passing under the declared budget/configuration. Report numerators/denominators by source origin, case and repeated run; no adding overlapping synthetic/replay tests. Failed v12 baseline results remain failures even if a later deployed version passes. If the deployed version is different, acceptance is explicitly for that version; do not claim v12 itself was fixed without changed, versioned evidence.

These thresholds apply only to this finite reviewed corpus. They are not statistical proof of arbitrary-plan100% accuracy, trading profitability or real-installation monitoring readiness. A fully annotated corpus and working grader without the actual provider runs is `REAL_ACCEPTANCE_PENDING`, not completed acceptance.

## EVA-S06 — Required artifacts and implementation seams

`extraction-acceptance-v1` owns a manifest, immutable per-run index, original responses, independent obligation-level scores, all failures/rechecks, actual attempt ledger and bilingual report. Bind report conclusions to source/prompt/model/config/rules hashes and code revision. Approval or a screenshot cannot replace the evidence index. A stored replay proving the new coverage blocker is useful regression evidence and remains labeled replay.

Suggested seams: `tests/fixtures/plan_assurance/` redacted sources/truth, focused offline corpus/grader tests, a bounded explicit real-run entry under `scripts/`, and `docs/verification/` report pair plus neutral evidence assets. Acceptance: PMA-A01/A02,A07/A08,A12; operations remain gated as in PMA-D05. This draft creates none of those executable fixtures/scripts or real-run artifacts.
