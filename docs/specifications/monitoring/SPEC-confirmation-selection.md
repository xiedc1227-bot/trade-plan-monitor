# Specification: confirmation-selection

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).

## CS01 — Objective and boundary

Select exactly one market-linked BUY route using `market-regime`, `relative-strength` and existing individual-stock conditions. The source must explicitly authorize the linkage policy and its complete definitions. Unlinked rules acquire no implicit index dependency. P0 linkage uses `OFFICIAL_DAILY_CLOSE` and `NEXT_EXCHANGE_SESSION_ONLY`; linking a five-minute confirmation is unsupported, not silently converted.

## CS02 — Confirmation definitions

S0 is the complete reviewed stock entry condition: region, price/volume or candle criteria, technical auxiliary evidence, explicit ALL/ANY, confirmation and independent-signal semantics. These are source-specific; no threshold may be inferred from the S0 label. Unquantified technical judgments retain scoped REVIEWED_FACT authority, never an AI-created truth. Missing definitions block review; fully defined but unverified technical facts remain runtime unknown.

S1 is ALL of: adjacent valid exchange sessions D-1 and D close in the low-buy region; D close >= D-1 close; complete S0 holds at D; D volume <= mean volume of the previous 20 sessions excluding D; D RSI14 > D-1 RSI14; no higher-priority risk. Required histories, indicator warm-up and source date alignment must pass. Suspended/missing sessions do not become an adjacent observed-bar pair.

S2 is S1 AND each of the two closes >= its own day's MA20. D-1 must not be compared with D MA20. S0 unknown or incomplete cannot become a complete S1/S2 pass. Preserve the plan's requested labels and definitions; do not silently rename levels.

## CS03 — Closed route table

| Market / route | Confirmation | Quantity ceiling | P0 result |
| --- | --- | --- | --- |
| NORMAL_TRANSITION | S0 | Q0 | Eligible only after conditions and remaining gates pass |
| WEAK with an ordinary legal reduced quantity | S1 | 0.5 * Q0 | Eligible only after conditions and remaining gates pass |
| WEAK with reduction below the minimum legal quantity | S1 plus STRONG for exception eligibility | No ordinary quantity | `P1_EXCEPTION_REQUIRED`; no upward rounding, even if eligible |
| BROKEN and NOT_STRONG | None | 0 | `MARKET_BROKEN` |
| BROKEN and STRONG | S2 for exception eligibility | No approved exception quantity | `P1_EXCEPTION_REQUIRED`, including when S2 passes |
| UNKNOWN or necessary route inputs unknown | Undetermined | 0 authorized | `MARKET_INPUT_UNKNOWN` |

BROKEN with strength UNKNOWN follows the last row. NORMAL_TRANSITION and ordinary WEAK do not require relative strength, so irrelevant strength gaps must not block them. Evaluate required predicates lazily while retaining evidence for every consumed fact. Ineligible exception conditions may also list their unmet/unknown reasons; P1 authorization still remains absent.

To keep dependencies acyclic, the route selector reads `ordinary_quantity_available` from a shared pure domain preflight over reviewed Q0, the route factor and verified market/simulation quantity rules. This preflight returns only arithmetic feasibility, never inventory eligibility or trading authority. The quantity policy reuses the same helper after route selection; neither module calls the other's evaluator. Unknown preflight inputs follow the last row.

## CS04 — Signal lifecycle

Condition groups are alternative eligibility routes for one ordinary rule, not separate orders or tranches. Confirm only after the selected group's evidence is satisfied. Bind the selected route, signal occurrence, plan/review revision, evidence set and final quantity. Reuse existing independent-signal, deadline, reset and ordered-tranche policies; moving between routes or changing the date is not an independent signal.

A valid unchanged signal retains its original next-session execution window. An adverse technical risk invalidates ordinary authority according to existing risk rules. A changed/corrected consumed fact invalidates the pending linked signal; no automatic resize, backdated reconfirmation or automatic restoration after improvement. A new signal requires the original reviewed independent event/reset semantics. Plan updates follow existing replacement/retention rules and never transfer authority just by reusing an ID.

## CS05 — Acceptance and verification

| ID | Required evidence |
| --- | --- |
| CS-A01 | Each S1 component and each own-day S2 MA comparison can independently fail; incomplete/unknown S0 never becomes a pass. |
| CS-A02 | Every route-table row, irrelevant strength gaps and BROKEN/UNKNOWN combination yields exactly one specified route. |
| CS-A03 | Both exception routes retain a P1 block even with STRONG and S1/S2 satisfied. |
| CS-A04 | Switching routes, restarting or correcting one day's data does not create a duplicate independent signal or extend its window. |
| CS-A05 | Risk overrides entry; unchanged valid signals avoid an added waiting day; missing meanings and five-minute linkage fail review visibly. |

Implementation files: `decision/confirmation_selection.py`, shared unified lifecycle seams and focused tests. Verification command from `trade-plan-monitor/`: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_confirmation_selection.py tests/integration/test_market_linkage_runtime.py -q`. Follow MLP07, with deterministic scoped facts and exact event sequences.
