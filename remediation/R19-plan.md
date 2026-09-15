# R19 plan: AI truncation remediation and next-candidate design

Canonical English; `R19-plan.zh-CN.md` is the equivalent Chinese review copy. Status **IMPLEMENTED_OFFLINE / LIVE_NOT_RUN**.

## Scope

- Diagnose the consumed R18 literal extraction from preserved redacted evidence without reconstructing or exposing provider content.
- Make complete structured JSON more likely to fit while retaining a finite spend boundary, immutable historical prompt contracts, strict parsing, review blockers and explicit activation.
- Prove offline that truncation is recognizable and cannot create/save/activate a draft, change an active plan, or cause browser recovery to submit another paid POST.
- Prepare one concrete but unauthorized next live candidate. Do not execute it, change real credentials/configuration/database state, call AI/market data, send webhooks, place trades, create an automation, or reuse/delete R14/R17/R18 one-shot claims.

## Delivered slices

1. RED/GREEN contract tests made `plan-extract-v5`, an 8,192-token omitted-config default and `AI_OUTPUT_TRUNCATED` explicit.
2. The v5 prompt keeps the v4 schema and review model, asks for minified JSON, and permits only empty top-level `assumptions`/`warnings` omission. V1–v4 remain byte-identical.
3. V4 and v5 successful mappings share the existing save/review/activation boundary. `finish_reason=length` returns no draft or mapping; a public active-plan read is unchanged.
4. Existing UI recovery tests prove one accepted POST followed only by GET recovery. The R19 report and next-candidate proposal record evidence, uncertainty, budgets and stops.

The ignored `config/app.yaml` remains unchanged at its explicit 4,096-token value. The new 8,192 default applies only when a configuration omits `max_output_tokens`; any later live candidate must use an explicit, separately approved bounded override.
