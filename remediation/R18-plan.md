# R18 independent review and next acceptance preparation

Canonical English; `R18-plan.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_REVIEW_COMPLETE / LIVE_NOT_AUTHORIZED / LIVE_NOT_RUN**. This step starts from `c7f3e8a7e592af0a84606ab9834d8349892fc4e4` with the R17 repair still uncommitted, preserves the 12 earlier tracked edits and four R00 untracked files, and does not reinterpret R17's failed business result.

## R18-1. Contract and diagnostic decision

- Replay the three preserved R17 HTTP 200 failure DTOs through `createAIPlanApi`: accepting their new `diagnosticStatus` must retain `PROVIDER_ERROR` / `INVALID_OUTPUT`, null drafts and activation-blocking issues. Check omitted/null/`RECORDED`/`WRITE_FAILED`; reject malformed enums or unknown fields. Compare the partial successful fixture against backend serialization and keep unresolved policies activation-blocking.
- Exercise QUEUED → RUNNING → failure, failed GET, same-operation GET recovery, and local stop in the actual composable/browser. Recovery may make additional GETs, never a second paid POST. A stopped local wait is not a server cancellation.
- Trace startup `trade_cal` through the production pipeline and request controller. Preserve bounded `REFERENCE_*` categories and `nextRetryAt`, clear them on recovery, and avoid provider content, source text, exception strings or credentials in logs/health. Keep historical calendar root cause unproven.
- Check `STRUCTURE` to scalar, field-level source/binding paths and source-evidence validation. Keep historical mapping fields unproven; the new scalar defect is an independent offline finding.
- Check OpenAPI snapshot, generated TypeScript, type-check, production build, installed asset equality, real Chrome with intercepted local API, targeted Python tests and all 16 protected hashes. The historical `reproduce-client-contract.cjs` proves the old rejection and is not a repaired-state success criterion. Do not make the interrupted ten-symbol/252-day backtest capacity test a monitor-core blocker without an implementation link.

## R18-2. Traceable implementation and bounded next session

R17 repair was committed as `0f1dea5` (`fix: 修复提取契约与失败诊断`) after the independent checks. The new date-bound launcher and its offline boundary tests were committed as `6a97265` (`feat: 准备次日独立有界验收入口`). `scripts.r18_bounded_acceptance` defaults to no-network dry-run, uses only a new 2026-09-15 14:30–14:40 window, independent `data/r18-acceptance/_session_claimed` and the unchanged R17 three-AI/60-market/900-second physical guards. Its execution mode remains unused. The exact business procedure, spending uncertainty and failure stops are in `docs/verification/R18-execution-proposal.md`; it needs fresh direct user approval, not an old claim or code phrase alone.

## R18-3. Evidence limit and handoff

The R18 checks establish offline contract behavior and guarded wiring only. The full Python non-live suite was interrupted during a separate backtest capacity case in R17 and was not rerun or claimed green here. Real supplier permissions, tomorrow's open status, charges, literal parsing, human review, activation, fresh-market evaluation and visible alert remain unverified until a separately authorized session. If fixed test prices do not naturally trigger, alert delivery is `NOT_OBSERVED`, never fabricated PASS. No R19 or recurring task is created.
