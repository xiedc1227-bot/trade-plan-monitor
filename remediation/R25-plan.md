# R25 plan: extraction-only live-acceptance candidate

Canonical English; `R25-plan.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_IMPLEMENTED / SPECIFIC_EGRESS_APPROVAL_PENDING / LIVE_NOT_RUN**.

## Objective and boundary

- Prepare one fresh, extraction-only candidate for the still-unproved `plan-extract-v5` / `max_tokens=8192` provider path.
- Prove offline that the candidate sends only three frozen synthetic fixtures in the fixed order `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`, stops after the first failed or uncertain result, and never activates a plan.
- Preserve the production extraction contract: configured alias `deepseek-v4-pro`, one user message, `temperature=0`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`, `stream=false`, zero provider retries and explicit `max_tokens=8192`.
- Do not call AI or market data during preparation; do not change `config/app.yaml`, credentials, holdings, production databases, historical evidence, consumed claims, webhook configuration or broker state.

## Candidate contract

| Stable ID | Contract |
|---|---|
| R25-B01 | Proposal `R25-20260916-AM-EXTRACT-3`; run `r25-20260916-a`; proposed start gate **2026-09-16 09:30:00–09:45:00 Asia/Shanghai inclusive**. The gate is proposed, not approved or consumed. |
| R25-B02 | Fresh root `data/r25-extraction-acceptance/r25-20260916-a/`, fresh SQLite database and reserved loopback port `18770`; no R14/R17/R18/R20/R22/R23/R24 claim or evidence is reused. |
| R25-B03 | One shared 900-second new-call boundary plus at most 20 seconds for cooperative cleanup. No background wait, automation or cross-day continuation. |
| R25-B04 | Market cap is exactly one physical `trade_cal` start. Every other market endpoint has cap zero. The reference call must be the first external call; failure or uncertainty prevents every AI call. |
| R25-B05 | AI cap is three physical POST starts, one per frozen input, zero retry, strictly ordered `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`. An input is never resubmitted. |
| R25-B06 | A failed literal oracle, uncertain receipt/query, invalid/truncated provider result, diagnostic failure, returned-model mismatch, or failed semantic oracle stops all later cases. |
| R25-B07 | Successful validated results are retained only in the isolated review artifact and extraction-review table. `plan_version`, `plan_activation_state` and `active_plan` must remain empty. Human review remains mandatory and is never inferred from general execution authorization. |

## Business oracles

1. `LITERAL` must preserve all 15 exact source clauses, every frozen source-path/clause binding and unit, and every frozen pre-review value. Policies supplied only by the historical human-test supplement remain unresolved before human review.
2. `SEM-AMB-01` must match its frozen ambiguity oracle, preserve `UNRESOLVED_SEMANTICS`, and remain non-activatable.
3. `SEM-UNS-01` must match its frozen unsupported-semantics oracle, preserve `UNSUPPORTED_SEMANTICS`, and remain non-activatable.
4. The validated review artifact is evidence for a later person to inspect; an automated oracle pass is not a human review, save or activation decision.

## Approval and completion

The exact local review package is generated at `data/r25-extraction-review/egress-review.md` with an equivalent `egress-review.zh-CN.md`. It contains the complete source text, complete sole user prompt, origin, source/prompt SHA-256, destination and fixed body fields for each request; credentials are omitted. No live execution is permitted until the user specifically approves external transmission of that displayed content to `https://api.deepseek.com/chat/completions` for the three stated purposes.

R25 offline preparation is complete only when the candidate, focused tests, bilingual plan/report/handoff, local review package and a clean local commit are present. Live business acceptance remains unproved until a separately started candidate passes and its current validated results receive explicit human review.
