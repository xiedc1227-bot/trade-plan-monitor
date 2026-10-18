# Four-source full inheritance verification — 2026-10-17

## FI-01 — Why the earlier second entry was independent

The earlier completed run reused independently reviewed first, second and third entries; only the fourth referenced its predecessor. The new predecessor default does not retroactively mutate reviewed entries or frozen inputs. That earlier run remains unchanged. This verification creates new reviews in order, with versions 1 → 2 → 3 → 4, and combines their exact immutable identities.

Inputs are the four actual originals `01-20260924-104506.txt`, `02-20260928-092555.txt`, `03-20260930-095728.txt`, and `04-20261009-091956.txt`. Effective dates remain the user-confirmed 2026-09-24, 2026-09-28, 2026-09-30, and 2026-10-09. Previously verified earlier-source quotations supply the first maximum of 300 shares and the second ordinary full-exit scope. The separate user confirmation supplies `RESUME_FIRST_CLOSE`. These additions retain their provenance; `plans.json` and `entry-fields.json` are not originals. Funding remains `POSITION_LIMIT_ONLY`, with one zero-share opening account.

## FI-02 — Actual AI and source review

Four real calls used the configured official `api.deepseek.com` / `deepseek-flash`, one original at a time. Calls 2–4 included the newly reviewed immediate predecessor. All raw responses were retained. This was not four flawless automatic extractions: source-backed corrections were applied through review, and corrected captured responses were replayed locally without extra provider calls.

- First: restore the explicit two-close stabilization alternative and cancellation alert omitted/collapsed by the fresh response, using the previously validated extraction of the same source.
- Second: reconcile the model's proposed BUY modification with explicit cancellation of the old 26.40–26.70 entry; restore the omitted ordinary full-exit branch and the already confirmed suspension policy. Evaluation of a future entry is not direct BUY authority.
- Third: remove an operation/binding for an alert the model never defined; retain the unchanged prior alert and ordinary risk branch. The source explicitly forbids cancelling risk controls merely because of a rebound. The 24.20 no-entry instruction remains source evidence; this correction does not invent a timed alert or SELL.
- Fourth: remove an invalid account dependency object containing no holdings assertion; correct first-tranche evidence and retain the unchanged alert. The existing source normalization removes the erroneous self-dependency of the first tranche. Review explicitly removes the former ordinary line-based exit because the complete source row reclassifies the same 25.99 price as a repair threshold, not a new-position stop. No replacement stop price is invented.

Fixes cover cancellation/change-list consistency, adding a first rule to an empty collection, preservation of untouched predecessor risk branches, explicit source-backed risk retention, and narrowly validated demotion of the exact prior risk line. Partial evidence, a different prior price and hypothetical retention wording remain blocked.

## FI-03 — Reviewed inheritance differences

| Effective date | Preparation | Principal reviewed differences |
|---|---|---|
| 2026-09-24 | `full-chain-20261017-1` | Root: maximum 300; first 100 only after stabilization and close above 26.70; cancellation alert below 25.99. |
| 2026-09-28 | `full-chain-20261017-2-v2` | Retain maximum/account; modify price levels; revoke prior BUY; add ordinary two-close full exit with `RESUME_FIRST_CLOSE`. No directly authorized BUY. |
| 2026-09-30 | `full-chain-20261017-3-v2` | Retain maximum, alert and ordinary exit with original provenance; modify pressure to 25.50–26.00; add first 100 after recovery/retest conditions. |
| 2026-10-09 | `full-chain-20261017-4-v2` | Retain maximum and alert; modify pressure to 25.95–26.40 and first entry; add second 100 after first completion and 26.40 confirmation; revoke former 25.99 line-based exit. |

`full-chain-20261017-combined` contains exactly four entries. Only the first is independent. Every successor's `base_hash` equals its immediate predecessor's `extraction_candidate_hash`. All four review issue lists are empty. Maximum holdings remain 300, and later zero-holdings descriptions never reset the account. Qualitative conditions without a quantitative definition remain unknown, not automatically satisfied.

## FI-04 — Continuous replay and validation

Run: `b8c260af9676353ef049310b4e8fdba9d4119e9423e716d24fd8fe37169e8010`.

The completed run uses the existing frozen actual market dataset for 2026-09-24 through 2026-10-09, with warmup from 2026-09-01. No synthetic prices or additional market-provider requests are used. Audit verification passed: 1,468 evaluations, 2,961 events, three replacements on the confirmed successor dates, six reminders, zero order intents and zero fills. One account stayed at zero shares. Report hash: `381e0a37e7e5df9b38f0db32ca356589ab6658839175a493c1bc478a3ec82922`.

All four diagnostic review statuses are `PASSED`, without extraction/validation blockers. First-plan close was 25.69 versus the required above 26.70; its two-close series declined from 26.62 to 25.69. The second plan has no direct BUY authority and prices of 24.44/25.05. The third has no qualifying earlier close at or above 25.99 (25.01, followed by 25.14). The fourth has no earlier qualifying close above 25.99 and latest price 25.35; its second tranche cannot bypass first-tranche completion. Unknown qualitative predicates remain visible separately. Two midnight evaluations precede availability of the current-session daily basis; closing evaluations have verified basis. `POSITION_LIMIT_ONLY` deliberately leaves capital-return metrics unavailable.

Validation: 3,226 unit tests and 25 focused provenance/library/successor tests passed; changed-file lint and `git diff --check` passed. The combined test invocation encountered an existing duplicate test-module filename. The separate broad integration run was stopped during the unrelated ten-symbol 252-day capacity benchmark; no full integration-suite pass is claimed. Earlier sandbox temporary-directory failures were resolved by the focused run in the normal environment.

Local evidence: `data/verification/2026-10-17-full-inheritance/`, including raw provider responses, review corrections, `chain-review.json`, `combined.json`, frozen run input, result store and test logs. Historical databases were backed up before creating the new reviews.

The verified report was added to `data/backtest-results.sqlite3` through the domain publication API, preserving earlier runs. The local service was restarted with its original configuration. Browser verification of `/backtests/b8c260af9676353ef049310b4e8fdba9d4119e9423e716d24fd8fe37169e8010?tab=summary` confirmed `full-chain-20261017-combined`, 1,468 evaluations, zero fills, four passed reviews and actual price comparisons. The first request during lazy service initialization returned 503; the visible retry succeeded. Screenshots: `result-overview.png` and `result-page.png` in the evidence directory.
