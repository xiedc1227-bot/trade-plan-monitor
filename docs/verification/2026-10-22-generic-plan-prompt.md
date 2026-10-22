# Generic plan-generation prompt verification — 2026-10-22

[Chinese review copy](2026-10-22-generic-plan-prompt.zh-CN.md). Prompt: [English README](../../README.md#generic-trade-plan-prompt), [Chinese README](../../README.zh-CN.md#generic-trade-plan-prompt). [Machine-readable evidence](evidence/2026-10-22-generic-plan-prompt/verification.json).

## GP-V01. Outcome and scope

**NOT_FULLY_PASSED.** The generic prompt is saved in both README files. Final synthetic generation correctly isolates symbols, preserves requested reminder counts and blocks missing required parameters/unsupported dependencies. Neither normal reminder source passes the real extractor's source review, so neither yields an accepted draft. This is not ready to be described as universally validated.

The user selected cross-symbol and missing-input verification. Tests use synthetic observations and explicitly prohibit live-market fetching. They do not certify current quotes, financial conclusions, all supported trading rules or every stock/board. The Chinese prompt was used for live generation; the English counterpart received documentation parity checks, not a separate live generation trial.

## GP-V02. Method and preserved evidence

The prompt was first saved before model testing. Each round reads the actual prompt block from `README.zh-CN.md`, appends the synthetic case and verified local software-contract facts, then calls the configured `deepseek-flash` provider to generate A/B. The transport requires a JSON object containing only A and B strings. That delivery envelope does not change policy meaning. Only the unchanged A string is passed to the production `extract_plan` flow using `plan-extract-v9`; B is never extraction source.

Three diagnosed prompt versions were tested, not repeated unchanged requests until success: 12 generation calls and 6 extraction calls. Limits remain 50,000 input characters, 4,096 output tokens, 30 seconds and 2 configured retries. No configuration, runtime implementation, schema or validator was changed. The provider adapter retains its existing transport retry policy.

For each version, `prompt.json` stores the exact prompt string/preflight. Case JSON files retain the request suffix, unmodified generation/extraction response strings inside their envelopes, A/B strings, expected data, strict results and diagnostic observations. JSON string encoding preserves embedded newline semantics across Git/platform formatting. Text hashes refer to UTF-8 encodings of those decoded strings. All earlier failures remain available.

## GP-V03. Findings and prompt corrections

- Initial generation dropped `.SH` from a stock code. The source reviewer correctly rejected the inferred normalized value because the exact source lacked it. The prompt now requires full identifiers and explicit `.SH`→`SSE`, `.SZ`→`SZSE`, `.BJ`→`BSE` mapping; identity/trading scope still requires verification.
- A blocked missing-limit response avoided inventing a limit but included a hypothetical rule in its explanation. The initial strict format check flagged those field tokens. Blocked A now contains only `暂不提供可导入正文。`; details belong in B. This was a source-format finding, not evidence of invented inventory.
- The prompt now separates unknown conditions from verified true/false results, uses compact rule grouping and only registered unchanged product defaults. No strategy quantity, price, confirmation, deadline or grouping is inferred from a software default.
- In round 2 the two-reminder extraction reached `finish_reason=length` at 4,096 output tokens. It was rejected as `AI_OUTPUT_TRUNCATED`; no partial draft was accepted. Redundant software-constant declarations were reduced using the existing product contract. Both final extraction responses complete with `finish_reason=stop`, at 2,693 and 3,870 completion tokens respectively.
- The final A format uses the reviewer's already registered standalone empty-group declarations. Despite the change, the extractor repeatedly returns binding values of the string `"[]"` for `ordinary_rules` and `risk_branches`. Actual candidate values are JSON arrays `[]`. Exact-type validation correctly rejects them as `AI_FIELD_EVIDENCE_INVALID`. Changing source wording did not resolve this internal model-output contract failure.

There was no prefix stripping, binding replacement, manual response repair or relaxed validation. Parsed raw candidates below are diagnostic observations, not accepted plans.

## GP-V04. Final round matrix

| Synthetic case | Required result | Generation observation | Real extraction |
| --- | --- | --- | --- |
| `600010.SH`, limit 500, reference 12.34, close strictly below 12.07 | 1 reminder, 0 ordinary/risk rules | Correct symbol/limit; raw candidate has 1 reminder | Rejected: empty-array binding strings; accepted draft is null |
| `000858.SZ`, limit 800, reference 78.90, close strictly below 74.32 or strictly above 85.67 as separate reminders | 2 reminders, 0 ordinary/risk rules | Correct symbol/limit; raw candidate has 2 reminders; no previous-stock parameters inherited | Rejected: same binding-type defect; accepted draft is null |
| `600519.SH`, unknown position limit | Block A without guessing a limit | Correct blocking sentence; no importable policy | Not called, as required |
| `600036.SH`, runtime index-dependent quantity/confirmation, no authorized fallback | Block the whole dependent trade rule | Correctly blocks; no stripped-down BUY or invented reminder | Not called, as required |

Final full-chain acceptance is **2 correctly blocked cases out of 4; 0 accepted sources out of 2 normal sources**. Generation isolation and expected candidate counts do not substitute for complete source review.

## GP-V05. Checks and protected state

- 30 existing source-contract/security tests pass, including strict rejection controls.
- Both README prompt blocks have 10 main sections and 17 subsections, matching heading structure and identical machine-layout examples. Required technical tokens/thresholds and absence of old-stock identifiers/prices were checked.
- Current prompt-string SHA256: English `a792fa3a9574fa194bed96372b5cf308135251ac0b679e2f6acbf19e9950879b`; Chinese `4a3756d32bd49884e0d4e5f1a0291a75e76cedf5ca83697550219554e382ad6a`.
- AI extraction/source-review/domain validator files remain unchanged. Unrelated concurrent CPU-attribution work is excluded.
- Read-only before/after snapshots match for the existing draft, provenance, activation, actual/simulated positions, protected risks, daily records, storage constraint and configuration. The generation/extraction runner itself does not open application storage.
- The actual saved draft remains `DRAFT`, review unconfirmed, inactive, with 1 technical reminder and 0 ordinary/risk rules. No draft is saved by this validation; no inventory is initialized or changed.

Executed contract/security command from the project root:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_current_review_contract.py tests/unit/test_current_plan_extraction_security.py -q --tb=short --basetemp .tmp/generic-prompt-contract-20261022-67b8ed
```

## GP-V06. Remaining work

Before claiming full extraction readiness, correct the internal AI instruction/schema communication for empty-array binding types and add focused regression covering these retained raw responses. Preserve exact source review; converting `"[]"` into `[]` after generation is not an acceptable fix.

Then repeat a bounded real verification on both normal cases and retain blocked-case checks. Multi-rule output still has limited headroom under 4,096 tokens; larger/more complex trading plans are unverified and must not be simplified or partially accepted merely to fit. This documentation task does not authorize runtime-contract implementation changes, plan review, activation or inventory mutation.
