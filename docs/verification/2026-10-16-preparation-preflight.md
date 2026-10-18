# Preparation preflight and actual-source verification — 2026-10-16

Canonical English; Chinese review copy: [2026-10-16-preparation-preflight.zh-CN.md](2026-10-16-preparation-preflight.zh-CN.md).

## PF-V01. Reproduced cause and scope

The preparation saved at 2026-10-16 15:34 Shanghai time had one failed first item (`INVALID_OUTPUT`) and three untouched `WAITING` successors. Offline reproduction of the exact first source with `max_input_chars=50000` produced `AI_INPUT_TOO_LARGE` before any provider call. Its 1,478-character text generated a 58,640-character prompt. The service discarded that specific reason when persisting the failure. Separately, all four source dates were null; their text did not establish complete effective dates with years.

The repair implements ML20: compact complete requests, actionable safe failure codes, date confirmation before extraction on both client and server, and “等待提取” for unprocessed items. No configured length threshold was raised. No original research file or operational preparation record was rewritten. `plans.json` and `entry-fields.json` were not read as plan inputs or supplements.

## PF-V02. Actual source evidence

The four original TXT files were copied unchanged into `tests/fixtures/shengxin_sources/`. Tests load their complete text and assert equality after decoding the prompt's data envelope, plus exact clause IDs, offsets and excerpts. Schema display titles, redundant JSON spacing and unassigned clause classification placeholders are omitted; descriptions, constraints, defaults and literal values remain. Successor context is preserved in full. A separate regression protects a schema property/default literally named `title`.

| Original TXT | Text characters | Previous initial request | Repaired initial request | Repaired successor request with controlled past context |
|---|---:|---:|---:|---:|
| `01-20260924-104506.txt` | 1,478 | 58,640 | 44,927 | 43,024 |
| `02-20260928-092555.txt` | 1,423 | 57,623 | 44,260 | 42,357 |
| `03-20260930-095728.txt` | 1,732 | 59,785 | 45,822 | 43,919 |
| `04-20261009-091956.txt` | 1,924 | 62,709 | 47,746 | 45,843 |

All repaired requests in this fixture fit the unchanged 50,000-character guard. Successor measurements use a validated synthetic predecessor, not an invented extraction of the actual previous source. Larger real predecessor context can still exceed the configured bound; it must produce the explicit input-limit message without truncation.

## PF-V03. Automated and browser checks

The new actual-source budget tests failed for all four files before the repair and pass after it. Integration checks prove that unresolved dates leave the durable record and attempts unchanged and make zero extraction calls. A deliberately tiny input budget persists `AI_INPUT_TOO_LARGE`, releases the task and allows explicit retry without automatically consuming additional attempts. Existing extraction/admission fixtures now supply explicit dates when their purpose requires starting extraction.

| Check | Result |
|---|---|
| Backend unit suite | 3,073 passed; one existing Starlette/httpx deprecation warning. |
| Preparation and monitoring-loop integration suites | 543 passed; one existing Starlette/httpx deprecation warning. |
| Frontend suite, `npm run test -- --run --maxWorkers=4` | 1,035 passed across 64 files. |
| Real Chrome, `monitor-loop-backtest.spec.ts` | 4 passed, including the actual-source preflight journey. |
| Type checking, production build, API snapshots/types, changed-file Ruff and whitespace checks | Passed; canonical monitor v2 and compatibility monitor v1 remain current. |

The actual-source Chrome scenario uploads the four original files, verifies date prompts and no extraction action, checks API rejection with `SOURCE_DATE_REQUIRED`, then enters explicit test confirmation dates one by one. Extraction remains unavailable until all four are saved. The controlled provider then returns a known rate-limit response, proving the first actual prompt reached the provider boundary rather than the length guard. The first item displays the provider reason; the other three remain “等待提取”. Date-confirmation layouts are checked at 320 and 1440 pixels. Existing single-source, cancellation and continuous-account journeys are also retained.

An initial browser assertion matched both the stable status and temporary submitting message; it now selects the stable live status. One fully parallel frontend run timed out on an unrelated route-navigation wait during simultaneous backend/browser work; the unchanged test passed in the complete four-worker rerun. No tests or assertions were removed to obtain passing results.

## PF-V04. Boundaries and use

At this verification stage, actual source content was verified through local request construction, server preflight and real-browser UI, using controlled AI responses. No paid/live AI request was made at that stage; this does not certify successful semantic extraction of all four plans or a completed backtest using them. Their years still needed user confirmation. Test confirmation dates are fixture inputs, not application inference from filenames. No trade or opening-account facts were fabricated. The subsequent user-confirmed dates and live AI results are recorded in [Actual-source live AI preparation verification](2026-10-16-real-ai-preparation.md).

Build the frontend and restart the application to load the repair. For the existing failed preparation, select each source, confirm its effective date and save; those edits reset the affected extraction cycle. Start extraction only after all dates are confirmed. Old generic failures cannot acquire missing diagnostic detail retroactively. New input-overflow messages direct the user to the complete request budget, not an assumed defect in the trading plan.
