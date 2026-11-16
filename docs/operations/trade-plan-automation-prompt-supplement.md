# Trade-plan generation: automation supplement

Preparation document · 2026-11-01 · PMA-H01/H02 · [Chinese review copy](trade-plan-automation-prompt-supplement.zh-CN.md).

## PGS-01 — Use

Use this independent source-writing supplement when generating a plan alongside the existing [README prompt](../../README.md#generic-trade-plan-prompt) and the supplied original report. It does not replace either source, change the deployed `plan-extract-v12` prompt, or certify extraction. The [source inventory](../specifications/monitoring/INVENTORY-plan-condition-automation.md) records current capability and unresolved definitions; its categories are documentation, not new API values.

## PGS-02 — Copyable supplement

> Preserve every mandatory source condition and permission/quantity/validity restriction, including polarity, ALL/ANY grouping, rule owner, daily/minute period, and confirmation/execution window. Keep mandatory execution conditions in A; B cannot repair missing A conditions or grant permission. Do not weaken a hard condition, turn a preference into a hard gate, or replace an unsupported rule with a reminder.
>
> Prefer existing automatic conditions when the source or an explicitly approved product default supplies the exact definition: price field/comparator/endpoints, fixed or dynamic reference, observation window, volume baseline, candle component/ratio, or indicator parameters. Preserve the original meaning. A supported formula is not permission to invent its threshold; “stabilized”, “unusual volume” and “strong wick” are not complete definitions by themselves.
>
> Collect genuinely missing definitions into one clear clarification/review step, tied to the original clauses. Ask only for the unresolved parameters or interpretation. Reuse an unchanged reviewed definition instead of redefining it every day. Changed definition, scope, period or plan binding requires the applicable review again. An answer defines the condition; it never asserts that today's condition is true. Unanswered meanings remain unresolved.
>
> Once defined, let existing owned data acquisition and reevaluation calculate supported market conditions. Missing, stale or unfinished bars mean wait for the appropriate data/close, not “false” and not a request for a person to certify an arithmetic result. Preserve a decisive independent ALL/ANY result where the native evaluator permits it, while keeping the missing branch visible; existing action guards still apply.
>
> Retain genuinely necessary human steps: initial plan/source review and activation; applicable official-information verification; explicit inventory/cost declarations; and separate approval for each permitted exception opportunity. A plan permission, AI prose, saved draft or preview is not approval or a fill. For any irreducible manual condition, name the exact condition and applicable date/bar/signal; do not substitute a generic same-kind assertion or promise an unimplemented public registration path.
>
> Keep unsupported obligations and unanswered definitions visible and block the affected dependent rule. Do not approximate persistent pre-entry no-buy restrictions with a current-price test, a generic manual fact or a fabricated recovery rule. Do not move risk lines, quantities, ownership or expiry to make import succeed. Retain independent risk handling where its own existing evidence and authority permit it. Add no strategy, threshold, automatic approval or output format.

## PGS-03 — Current boundary

This text supplies generation guidance only. Schema5 ordinary `REVIEWED_FACT` / `TRADE_DATE` official-daily/completed-minute selection and server-derived registration are implemented; selection UI and the scoped exact-leaf browser journey passed engineering acceptance in [PMA-R97/R103](../verification/2026-10-27-plan-monitor-assurance.md). As reconciled on 2026-11-16 in [TOM-04/TOM-07](../verification/pma-t13-obligation-matrix-2026-11-16.md), Schema10 ordinary `OFFICIAL_DAILY_CLOSE` / `REVIEWED_FACT` / `TRADE_DATE` manual-fact support is not yet accepted; other owners/schemas/scopes are not enabled by the Schema5 delivery. Existing initial review, official facts, inventory and per-opportunity approvals remain necessary. Data readiness reads do not acquire data.

Do not append this supplement to frozen corpus inputs or extractor instructions to replace the existing baseline. Preserve and score original automatic results separately from clarified/human-assisted results. Guidance for future new plans does not repair or approve the existing corpus.

[PMA-R59](../verification/2026-10-27-plan-monitor-assurance.md) records 505 focused offline backend checks; [PMA-R62](../verification/2026-10-27-plan-monitor-assurance.md) accepts the narrow public companion. These are not corpus or real-installation acceptance. The persistent BUY guard is implemented under source-bound approved clarification, with ordinary continuation inheritance and exact reviewed replacement activation ([PBS final acceptance](../verification/plan-buy-suspension-2026-11-15.md)); raw and assisted outcomes remain separate. Other original03/04 obligations/full positive acceptance, X09, X12 predecessor/corpus and resource issues remain open ([TOM-05–TOM-08](../verification/pma-t13-obligation-matrix-2026-11-16.md)); real extraction stays 0/48. README and v12 bytes remain unchanged. Any later change to extraction instructions/schema needs its own version and existing acceptance gates, not a relabelled v12.
