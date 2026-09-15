# R25 plan: extraction-only live-acceptance candidate

Canonical English; `R25-plan.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_IMPLEMENTED / SPECIFIC_EGRESS_APPROVED / LIVE_NOT_RUN**.

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

The exact local review package is generated at `data/r25-extraction-review/egress-review.md` with an equivalent `egress-review.zh-CN.md`. It contains the complete source text, complete sole user prompt, origin, source/prompt SHA-256, destination and fixed body fields for each request; credentials are omitted. On 2026-09-15 the user replied “批准” after that package had been displayed and specifically approved external transmission of its exact contents to DeepSeek at `POST https://api.deepseek.com/chat/completions` for the three stated extraction tests. This satisfies the previously missing content-specific egress approval; general permission must not be requested again.

The approval is bound to package SHA-256 `6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d` / `4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0`, source SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`, `26760155a5c87044b514ab2cff3a162dcef45d739dc863961ee629573e9e991e`, `23401380e6f188abe6da02c2e77db8e4f67bb8e7133efa191329cf505baa11b0`, and prompt SHA-256 `660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89`, `f4e5a48d49dbbf582dae883af8dfe724b133df465dd92ff7363dadb6c4e5e2a7`, `fea166298e40b143a5ae261bc7efdf17b3ce8f95869df6ee9c2bdf7cef451455`. Any change invalidates this approval. Approval does not override the date/window, route, price, certificate, configuration, hash or port gates and is not human review of future provider results.

R25 offline preparation is complete only when the candidate, focused tests, bilingual plan/report/handoff, local review package and a clean local commit are present. The approval-recording turn did not execute the candidate or consume a claim. Live business acceptance remains unproved until a separately started candidate passes and its current validated results receive explicit human review.
