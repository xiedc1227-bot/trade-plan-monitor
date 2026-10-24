# Market linkage P1 operations

[Chinese review copy](market-linkage-p1.zh-CN.md) · [Specification](../specifications/monitoring/SPEC-market-linkage-p1.md) · [Tasks](../../tasks/market-linkage-p1.md) · [Verification](../verification/2026-10-24-market-linkage-p1.md)

## MLO1-01 — Plan permission and occurrence approval

Use `/plans`: source → `plan-extract-v10` draft → source review → save → confirm review → explicit activation. Schema 7 / `condition-plan-v3` / `market-linkage-v2` requires `REVIEW_PER_OCCURRENCE` and separate `WEAK_MINIMUM` / `BROKEN_STRONG` permissions, each `DISABLED` or `PER_OCCURRENCE`. Preserve complete source bindings for market, strength, S0/S1/S2, quantity and authorization definitions. Missing definitions or mixed fixed/policy quantities block complete import/review. Do not infer permission from a version label. Schema 5 remains fixed-quantity; Schema 6 keeps `BLOCK_P1` and cannot acquire exception approval.

Plan review enables a route only. Each independent occurrence starts `PENDING`; AI extraction, plan activation, verified facts, reminders, acknowledgement and reopening the app cannot approve it. All P0 market/strength/confirmation and [official quantity-grid](market-linkage-p0.md#mlo02--official-quantity-rules) gates remain applicable.

## MLO1-02 — The two quantity rules

Let Q0 be the explicit source base quantity, m the official minimum, s the official increment, and capacity the currently remaining reviewed position capacity. Simulation still requires a positive multiple of 100 shares.

| Route | Conditions | Quantity and examples |
| --- | --- | --- |
| `WEAK_MINIMUM` | WEAK, STRONG, S1, route enabled; `0.5*Q0 < m <= Q0` | The only proposed quantity is exactly m, read-only. Main-board Q0=100 and m=100 permits 100; STAR Q0=300 and m=200 permits 200. Q0=400 and m=200 is an ordinary WEAK order, not an exception. An incompatible minimum never becomes an upward substitute. |
| `BROKEN_STRONG` | BROKEN, STRONG, S2, route enabled | Enter Qe explicitly; the field starts empty. Require `0 < Qe <= Q0`, `Qe <= capacity`, `Qe >= m`, `(Qe-m) % s == 0`, and `Qe % 100 == 0`. For Q0=500/capacity=400, 300 is possible; empty/0/150/500 is rejected. There is no half/full default. |

Both routes require known evidence, no blocking higher-priority risk and capacity for the entire quantity. Approval freezes the quantity; later capacity loss blocks the whole trade, and recovery never resizes it. Ordinary sizing still floors downward.

## MLO1-03 — Review, approve, revoke and simulate

1. Open the current candidate and inspect the route, original decision session, consumed evidence, official grid, next exchange session and expiry. Supply a concrete reason. For `BROKEN_STRONG`, enter the exact quantity.
2. Request a server preview. Approve only that exact preview and revision, or reject the occurrence. Stale evidence/quantity/revision requires a fresh preview; an uncertain retry retains the command identity.
3. Approval changes authorization only. Separately confirm the offered whole simulated buy. The server rechecks current authority, quote/tradability, inventory, capacity, risk and the original execution window in the same transaction that consumes approval and records inventory/receipt.
4. Revoke an unconsumed approval with a reason if required. Rejection, revocation, expiry, invalidation and consumption are terminal. A new date, route change, clone, correction or retry cannot reopen that occurrence; only the existing independently verified reset/new-event policy can create another opportunity.

The execution window is the next exchange session after decision D, expiring at 15:00 Shanghai time. Late evidence/approval never extends it. Unknown or corrected calendars block the old window. Receipt time is server-owned. Changes to consumed facts/basis, plan/review, activation or required rule identity invalidate authority; harmless receipts or equivalent numbers do not. Temporarily absent required sources block execution until revalidated. Risk-blocked closes cannot reset a pending candidate.

Command families: `POST /api/v1/plan-exception-previews`, `POST /api/v1/plan-exception-decisions`, `POST /api/v1/plan-exception-revocations`. Use the generated contracts for exact fields, digest/revision bindings and error variants. No request may supply an executable grant directly.

## MLO1-04 — Frozen research

Schema 7 research uses `backtest-run-v8`. Single research takes `unified-research-input-v2`; prepared single/scheduled/workbench loop requests accept `exceptionProgram` containing `exception-replay-program-v1`. Each `frozen-exception-event-v1` retains the original candidate, v2 evidence, immutable event, exact plan hash, provenance, order and envelope hash. The worker uses only the frozen input and its private account, never current local approvals.

- `RECORDED_LOCAL` identifies supplied local-event evidence; `RESEARCH_SCENARIO` identifies an explicit hypothetical event. Result displays retain the distinction; neither is exportable as a live grant.
- No supplied event means no exception authority. Approval alone means no exception fill, including with `FOLLOW_REMINDERS`. An independent explicit operation script is mandatory.
- Source events before research start are rejected. Select a start that includes the evidence and authorization timeline. Future events apply at their original receipt time, without changing earlier decisions. A consumed event only verifies a prior private execution; it does not create one.
- Single research retains explicit simulation-at-time behavior. A loop operation is a request at `at`, requiring a current eligible exception reminder; execution follows `NEXT_ELIGIBLE_MINUTE_CLOSE` and configured response delay. Both retain the original session window and whole quantity.
- Persisted results bind source outcomes and operation requests to the frozen input and audit. Repeated signal evidence uses verified same-decision references without raising the existing 32 KiB item limit.

The UI does not invent or auto-export an event script. Advanced frozen input uses the typed API. Original schemas/hashes remain readable; unknown versions reject rather than downgrade.

## MLO1-05 — Local operation and limits

Additive migration `0026_market_exceptions` stores candidate/event kinds and unique command identity. Back up before an authorized user-database upgrade; implementation acceptance uses temporary databases only. Downgrade refuses when exception records exist. Older readers must preserve new bytes and block unsupported operations.

P1 remains local monitoring and isolated simulation, with no broker orders or automatic human approval. Official quantity rules are used directly within their recorded date/security scope; unsupported historical scope fails closed. Offline acceptance does not certify live provider availability. Exact completion status, test counts and any remaining limitations are in the verification report.
