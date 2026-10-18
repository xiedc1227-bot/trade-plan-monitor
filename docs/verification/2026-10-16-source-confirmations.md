# Source confirmations and actual AI verification — 2026-10-16

Chinese review copy: [2026-10-16-source-confirmations.zh-CN.md](2026-10-16-source-confirmations.zh-CN.md).

## SCV01. Scope and fixes

Implemented [SC-01–SC-03](../../tasks/source-confirmations.md) within the existing “prepare one, combine reviewed plans” workflow. Explicit zero holdings are recovered from valid original evidence when AI omits them or supplies an invalid span; hypothetical zero and conflicting positive holdings remain unresolved. Unique explicit maximum-position statements and labelled observation ranges can be recovered without asking users to repeat them. Disabled ranges need no boundaries. A repair threshold is not a stop; evaluation-only language is not a purchase order; the first lot is once-only and the second waits for the first complete fill.

Fixed price constants no longer require invented quotation dates, including during runtime evidence evaluation. Valid repeated citations for the same field are merged; unknown citations remain rejected. Source interpretation is labelled separately from literal evidence and still needs whole-plan review. Original clauses, optional suggestions and context remain visible. Unmapped independent buy/sell instructions cannot be absorbed into another order's predicate or an empty order list. Qualitative restrictions can remain unresolved reviewed predicates; they are never self-attested as satisfied.

The UI separates automatically determined information, consolidated business questions and processing diagnostics. It does not request internal enum/path supplements for these four sources. A confirmed effective date supplies the simulation opening time without inventing a document/account timestamp. For an explicitly empty initial account, the user can configure cash once in the review form. Alternatively, explicit review can preserve unknown cash and its buy restriction. Cash alone no longer blocks policy review or causes a reviewed predecessor to be re-extracted. Missing policy parameters still block approval, and later sources cannot reset the account.

## SCV02. Actual sources and real calls

Only the four TXT originals in `data/research/shengxin-plan-extraction-20261010/` were used. Their fixture copies preserve the original bytes. `plans.json` and `entry-fields.json` were not inputs. Dates below were confirmed by the user. The user explicitly authorized sending these originals to `api.deepseek.com`, using configured model `deepseek-flash`. No credentials are included in artifacts or this report.

This repair session made 18 real calls across four four-source development rounds and two targeted repeats. All HTTP responses were 200 with `finish_reason=stop`; there was no request overflow or output truncation. Earlier semantic failures were retained rather than counted as extraction successes. Latest real responses come from `data/verification/2026-10-16-source-confirmations-live-check/` (sources 2 and 4) and `2026-10-16-source-confirmations-targeted/` (sources 1 and 3). Those latest four used 80,140 tokens in total.

The last live first-source response still cited a conditional cancellation for a recovered observation range. The final repair relocates that binding to the exact labelled table row. All four latest real responses were then replayed through production parsing, source validation, durable preparation storage and public projections, with no additional model calls. Results are in `data/verification/2026-10-16-source-confirmations-final-verification/`. This distinguishes actual provider requests from final local validation; it is not a claim that the last four raw live results were already free of mapping issues.

| Original | Confirmed date | Request characters | Latest input / output tokens | Final extraction | Remaining stored issues | Source-mapping blockers |
|---|---|---:|---:|---|---:|---:|
| `01-20260924-104506.txt` | 2026-09-24 | 45,308 | 15,242 / 4,104 | SUCCEEDED | 2 | 0 |
| `02-20260928-092555.txt` | 2026-09-28 | 44,641 | 14,938 / 4,114 | SUCCEEDED | 4 | 0 |
| `03-20260930-095728.txt` | 2026-09-30 | 46,203 | 15,663 / 4,354 | SUCCEEDED | 1 | 0 |
| `04-20261009-091956.txt` | 2026-10-09 | 48,127 | 16,503 / 5,222 | SUCCEEDED | 1 | 0 |

The 50,000-character request guard and 16,384-token extraction output budget were retained. Each source was called separately. A failed output is not retried as a fabricated completed plan.

## SCV03. Genuine confirmations and backtest readiness

- **Source 1:** maximum position is absent. Its first 100-share entry does not establish a total holding limit; later 300-share plans cannot retroactively fill it.
- **Source 2:** conditional ordinary risk exit is stated, but its applicable holdings and exit quantity are not complete. The three internal scope/quantity fields are one consolidated business question. A “core risk line” does not prove a CORE position bucket. Re-establishing and evaluating entry does not authorize a buy.
- **Sources 3 and 4:** policy structure and source mapping pass. Both can proceed to explicit review after setting cash or acknowledging unknown cash. This was verified in isolated test stores, with test-only approval, for both known and unknown cash.
- **Once per initial account:** cash is not in these originals; set it once or preserve unknown cash, which prevents purchases. All four explicitly establish zero inventory without creating fictional lots.
- **Qualitative conditions:** stabilization, retest, volume and relative-market confirmation need a defined criterion or later verified review evidence. They remain unknown until then. New-position exit policy is shown for confirmation where absent; the engine does not invent a stop or liquidation order.

No real candidate was approved and no actual-source backtest was submitted. These live calls are independent diagnostics because source 1 is not yet reviewed. They do not certify a real AI update chain linked to an approved predecessor. The four-plan continuous backtest still needs source 1's limit, source 2's exit scope and explicit overall review. Synthetic and recorded-response tests verify the linked predecessor/composition mechanics without substituting synthetic strategy decisions for missing source facts.

## SCV04. Verification and limits

- Backend regression: **3,476 passed** across all unit tests and selected preparation, storage, review, worker, date, library, composition and API-contract integration tests. After the last range/citation repairs, **99 focused tests passed**, including two real-response rounds, negative source cases, staged fills and explicit account-review boundaries.
- Frontend: **1,049 passed**; TypeScript and production build passed. Legacy internal-supplement handling remains covered for older projections.
- Both OpenAPI profiles and generated TypeScript are current; English and Chinese U14 carry the matching hashes. Targeted Ruff checks passed.
- Real local Chrome rendered all four actual candidate projections: one consolidated panel each, no internal-field or redundant datetime input, no processing blocker, no runtime error, and no horizontal overflow at 320 / 768 / 1440 pixels. This checks the full review component, not a new end-to-end market-data backtest.
- Initial temporary-directory and Vite path permission errors were resolved by running local checks with a project-owned temporary directory. A prior test that required a missing account timestamp to block review was replaced with an explicit preloaded-opening-time assertion; missing source/policy evidence still has negative coverage.

All artifacts and databases are isolated verification data. No live account, deployed service, Git commit or remote branch was changed. No profitability, market-data coverage or intraday tranche certification is implied.
