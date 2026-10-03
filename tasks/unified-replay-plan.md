# Implementation Plan: Unified Replay

## P01. Contract and review

Implement [UR01–UR08](../docs/specifications/backtesting/SPEC-unified-replay.md). This topic-specific task list preserves unrelated unfinished `todo.md` work. Baseline is clean `6118569`. Parent Astra/high owns design/scope/final review; one explicitly selected Sol/high subagent began sequential implementation; after two capacity failures, a separate continuation subagent using the inherited parent configuration completed the remaining work. No concurrent edits to shared files and no commits. Stage transitions are already authorized.

Internal design review: the plan addresses legacy type rejection, missing current lifecycle orchestration, optional position fields, certified daily evidence absent from old datasets, explicit operation authority, future-dependent identities, typed result compatibility and real entry-point verification. Prefer the existing runtime in an isolated research session over duplicating policy. Unknown input is visible, never inferred. Paired documents contain identical UR/P/A IDs and contracts. Design gate: PASS; implement in dependency order below.

## P02. Ordered slices

- [x] S1 — Input and identity. Add bounded research contracts and v4 run dispatch/validation; tests first for rejection, optional caps, round trip and old byte goldens. Files: research input module, run_input, focused unit tests and fixtures. Acceptance: UR-A01/A02.
- [x] S2 — Minute replay. Add frozen event adapter and isolated runtime reuse, no notification sink; hook existing runner. Test one current minute plan with unchanged holdings and deterministic output. Files: new replay/session modules, runner, minimum runtime seam, focused integration tests. Acceptance: UR-A03/A06/A08.
- [x] S3 — Daily/mixed and lifecycle. Add certified supplemental daily admission and explicit fact/lifecycle script. Test cutoffs, warm-up, persistence/date windows, independent signals, termination and latched risk. Files: same research modules and focused scenario tests; minimal shared participant only if necessary. Acceptance: UR-A03/A04/A05/A06.
- [x] S4 — Explicit operations. Reuse current whole-simulation/reassessment checks; preserve research cost distinction and full quantity. Test T+1, CORE, capacities, duplicates, negative/unknown facts and explicit removal. Files: research operation adapter, necessary shared operation seam, focused tests. Acceptance: UR-A05/A07/A08.
- [x] S5 — Durable results. Add typed current report/detail projections and compatible persistence/read/export. Record any new projection/export domain before implementing it. Test cancellation, reopen, job publication and exact old/new bytes. Files: reporting/results/result_service/jobs dependencies in small sequential groups. Acceptance: UR-A02/A09.
- [x] S6 — Existing entrances. Wire CLI research file, API schema/composition/errors and generated contracts; then current Vue form/detail display. Test inactive reviewed plan through durable worker and browser. Files: CLI, backtest composition/HTTP contracts, generated artifacts, backtest UI and corresponding tests. Acceptance: UR-A01/A10.
- [x] S7 — Final verification. Build per-event current-runtime parity scenarios with independent expected assertions, future mutation and a guard mutation test. Run required checks, fix scoped failures, record bilingual evidence and usable commands, update current indexes. Parent independently reads diff/tests and verifies evidence. Acceptance: UR-A01–A10.

## P03. Gates and controls

Each slice starts with a meaningful failing test and ends with focused green evidence. Refine file groups before editing; retain the contract and report additional necessary dependencies to the parent. Changes outside UR08 require user agreement. Do not weaken checks, swallow missing data, fabricate review/adjustment evidence, or relabel old tests as new acceptance. An isolated synthetic review fixture is explicitly research input, never an attestation about real user text.

Final commands and evidence are specified by UR08. No external services, production database/config, provider probes, commit, push or deployment. Test failures get root-cause repair within scope. Final review records actual models/efforts, limitations, retained legacy compatibility and entry points.

Final independent review: PASS. S1–S7 are complete; UR-A01–UR-A10 evidence and explicit limits are recorded in the [verification report](../docs/verification/2026-10-03-unified-replay.md). Changes are local; no commit, push or deployment.
