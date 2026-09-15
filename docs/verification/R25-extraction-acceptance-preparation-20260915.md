# R25 extraction-only acceptance preparation

Canonical English; `R25-extraction-acceptance-preparation-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal `R25-20260916-AM-EXTRACT-3`; run `r25-20260916-a`. Status **OFFLINE_PASS / SPECIFIC_EGRESS_APPROVAL_PENDING / LIVE_NOT_RUN / ZERO_EXTERNAL_CALLS**.

## Source and privacy inventory

All three proposed inputs are versioned synthetic test fixtures. `LITERAL` comes from `tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText`; `SEM-AMB-01` and `SEM-UNS-01` come from the matching IDs in `tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json`. The frozen source SHA-256 values are respectively `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`, `26760155a5c87044b514ab2cff3a162dcef45d739dc863961ee629573e9e991e` and `23401380e6f188abe6da02c2e77db8e4f67bb8e7133efa191329cf505baa11b0`.

The fixtures contain synthetic trading-rule and holding language. Offline pattern inventory found no email address, phone-like number, 12-or-more-digit account-like number, credential term or broker name. They do not read a real account, production holding or production plan. This classification does not replace content-specific egress approval; the exact text and full prompt are displayed locally for review.

## Implemented candidate

- `scripts/r25_extraction_acceptance.py` defaults to dry-run and creates no claim. `--execute` requires the exact authorization string, exact run ID, eligible proposed date/window and a passing offline preflight.
- It reserves port `18770`, atomically claims a new isolated folder, starts the production reference lifecycle, and admits exactly one `trade_cal` physical start before AI. All other market caps are zero.
- A shared 900-second deadline bounds all new calls, followed by no more than 20 seconds of cooperative cleanup.
- It then uses the production configured AI composition with an isolated v5/8192 override, one physical start per frozen source, and the fixed order `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`. The ignored real `config/app.yaml` remains unchanged at its explicit value.
- Each terminal result requires a recorded content-free diagnostic and `modelMatchesConfigured=true`. The literal and semantic frozen oracles run before the next case. Any failure, model mismatch, missing diagnostic, uncertain receipt/query or timeout stops without resubmission.
- Validated result views are written to `validated-review-results.json`; raw provider content is never retained. The audit remains redacted. Cleanup verifies `plan_version`, `plan_activation_state` and `active_plan` are empty, so extraction cannot become activation.

## Offline verification

At `2026-09-15T15:00:34+08:00`, dry preflight read the local configuration and certificate metadata without printing credentials or a direct address. It reported the AI alias/key and market token/connect-address as present, stock certification ready, port 18770 available, and `ready=false` solely because the proposed 2026-09-16 gate was not current. It made no AI or market request and did not probe balance or model-list endpoints.

Focused R25 tests: **7 passed**, with one pre-existing Starlette/httpx deprecation warning. They cover candidate identity/caps, exact request material, bilingual review-package generation, ordered early stop, frozen literal/semantic oracles, uncertain query without resubmission, and the exact execute gate. The R25/R23/R24 plus v4/semantic extraction regression group passed **46/46**. Ruff passed for the candidate and focused test.

An additional historical R14/R17/R18/R20 wiring group passed **39/40**. Its only failure is the existing `test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`, whose test payload omits the `temperature=0` field already required by the unchanged R14 transport guard. R25 did not modify that guard or test, and its exact request-material test proves `temperature=0` is present. This is recorded as pre-existing historical-test drift rather than changed outside R25 scope.

The generated local package is `data/r25-extraction-review/egress-review.md` with equivalent `egress-review.zh-CN.md`. It contains each complete source and exact complete sole user prompt, not merely hashes. It names DeepSeek as recipient, `POST https://api.deepseek.com/chat/completions` as destination, and the three purposes. The Authorization value is deliberately absent. Package SHA-256 values are `6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d` (English) and `4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0` (Chinese).

## Current official route and price snapshot

The DeepSeek pricing page read on 2026-09-15 identifies alias `deepseek-v4-pro` as model version `DeepSeek-V4-Pro-0813` and says V4 Pro API service continues after September 14, 2026. It lists peak prices per one million tokens of USD 0.044 cache-hit input, USD 1.32 cache-miss input and USD 3.96 output; off-peak rates are half. The proposed 09:30–09:45 Asia/Shanghai window is 01:30–01:45 UTC on a Wednesday and therefore falls in the documented 01:00–04:00 UTC weekday peak period. Sources: https://api-docs.deepseek.com/quick_start/pricing/ and https://api-docs.deepseek.com/api/create-chat-completion/.

Using the transport's 19,000 UTF-8-byte prompt ceiling as a conservative 19,000-input-token arithmetic bound, cache-miss peak input price, the full 8,192-output-token cap and three requests gives USD `0.17256096` before taxes or account-specific adjustments. This is an estimate, not a guaranteed charge or account balance. Actual tokenization, cache status, output length, pricing changes, taxes, market-data fees and balance remain unknown. No recharge or external account probe is authorized or performed.

## Conclusion and remaining gate

R25 offline preparation proves the candidate's local bounds and failure behavior; it does not prove a real provider result. No AI POST, `trade_cal`, other market request, webhook, broker action, holding change, plan activation or consumed R25 claim occurred.

The parent task's attempted live dispatch was rejected by automatic system approval because the exact potentially sensitive payload and external destination were not specifically approved. The remaining approval is therefore narrow: the user must inspect the generated exact review package and specifically authorize those three displayed source/prompt payloads to be sent to DeepSeek at the stated endpoint for the stated extraction tests. General continuation authority is not being requested again.
