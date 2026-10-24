# Specification: market-linkage-workflow

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).

## WF01 — Objective and compatibility

Deliver the four policy modules through the real one-plan workflow and isolated replay. New linked plans use the approved Schema 6 / `condition-plan-v2` contract from MLP-D01. Existing Schema 5 fixed-quantity plans continue unchanged; Schema 1–4 historical decoding/replay retains its original bytes/hashes. No auto-upgrade of saved/active plans, no extra UI plan-type selector and no second workflow.

Contract task MLP-T01 must inventory exact persisted, extraction, preparation/update, API, runtime, notification and replay readers/writers. It must define versioned canonical payloads, digests and compatibility fixtures before dependent implementation. A reader lacking the new capability rejects a new linked payload explicitly instead of dropping fields. A rollback may disable new linked activation, but must preserve new evidence and legacy operation; it cannot reinterpret a new policy as fixed quantity. Database changes are additive and tested on temporary databases before any separately authorized user-database upgrade.

## WF02 — Extraction and review

Only source-authorized linkage produces `market_policy` and `quantity_policy`. Extract or bind the complete market-state definitions, relative-strength definition, S0/S1/S2, Q0, factors, quantity rules and P1 exception boundaries. The preset version names an expanded policy; naming a preset never excuses missing strategy provenance. Source interpretation, literal extraction and product constants stay distinguishable. The server derives board identity, verifies it against the stock and binds the derivation; AI cannot select an alternate benchmark.

AI returns a draft and evidence, never approval. The review must show actual policy values, all route effects, omissions and proposed source interpretations. Missing Q0, S0 definition, necessary operator/window, incorrect timing, mixed fixed/policy quantities, dropped restrictions and fabricated human facts block complete review. Fully represented scoped technical facts may remain unknown at runtime. The two P1 exception rows may remain explicitly disabled in an otherwise complete plan; deleting their meaning is forbidden.

Current source text, candidate content, policy/formula versions and evidence revisions bind the review. Editing any of them invalidates approval. Save does not activate; activation is explicit. Success of AI transport/JSON parsing does not mean a plan is executable. Preserve precise processing-error versus business-question diagnostics.

## WF03 — API, UI and runtime

Extend existing operation families: `/api/v1/plan-extractions`, `/api/v1/plan-drafts`, `/api/v1/plan-review-previews`, `/api/v1/plan-review-confirmations`, `/api/v1/plan-activations`, `/api/v1/plan-runtime/{symbol}` and `/api/v1/simulated-trades`. No new endpoint is required by this proposal. The contract inventory must record additive request/response variants and required generated OpenAPI/TypeScript changes before implementation. All authority remains server-side.

The `/plans` review and runtime views show: reference index/date, actual market operands/state, stock/index returns and strength predicates, selected S0/S1/S2, Q0/factor/candidate/frozen quantity, remaining capacity, reasons and evidence time. Explain calculation versus authority; display zero authorized quantity without offering a zero-share trade. Differentiate pending review, unsupported meaning, missing data, unmet conditions, P1 exception block, expired signal and insufficient capacity. Hide technical schema identifiers from ordinary user flows.

Production composition must request the exact stock/index evidence required by the active rule, share compatible index requests, respect existing worker limits and recovery, and bind completion proofs to both evidence sets. Unlinked reminders remain independent of missing indexes and simulation inventory. No network I/O in database transactions. A changed activation, plan, review, source revision or required fact rejects stale computation and queued reminder eligibility. Explicit full-quantity simulation rechecks current quote, calendar, tradability, T+1, CORE, risk, inventory revision, limits, signal and idempotency atomically.

## WF04 — Replay, evidence and bounds

Replay freezes source versions, policy definitions, calendars, stock/index datasets and adjustment/fact revisions. It invokes the same classifier, strength, selection and sizing functions as live monitoring, with the same cutoff rules. Do not reuse a current informational index head as historical evidence. Add index dependencies to replay admission rather than silently omit them; unavailable historical calendars/providers reject the dependent scope honestly.

Record each decision's consumed evidence, selected route, conditions, Q0, factor, candidate and authorized quantity, capacity, reasons and signal identity. Record zero-trade outcomes with causes. Future source changes cannot alter prior event identities. Existing single-job exclusion, cancellation, atomic result publication, data retention and runtime limits remain. Targeted acquisition should fit existing 500 daily-observation, 50-leaf, depth-4 bounds; requirements beyond them fail explicitly.

## WF05 — Acceptance and verification

| ID | Required evidence |
| --- | --- |
| WF-A01 | Real extraction/review service accepts a complete linked candidate and rejects omitted dependencies, malformed values, fake approval and unsupported linkage; no silent strategy repair. |
| WF-A02 | All old byte/hash fixtures remain exact; old readers reject new formats explicitly; reopening and rollback preserve stored evidence. |
| WF-A03 | Actual production composition, recovery, completion-proof reads, activation races and send-time notification admission consume the correct paired evidence. |
| WF-A04 | One browser journey prepares, edits, reviews, saves, explicitly activates and inspects a linked plan; independent reminders and explicit simulation remain correctly isolated. |
| WF-A05 | Identical frozen scenarios produce identical policy decisions in live adapters and replay; future mutations cannot change earlier results; all six route rows have evidence. |
| WF-A06 | Full focused/regression/build checks pass; bilingual docs, generated contracts and verification report match implemented capability and distinguish local evidence from live certification. |

Implementation files span `ai`, `domain`, `state`, `monitoring`, `web`, `backtest` and existing Vue workspace. Implement in the small sequential slices of [tasks](../../../tasks/market-linkage-p0.md); do not edit all subsystems in one task. Follow MLP07 commands and existing style. No new dependencies or production operations are included in this scope.
