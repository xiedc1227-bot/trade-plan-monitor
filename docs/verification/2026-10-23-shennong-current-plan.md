# Shennong plan generation, extraction, draft save and page verification — 2026-10-23

## Inputs and market evidence

Used the exact current Chinese README prompt, original `TradingAgents/Y/complete_report.md` dated 2026-10-21, and actual holdings 0, holding cost none, maximum 300 shares. The report timestamp timezone remains unknown. English is this review summary, not a separately generated plan. The previously authorized independent flat-position observation policy remains: official daily close strictly below 26.59 yuan triggers reassessment, not an exit or entry stop.

Public data were retrieved at approximately 22:05 Beijing time on 2026-10-23. Eastmoney unadjusted daily data and Sina agree on close 30.24, +0.80%, OHLC 29.89/30.49/29.49/30.24, volume 3,506,650 shares and turnover 105,189,344 yuan. Sina's 15:34:59 snapshot timestamp is separate from the exchange 15:00 close. Eastmoney QFQ/index requests disconnected; Yahoo supplied matching 275-session stock/index histories through 10-23. Stock adjusted-close factors are normalized to the latest actual price; index levels are raw, without cross-provider partial-bar splicing.

Calculated stock MA20 30.6645, MA50 31.7996, MA60 31.4545; index I 3690.4753, M20 3803.8838, M60 3871.5671, M20_5 3847.7392, L20 3649.8650. The index is weakening under the prompt rules, not confirmed structural damage. Relative strength fails: 5-session stock/index +5.29%/-0.69%, 20-session -7.32%/-4.78%, stock below MA20. No current low-buy quantity is proposed; hypothetical future weakening-state sizing is capped at 0.5Q0 rounded down legally with S1 confirmation, subject to complete S0/Q0 and human assessment. Native dynamic index linkage remains unsupported.

The SSE 10-23 issuer-announcement index was read, and the [issuer announcement text reproduced by Sina](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12653528&stockid=605296) states planned Q3 disclosure on 10-28 and a 10-30 briefing. This is a planned publication, not verified Q3 results. The original report's financial assertions were not independently reaudited here.

## Generation and real extraction

The full report is 61,094 characters. To preserve the existing 50,000-character input budget, generation used 21,992 characters of original text: the technical and fundamental analyst sections and final portfolio-manager decision, omitting repeated debate. The full report and excerpt hashes and exact sent requests are archived. No report instructions were executed.

Configured model `deepseek-flash`, 4096 output tokens, 30-second timeout and 2 maximum retries. Three diagnosed rounds produced 3 generation and 3 extraction calls, each with one provider attempt; all requests used the existing budget. No production code, prompt README, validator, Schema or provider settings changed.

- `run-v1`: full extraction passed, but B did not enumerate the final report's concrete fundamental reassessment gates. Those original criteria were explicitly identified in the next generation input.
- `run-v2`: B preserved those gates; A appended policy-purpose explanations containing commas into its source label. Strict mapping rejected the raw extraction with `AI_FIELD_EVIDENCE_INVALID`. Exact offline replay reports `source binding is absent from its exact clause`. The input was clarified to keep the factual report source label in A and all purpose explanations in B.
- `run-v3`: full `SUCCEEDED`, no issues, assumptions or warnings, exactly **1 RISK_ALERT / 0 ordinary rules / 0 risk branches**, cap 300, official-close `LT 2659 FEN`, source fact date 2026-10-15. Metadata retains report reference 3030 fen and unknown timestamp null. Draft structure converts successfully; this is not approval or activation.

[Final A](evidence/2026-10-23-shennong-current-plan/A.txt) and [final B](evidence/2026-10-23-shennong-current-plan/B.txt) are untouched generated strings. Every round, including the failed raw mapping, is retained in [evidence](evidence/2026-10-23-shennong-current-plan/verification.json). No prefix stripping, source relabeling after generation, binding deletion, output repair or validator relaxation occurred.

## Policy and human follow-up

General validity is exactly `计划持续有效，直至人工停用`. Cost none is preserved, without fee/PnL calculations. The current independent reminder has **no missing parameters**. B retains the report's wait-before-Q3 conclusion and post-report reassessment in about 1–3 months. Existing-position exit conditions do not create sales for a flat account.

