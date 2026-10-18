# Unified preparation verification — 2026-10-16

Chinese review copy: [2026-10-16-unified-preparation.zh-CN.md](2026-10-16-unified-preparation.zh-CN.md).

## UPV01. Delivered behavior

The entry is “准备计划”, without complete/update radios. A successor defaults to the just-reviewed plan. On a fresh page, only a single-asset library with a unique latest effective date is selected automatically; ambiguous choices stay visible. Explicit new-chain selection survives refresh. Saving pins the immutable predecessor; changing a later source never changes the account or previously reviewed versions.

Review groups rules as retained, modified, added and cancelled, shows changed values and source clauses, and collapses retained rules by default. Missing inheritance is a business question rather than a technical mapping error. Fully restated policy with validated current evidence, identical fixed product constants and explicit retention can establish scope without forcing the document to contain internal field names. Cancellation still requires a unique target: the original-style “原26.40—26.70低吸计划正式取消” matches the exact prior zone; a different price or ambiguous buy-rule identity remains unresolved.

Repairs also cover empty AI account-context objects, repeated evidence for the same operation, unchanged fields in modified sections, explanatory warnings for represented unverified conditions, and the admission of successors after cash-only unknowns were explicitly reviewed. Conflicting operations, fabricated values/spans, negative/hypothetical changes, ambiguous targets and unsupported independent instructions remain guarded.

## UPV02. Four actual originals and one new live call

The four TXT originals in `data/research/shengxin-plan-extraction-20261010` were replayed through the configured production extraction adapter and isolated preparation service using previously captured real AI responses. Confirmed dates remain 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09. `plans.json`, `entry-fields.json` and filenames were not strategy evidence. All four produced candidates with zero source-mapping errors. These four diagnostic preparations were independent; they were not an approved four-plan chain.

| Source | Literal facts / remaining boundary |
|---|---|
| 01-20260924-104506.txt | Explicit zero holdings and first lot of 100 shares; no total maximum position in this original. A prior reviewed rule may supply it, but source 2 cannot retroactively establish the first source's limit. |
| 02-20260928-092555.txt | Explicit maximum 300, inactive low-buy zone and cancellation of the old range. Risk-exit timing is stated; the text refers to the original rules without specifying the exit quantity/scope. An actual reviewed predecessor can supply that scope when it contains it. |
| 03-20260930-095728.txt | Explicit maximum 300 and first lot 100; policy validation succeeds. Cash is a separate opening-account setting. |
| 04-20261009-091956.txt | Explicit maximum 300, first lot 100, second lot 100 and reserved final 100; policy validation succeeds. Qualitative criteria remain unverified conditions. |

After explicit authorization for the original and derived predecessor policy, one new `api.deepseek.com` / `deepseek-flash` call sent source 4 with the validated source-3 snapshot as an isolated diagnostic predecessor. This was not user approval of either plan. Request size: **49,090 characters** against 50,000; output budget: **16,384 tokens**. HTTP 200, `finish_reason=stop`, input 16,878 tokens, output 6,027, total **22,905**. The initial raw response failed the old empty-account/duplicate-operation checks. After repairs, the same captured response passed extraction and materialization with **zero issues**; no second paid call was made.

The actual 3→4 change list contains 7 retained sections/rules, 2 modifications, 1 addition and 0 cancellations: pressure range changes from 25.50–26.00 to 25.95–26.40; first-lot conditions change; the second 100-share tranche is added after the first fully fills; the 300-share cap and the 24.20 new-low alert are retained. These counts include settings sections, not only trade orders.

## UPV03. Verification evidence

An isolated integration test replays the actual source-3 and source-4 responses, explicitly performs test-only reviews, and composes their exact versions. It confirms identical opening accounts, unknown cash remaining unknown, no invented lots, and no automatic approval before the test review command. It does not run market replay or approve the user's actual library.

Frontend: **1,054 tests passed**, type check and production build passed. Browser verification in headless Chrome covers default predecessor selection, explicit new-chain selection, absence of type radios, all four change groups, actual 3→4 differences, and four actual-source confirmation panels. There are no runtime errors or horizontal overflows at 320, 768 and 1440 pixels, and no mandatory authoring/account timestamp inputs. The four-category cancellation demonstration is a labelled UI fixture; the actual 3→4 response has no cancellations.

Backend: **3,510 tests passed** (all unit tests plus related preparation/library/API integration tests); one existing Starlette/httpx deprecation warning remains. Ruff passed, and generated OpenAPI/type checks passed for both monitor profiles. Local evidence is under `data/verification/2026-10-16-unified-preparation/`: `summary.json`, four `public-*.json` projections, `live-update/http-response-01.json`, `update-replay/materialized.json`, and `browser.png`. Stable real-response regressions are included as test fixtures `shengxin-unified-base-03.json` and `shengxin-unified-update-04.json`.

## UPV04. Operational boundary

The four-plan continuous backtest has not been run. The first original's maximum and the second original's referenced exit scope are not invented; confirmed prior reviewed policy can be inherited, while truly absent policy remains visible. Cash is configured once or explicitly retained unknown. Unverified stabilisation/retest/volume conditions never become true automatically.

Restart the application to load backend changes and refresh the rebuilt frontend. Re-extract affected unreviewed candidates: stored outputs are not silently rewritten, and reviewed versions remain immutable. No production library entry was approved and no market/account history was modified by this verification.

Follow-up, 2026-10-17: the original conversation supplied earlier evidence for maximum 300 and full liquidation. These no longer require a new strategy decision when that context is included. After the user confirmed `RESUME_FIRST_CLOSE`, the four-plan replay completed. Its three plan switches, unknown cash, and unresolved daily price-basis limitation are documented in [the predecessor-evidence report](2026-10-17-predecessor-evidence.md).
