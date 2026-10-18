# Compact backtest service controls

## SC-01 — Interface

Normal backtest pages show one short status and a `服务管理` disclosure. Put refresh, pending-history lookup, service stop, last-check time, explanations and the return link inside it. Expand on service faults, uncertain controls, stopped/disabled service or a detected interrupted job. A running authorized job is not an interrupted job. Preserve task progress, cancellation, preparation refresh and same-request retries in their existing pages.

## SC-02 — Read and control boundaries

Use the existing component/composable and API contracts. When `canRead=true` and no job is currently authorized, inspect at most one unfinished job. Reuse a successful check until the service boot/revision/generation/state/authorization identity changes. Manual lookup remains available. Passive temporary 503 defers to the existing status poll; manual failure and other read errors remain visible. Never prepare storage before readability, activate execution, resume a job or submit paid extraction from this check. Resume still needs explicit checkbox confirmation; control body/key, cancellation and physical-drain rules remain unchanged.

## SC-03 — Verification and status

**Complete within SC-01–SC-02.** Final frontend suite: 71 files / 1088 tests passed, including 32 service tests. Type checking and production build passed. Three focused real Chrome journeys passed; actual four-plan results were checked at 1440, 390 and 320 pixels with no overflow or control writes. Existing cancellation/retry tests remain intact. Broader browser checks exposed existing navigation-abort and preparation-read failures also reproduced on the isolated prior baseline; they are not classified as passing. See [SC-V01–SC-V04](../docs/verification/2026-10-18-compact-backtest-service.md) for evidence and limits. This task changes no plan rules, report identities or acceptance thresholds.
