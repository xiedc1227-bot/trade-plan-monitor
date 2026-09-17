# R32 AI transient-classification acceptance execution record

Canonical English; `R32-ai-transient-acceptance-execution-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **AI_ACCEPTANCE_FAILED / TERMINAL / NO_RETRY / ISOLATION_PRESERVED**.

## Authorized scope

Proposal `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1` and run `r32-20260917-a` executed from clean branch `codex/r32-ai-transient-acceptance` at commit `276ef0cff7a68e6f08062b9293fdd5f16e43d3be`. The approved ordered review package remained `7832b7e80f791c6a9f58fb30e1bd1f18f1958c60e6d845557d9b4f5e0916bfda`; the package-bound execution attestation SHA-256 was `2326249e2bcfe9600590b11b7fa0dcb512e3b4352b7bbe49ac7aea3a649e87db`.

The approved limits were one `POST https://api.deepseek.com/chat/completions`, zero retries or resubmissions, zero market calls, zero account calls, and an `81s` parent-process hard deadline. The fixed source, prompt, and canonical request-body SHA-256 values were respectively `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`, `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`, and `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`.

## Current official review

Immediately before execution, DeepSeek's official Chat Completions, Models & Pricing, Thinking Mode, and JSON Output documentation confirmed the base URL `https://api.deepseek.com`, path `/chat/completions`, model `deepseek-v4-pro`, disabled thinking mode, JSON object output, and the requested output limit. Official V4 Pro peak rates were `$1.32` per million cache-miss input tokens and `$3.96` per million output tokens; off-peak rates were `$0.66` and `$1.98`. The conservative `20,000` input plus `8,192` output estimates were `$0.05884032` peak and `$0.02942016` off-peak. Actual tokenization, cache split, billing, taxes, and adjustments remain unknown.

## Execution result

- started `2026-09-17T12:12:59.744732+08:00` and finished `2026-09-17T12:13:34.008455+08:00`;
- bounded elapsed time `34,272ms`;
- physical AI attempts `1`; denied-before-network `0`; market attempts `0`; retries/resubmissions `0`;
- terminal audit status `AI_ACCEPTANCE_FAILED`;
- extraction status `INVALID_OUTPUT`, diagnostic stage `schema`, fixed path `draft.plan_id`, reason `SCHEMA`, schema error type `other`;
- provider finish reason `stop`, configured model matched, response usage metadata was available to the diagnostic surface, but no accepted extraction usage record was emitted;
- provider error, transient kind, and timeout kind were all absent; oracle status `NOT_RUN`;
- cleanup `COMPLETE`; review receipts `0`; all 38 independently counted business tables remained at zero rows;
- claim `CONSUMED`; no retry or second POST is permitted.

The earlier authorized launcher invocation stopped before claim creation and before network I/O because the elevated identity could not initially read Git state. A command-scoped safe-directory correction was committed, then the elevated dry preflight returned `ready=true`. That local stop consumed zero physical attempts and was not a provider submission.

## Evidence

Controlled local evidence is under `data/r32-ai-transient-acceptance/r32-20260917-a/` and remains ignored from Git. No credentials, authorization headers, raw prompt/source, raw provider content, exception text, or direct IP addresses are reproduced here.

| File | SHA-256 |
|---|---|
| `claim.json` | `0bc80711d74c2313b01cf335854058a1942540152f9ab0ecd66074e22e21df5f` |
| `audit.json` | `92b8973961cf39f1f7e57586de77c5b40346dd0d5085569684044f696dc7b8f7` |
| `physical-attempts.json` | `1217905754c7c4b3c77634defebad8e1d35074dd3a16f45575baf8839c3637a8` |
| `monitor.ai-extraction-diagnostics.jsonl` | `a0e0acf8f4ff303e4e2762614d322ea625eb3fc183c2866a9ed94194a5de557c` |

R32 is terminal. Do not retry, resubmit, replay R30, or start R33 automatically.
