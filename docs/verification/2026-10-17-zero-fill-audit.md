# Four-source zero-fill audit (2026-10-17)

## ZF-V01. Scope and evidence

The user requested a per-source explanation of zero fills, separating actual unmet conditions from qualitative ambiguity and extraction/validation defects. Re-read the four original `.txt` sources under `data/research/shengxin-plan-extraction-20261010`; `plans.json` and `entry-fields.json` are not source plans. Keep confirmed effective dates 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09. Earlier primary-source evidence for the first 300-share ceiling and second full-exit scope remains attached; the user's `RESUME_FIRST_CLOSE` choice remains unchanged. No cash input is required.

This verification reuses saved real AI responses and actual historical market responses; it makes no new AI or market-provider request. Sources 1–3 use saved initial extraction responses; source 4 uses the saved update response against the reviewed third source. This is not a claim of four fresh sequential AI update calls. Preparation, normalization, review, composition, dataset freeze, continuous replay and report publication use production services with isolated local databases. Reviewed test evidence is not production activation.

Artifacts: `data/verification/2026-10-17-zero-fill-audit/`. `per-source-reasons.json` compares old and repaired close-time evidence, including condition leaves, operands, bar/basis IDs and audit sequence numbers. `continuous-audit.ndjson`, `continuous-summary.json`, `combined.json`, `run-input.json` and `dataset-freeze.json` retain reproducible identities. Daily/minute/factor responses are reused from `data/verification/2026-10-17-predecessor-continuity/market/`. Their retrospective availability convention remains as documented in DB-V01–DB-V03; no contemporaneous collection claim is made.

## ZF-V02. Per-source result

Prices below are yuan from the retained actual daily responses, consistent with the admitted daily basis in this interval. Each row's close-time evaluation has no price-basis blocker.

| Source / active sessions | Explicit entry authority | Actual evidence | Why no fill |
| --- | --- | --- | --- |
| 1 / 2026-09-24 | Stabilization and non-abnormal volume, close above 26.70, then next-session first 100 shares | Close 25.69; high 26.72; previous close 26.62 | Close threshold failed. An intraday high is not a closing confirmation. The explicit nondeclining-close alternative also failed. Candle/volume ambiguity remains but is not needed to explain this rejection. |
| 2 / 2026-09-28–2026-09-29 | Keep zero holdings; after recovery, re-establish a low-buy zone and evaluate the first purchase | Closes 24.44 / 25.05; highs 25.52 / 25.27 | No directly authorized ordinary buy rule; the source's 25.99 recovery and 26.40–26.70 reassessment context were not reached. Empty buy rules are faithful to this source, not extraction loss. Full-exit rules cannot sell a zero holding. |
| 3 / 2026-09-30, 2026-10-08 | First reclaim 25.99 in a completed daily close, then retest 25.50–26.00 and recover; volume and relative-index requirements also apply | Closes 25.01 / 25.14; highs 25.56 / 25.95 | The first recovery stage never occurred in the new plan's window. Before repair, this known stage was bundled into an unverified qualitative fact. After repair the first-buy root is `UNSATISFIED`, rather than only `MISSING_INPUT`. |
| 4 / 2026-10-09 | First complete close above 25.99, then a later retest near 25.70–26.00; second 100 only after the first purchase and a 26.40 hold/retest | Close 25.35; high 25.88 | First recovery stage failed. No first purchase exists to authorize the second tranche; 26.40 was not reached either. First-buy evidence is now `UNSATISFIED`. The second rule's unquantified hold/retest still shows `MISSING_INPUT`, without granting trade authority. |

Therefore the zero-fill outcome has an explicit price/authorization basis in this interval. The previous third/fourth explanations were incomplete: extraction representation hid a measurable prerequisite behind qualitative uncertainty. Correcting that representation does not create a trade where the prerequisite was never met.

## ZF-V03. Repair and remaining definitions

Added the typed `DAILY_PRIOR_CLOSE` prerequisite with source-bound threshold/comparator and confirmed effective-date window. It searches only complete earlier sessions with admitted daily evidence; current-day recovery cannot simultaneously prove a subsequent retest. Missing/truncated history stays unknown. Source normalization only applies when explicit recovery order, a unique threshold, a current unrecovered statement and an effective date are present. It does not invent a lookback, intraday rule, retest duration or volume threshold. A matching current-close predicate is replaced only when its own source explicitly describes that earlier recovery stage; unrelated current-close requirements remain.

Both recovery and retest clauses are retained in evidence bindings even if the AI cited only the retest. The review summary shows the prior-close requirement as an automatic fact, removes repeated context from the business question, and preserves unresolved criteria and original text. New-schema prompt overhead initially reproduced `AI_INPUT_TOO_LARGE` on the fourth source. Removing redundant schema annotations resolved the retry within the existing limit; union constraints, source text and validation remain intact.

Still unresolved: source 1's wick/bullish-stabilization alternative and abnormal-volume definition; source 3's retest/recovery measurement, volume baseline and relative-index formula/window; source 4's “nearby”, “not breaking”, “rising again” and “holding firm” definitions. The first source's explicit two-close alternative already executes automatically. A price/range extracted from prose does not alone define those shapes. No new-position exit policy is invented from repair levels. These unknowns are retained, but none must be manually resolved merely to establish the zero-fill explanation above. Future automatic entries require the relevant definitions or admissible reviewed evidence; the generation template can supply explicit definitions for new plans.

## ZF-V04. Continuous replay and checks

- Run ID: `92edcbaa73bf9e445834b2c5ef5a22a4da4499d82c76fa412e05b92e62bb84d1`.
- Report SHA-256: `81ef60f0279f9346a835dff69e11f1ccf3c430e0fdea40be6202bc959ffc1423`.
- 1,468 evaluations, 2,956 audit events, three ordered replacements, one risk reminder, zero intents and zero fills. One account remains at zero shares; the maximum remains 300 shares.
- Two `PRICE_BASIS_UNVERIFIED` evaluations remain at 2026-09-29 00:00 and 2026-10-08 00:00, before declared 09:30 factor availability. No trading-session or close-time evaluation has that blocker. Fees and cost PnL are zero; capital return is unavailable in `POSITION_LIMIT_ONLY` mode.
- Audit chain, publication, exact schedule, zero inventory, confirmed risk scope and all six close-time explanations verified. Third/fourth first-buy roots changed from `MISSING_INPUT` to `UNSATISFIED` while unresolved children remained visible.
- 3,206 backend unit tests and 169 targeted integration tests passed. The latter cover actual successor preparation/review, library composition, frozen input ownership, dataset behavior and OpenAPI parity. Full integration-suite certification is not claimed.
- 1,055 frontend tests, TypeScript check and production build passed. Focused Ruff and both generated-contract checks passed. This turn did not repeat browser acceptance or make fresh live AI calls.

Code and bilingual documents are updated locally. To obtain this explanation in a new application run, restart with the updated code, re-extract/review affected candidates and create a new backtest. Existing reviewed policies/results are immutable; they are not silently rewritten.
