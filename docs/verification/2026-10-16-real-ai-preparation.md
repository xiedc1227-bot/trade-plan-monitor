# Actual-source live AI preparation verification — 2026-10-16

Canonical English; Chinese review copy: [2026-10-16-real-ai-preparation.zh-CN.md](2026-10-16-real-ai-preparation.zh-CN.md).

## LIVE-V01. Authorization and inputs

The user explicitly authorized live AI extraction of the four original TXT files and confirmed the effective trading dates below. The complete texts were read from `data/research/shengxin-plan-extraction-20261010/`, without rewriting them. `plans.json` and `entry-fields.json` were not used as plans, context or supplements. Authored and historical availability timestamps remained null.

| Source | Confirmed effective trading date | Initial request characters |
|---|---|---:|
| `01-20260924-104506.txt` | 2026-09-24 | 44,927 |
| `02-20260928-092555.txt` | 2026-09-28 | 44,260 |
| `03-20260930-095728.txt` | 2026-09-30 | 45,822 |
| `04-20261009-091956.txt` | 2026-10-09 | 47,746 |

The Web service at `127.0.0.1:8765` was not running. Verification used the current production `ConfiguredAIWebLifecycle`, `PreparationService`, extraction functions and HTTP adapter directly, with separate SQLite stores under `data/verification/2026-10-16-real-ai/`. It did not modify operational preparations or application configuration. The model was the configured `deepseek-flash`; all five completed HTTP calls used the real provider, with no mocked responses. API keys and authorization headers were not logged.

## LIVE-V02. Ordered collection with current configuration

The current settings were `max_input_chars=50000`, `max_output_tokens=4096`, `timeout_seconds=30`, `max_retries=2`. All four confirmed dates passed the collection preflight. The first request was sent at 2026-10-16 16:15:13 Shanghai time and received HTTP 200 with `finish_reason=length`, using 15,282 input and 4,096 output tokens. The complete prompt passed the unchanged input guard, but the provider response was truncated by the output budget.

Preparation `shengxin-real-ai-2f694787-e1f0-4555-87d4-c3d29c86c806` ended as `FAILED`: item 1 recorded one failed attempt with `AI_OUTPUT_TRUNCATED`; items 2–4 remained `WAITING` with zero attempts. The work claim was released. Reading the frozen preparation was rejected with `REVIEW_REQUIRED`. No review was approved and no backtest was submitted.

## LIVE-V03. Independent full-output diagnostics

To inspect all four actual texts beyond the truncation, each source was then sent once through `extract_loop_plan` as an **independent initial-source diagnostic**, with temporary in-memory settings `max_output_tokens=16384`, `timeout_seconds=120`, `max_retries=0`. The input guard remained 50,000. The source texts, model and provider were unchanged. These calls are not successor extraction and do not establish a valid continuous plan chain.

All four returned HTTP 200 and `finish_reason=stop` between 16:16 and 16:18 Shanghai time. None produced an accepted candidate:

| Source | Output tokens | Result | First blocking evidence |
|---|---:|---|---|
| 1 | 7,275 | `AI_OUTPUT_INVALID` | Extra top-level `type: "json_object"`; the schema forbids extra fields. |
| 2 | 6,538 | `AI_FIELD_EVIDENCE_INVALID` | `BACKGROUND requires a registered exact scope exclusion`; 59 background clauses lacked registered exclusions, starting with the section heading `## 1. 当前结论与行情摘要`. |
| 3 | 7,976 | `AI_OUTPUT_INVALID` | `bindings[8].unit`, `bindings[9].unit` and `bindings[10].unit` were `FEN`, outside the allowed unit enum. |
| 4 | 8,716 | `AI_OUTPUT_INVALID` | Extra top-level `type: "json_object"`; the schema forbids extra fields. |

Offline inspection of source 1 after removing only the extra `type` field also reached the same background-exclusion rejection as source 2. This diagnostic edit was never persisted as an accepted candidate. It demonstrates that ignoring the extra field alone would not resolve the extraction flow.

The five live calls reported 77,788 input tokens and 34,601 output tokens, 112,389 total. No further paid retries were made. Full responses, schema error locations, requests metadata and the collection record are retained locally in `data/verification/2026-10-16-real-ai/`; `expanded-output-diagnostics/` contains the four independent results. The files contain source/model output, not credentials. `diagnostic` is excluded by the result model's normal serialization; failure details in this report come from captured provider responses and offline schema/mapping validation, not an assumption that a serialized null means diagnostics were absent.

## LIVE-V04. Conclusion and remaining work

**The four-source workflow cannot yet continue to backtest.** Date confirmation and the input-budget repair work in the live path. The current output budget truncates the first result; increasing it exposes additional schema and source-mapping failures. This is not evidence that the confirmed dates are missing or that the original texts must be rewritten.

Before this workflow can pass, the output budget and time budget need to support complete responses; extraction instructions/output handling must satisfy the strict field and unit contract; and background treatment must align with source-fidelity validation without discarding trading conditions. A later run must then exercise the real successor context, resolve any genuine strategy/account unknowns, and complete the explicit review/freeze gate. This verification did not fabricate missing facts, relax validation, approve a plan, or establish a successful historical replay.