Future human research must verify actual disclosure/results, positive quarter-on-quarter gross-margin recovery, positive operating cash flow, no new material impairment, narrowing revenue decline, and volume-supported effective recovery of dynamic MA50. “Material”, “volume-supported” and “effective” remain unquantified report terms, not satisfied machine entry conditions; the sale-specific 18-day volume threshold is not reused as a buy gate. These future tasks are not missing inputs or added gates for the current reminder.

## Checks and state

Existing strict extraction/source/security regression: **50 passed in 1.76s**, command recorded in evidence. Read-only before/after protected snapshots are identical: original 神农集团 application draft remains unconfirmed `DRAFT`, review revision 0, 1 reminder and 0 ordinary/risk rules, with empty activation state. Inventory, risk, history/review and configuration hashes match. At the generation/extraction stage, no application draft was saved, no review confirmed, no plan activated and no actual/simulated inventory changed. Subsequent explicitly authorized save and page verification are recorded below. Other tasks' files are excluded.

## Draft save and preserved evidence

After the user authorized saving, the existing production draft persistence service saved the untouched final A and its validated extraction mapping at 2026-10-23 22:22:13 +08:00. No new AI call or manual output repair was needed. Plan `605296-20261023-ALERT01`, version 1, has version ID `daa0387c-26b2-4e5f-8ea1-b4ea142ecedb` and extraction ID `870179cc-ef04-4dd4-ab87-a4db8740ae81`. Fresh application-service readback confirms `DRAFT`, review revision 0, no review ID, `can_activate=false`, 1 technical alert, 0 buy/sell rules and 0 risk/liquidation branches. The existing earlier draft and history remain preserved.

The A source SHA256 is `99153867d727c3440ba7015870fcd54406165fc9ea6869c71822e149428cce33`; the persisted plan hash is `d544f88adf633d658c4539de6909391a4b45a9312393f35874f67057c55e0118`. [Save receipt](evidence/2026-10-23-shennong-current-plan/draft-save/draft-save-verification.json), saved response/readback, archive manifest and before/after protected-state hashes are retained. B and all three AI rounds were archived locally under `data/research/605296-20261023-ALERT01/validation-20261023-run-v3`, linked by plan-version ID. These are local research files, not a claim that B is displayed as a native application attachment. B's original “unsaved” statement and generation-stage `plan_saved=false` describe their creation stage and are intentionally preserved; the later save receipt records current state.

## Live page verification and human review

The user subsequently authorized starting the packaged local web service and opening `/plans/daa0387c-26b2-4e5f-8ea1-b4ea142ecedb`. An actual in-app browser displayed the saved A, one `alert_rules[0]` (`RISK_ALERT`, current `close`, `LT`, fixed `2659 FEN`, `OFFICIAL_DAILY_CLOSE`), empty buy/sell and technical-exit collections, “saved version 1 / awaiting review” and “alert-only draft: awaiting review, not activated”. The server pending-item count is 0 and activation is disabled. [Page observation and checks](evidence/2026-10-23-shennong-current-plan/page-check/verification.json) retain the accessibility tree and protected-state comparisons. The page was left open for the user; no review, activation, save or inventory controls were clicked.

The page also displays a historical simulation-inventory compatibility warning, explicitly stating alert-only rules do not depend on simulation inventory. The header displayed connection-in-progress; this verification establishes correct draft rendering, not live monitoring readiness. The draft is inactive and does not run reminder monitoring. Post-visit read-only checks confirmed unchanged current plan hash, no review confirmation, no activation, unchanged inventory and preserved earlier records/configuration.

Human review should check symbol `605296.SH`, maximum 300 shares, B's actual holding 0/cost none, the fixed 26.59-yuan source and strict official-close comparison, and the reminder-only scope. General validity remains `计划持续有效，直至人工停用`; report reassessment and index effects remain human research, not additional automated entry/exit conditions. There are no missing parameters for this reminder. Generic editor hints about replacement versions or empty CORE/TACTICAL fields are not added rules or mandatory inputs for this alert.

## Repository submission boundary

Only this paired report and its evidence directory belong to this submission. No local database, WAL/SHM file, runtime configuration, credentials or other task's changes are included. Raw AI records remain untouched, including the failed round. Archived Python files document the original local execution context; they are not standalone portable replay commands and are not automatically run during review. No schema, validation, budget or production behavior changed. The original 50-test result is retained; this documentation-only submission additionally checks evidence hashes, JSON integrity, raw A/B preservation, readback rule counts, protected snapshots and the explicit staged-file allowlist.
