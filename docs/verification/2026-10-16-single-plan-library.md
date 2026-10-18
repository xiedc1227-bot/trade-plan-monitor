# Single-plan library and live AI verification — 2026-10-16

**Correction to SPV03:** The issue counts below describe the earlier implementation, not a list of facts absent from the source. Inactive zone bounds, explicit zero holdings and preloaded opening time were software/extraction problems. See the [subsequent correction and actual-source verification](2026-10-16-source-confirmations.md).

Chinese review copy: [2026-10-16-single-plan-library.zh-CN.md](2026-10-16-single-plan-library.zh-CN.md).

## SPV01. Scope and implementation

Implemented the authorized flow: prepare one original, review and save it, link an update to an exact immutable reviewed predecessor, then combine selected reviewed entries into one continuous backtest. Existing batch records remain readable. New composition accepts 1–256 plans, orders dates on the server and rejects missing predecessors, duplicate dates/source IDs and mixed assets. Reviewed prefixes, individual approval times and the original account are preserved. Composition calls no AI and no live account is changed.

AI extraction uses independent defaults of 16384 output tokens and 120 seconds. The ordinary budget and 50,000-character configured request guard were not raised. Compact evidence references avoid repeated spans/values; the server validates every retained policy binding and exact account fact. Aggregate field references, exact `type:json_object` wrappers, redundant known account references and reverse-labelled actual holdings are handled without accepting arbitrary extra fields. An upward restoration comparison stays unknown with a material warning rather than becoming a downward risk trigger. Missing strategy and account facts are never invented.

## SPV02. Actual-source live calls

Only the four TXT originals under `data/research/shengxin-plan-extraction-20261010/` were supplied. `plans.json` and `entry-fields.json` were not used. Effective dates below were explicitly confirmed by the user. Production `ConfiguredAIWebLifecycle`, `PreparationService`, the provider adapter and durable preparation store were used in isolated verification databases. Model: `deepseek-flash` from the existing local configuration. Secrets are not included in this report.

Three development rounds made 12 real calls. Earlier failed responses were retained: round one exposed aggregate/null evidence paths and an upward risk comparison; round two exposed redundant `opening_account.inventory_quantity` bindings. The fixes were first checked against recorded responses, then round three called the real AI again with all four originals. Final local artifacts are in `data/verification/2026-10-16-single-library-verified/`; earlier rounds remain in `2026-10-16-single-library/` and `2026-10-16-single-library-final/`. Recorded response regression fixtures contain model output only.

Final round: all four HTTP responses were 200 with `finish_reason=stop`, all extraction attempts were `SUCCEEDED`, and all candidates were durably saved. Request message lengths were 42,717 / 42,050 / 43,612 / 45,536 characters. No input overflow or output truncation occurred. Total usage: 78,075 tokens. All four saved results passed public item projection validation; the source fixtures match the original TXT bytes exactly.

| Original | Confirmed effective date | Input tokens | Output tokens | Saved state | Full validation issues |
|---|---|---:|---:|---|---:|
| `01-20260924-104506.txt` | 2026-09-24 | 14,595 | 4,256 | `CANDIDATE / UNRESOLVED` | 132 |
| `02-20260928-092555.txt` | 2026-09-28 | 14,291 | 4,617 | `CANDIDATE / UNRESOLVED` | 151 |
| `03-20260930-095728.txt` | 2026-09-30 | 15,016 | 4,321 | `CANDIDATE / UNRESOLVED` | 141 |
| `04-20261009-091956.txt` | 2026-10-09 | 15,856 | 5,123 | `CANDIDATE / UNRESOLVED` | 184 |

## SPV03. Can these actual candidates continue to backtest?

Not yet. Extraction success is distinct from review readiness. These candidates still contain missing strategy parameters, unbound interpretations and unresolved source clauses. Examples include the first plan's missing maximum position, unclear independent-signal/risk-scope choices, incomplete price-zone bounds in later independent diagnostics, and the fourth upward restoration versus downward-risk interpretation. Cash and account snapshot facts remain unknown. Counts above include individual field-binding and clause-review issues, not that many independently missing business facts; public summaries remain bounded while full diagnostics are stored.

No candidate was automatically approved and no actual-source backtest was submitted. Because the first original is not yet reviewed, the later three live checks were explicitly independent diagnostic extractions. They do not certify a live AI update chain or substitute independent interpretation for a user-approved predecessor. The linked update/composition path was separately verified with complete synthetic source evidence and explicit test approvals. The actual chain requires review/correction of the first plan before later sources can be prepared as linked updates; later holdings cannot reset its account.

## SPV04. Executed checks

- Backend unit regression: 3,092 passed; 41 subsequent focused checks passed, covering update-prompt budgets, ambiguous-date saves and API snapshots.
- Preparation, review, worker, date preflight, production composition and plan-switch integration regression: 246 passed.
- Frontend: 1,041 tests passed; after adding initial-read recovery cases, all 87 targeted preparation tests passed. TypeScript and production build passed.
- API contracts: concrete new paths were added to the exact allowlist; English/Chinese U13 records both generated profile hashes. Initial failures identified the missing documentation/allowlist update and were fixed without removing the assertions.
- Final real Chrome: the other 3 scenarios passed in the previous run; after the fix, the complete four-plan journey passed separately (4.4 minutes), for all 4 scenarios passing. Checks cover legacy saved preparations, cancellation/recovery, individual uploads with ambiguous date confirmation, and four individually reviewed linked plans combined into one run. The synthetic expected result is two fills, final cash 1,019,000 fen, zero shares, fees 1,000 fen and realized P/L 19,000 fen. This is synthetic workflow verification, not a financial result for the four actual originals.

The initial browser run reached that expected synthetic result but failed its console assertion on the documented first-read `SERVICE_UNAVAILABLE`, and its cancellation assertion needed a unique status locator. A later run also found that an initial preparation GET returning 503 after reload left controls locked. Added at most 3 read-only retries, 2 seconds apart, with no repeated AI extraction and timer cleanup on unmount. The final run verifies the exact expected transient error envelope rather than suppressing other errors. Viewports 320 / 768 / 1024 / 1440 are checked for horizontal overflow in the library/result flow. No performance/load certification or live market-provider validation is claimed by these checks.
