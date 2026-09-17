# R31 AI transient diagnostics report

Canonical English; `R31-ai-transient-diagnostics-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_DIAGNOSIS_COMPLETE / SAFE_CLASSIFICATION_ADDED / R30_CAUSE_UNKNOWN / ZERO_EXTERNAL_CALLS**.

## Scope and evidence boundary

R31 investigated the provider-stage `PROVIDER_ERROR / TRANSIENT` recorded by R30 without replaying R30 and without making any AI, market-data, account, pricing, route, DNS, TCP, TLS, proxy, certificate, or other network probe. The retained R30 artifacts under `data/r30-ai-timeout-budget-acceptance/r30-20260917-a/` were read only through fixed safe fields and counts.

R30 proves one admitted physical AI attempt, zero retries, zero market/account calls, a provider-stage `TRANSIENT`, `attempts=1`, no response, no usage, no timeout kind, completed cleanup, consistent audit/journal data, and zero rows across 38 business tables. Its `261` bounded-work milliseconds are a whole bounded-work duration, not a precise HTTP timing measurement. The v2 sidecar did not preserve a transient subtype. It is therefore impossible to recover whether the historical failure was an HTTP status, DNS, TCP, TLS, proxy, protocol, response-read, decoding, or other request failure. Provider receipt, processing, and billing remain unknown.

## Exact R30 path

1. `AIBudgetTransport` validates the exact HTTPS route and frozen v6 request body, then admits and counts the physical attempt before delegating to its inner transport. A guard denial raises `BudgetDenied`; it is not an `httpx.RequestError` and cannot become `TRANSIENT` through the provider adapter.
2. The R30 `AsyncClient` wraps that guard with `follow_redirects=False`, `trust_env=False`, connect/write/pool timeouts of `30` seconds, and a read timeout of `60` seconds. The default inner `AsyncHTTPTransport` uses `retries=0` and `trust_env=False`.
3. The provider applies an independent `65`-second `asyncio.timeout`. Its catch order preserves `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`, the overall deadline, and other `httpx.TimeoutException` values as `TIMEOUT` with a closed timeout kind.
4. Before R31, both HTTP `408/5xx` responses and every remaining `httpx.RequestError` became only `TRANSIENT`. `AIProviderError`, extraction diagnostics, and the v2 sidecar retained no request-error subtype or transient HTTP group.
5. Strict schema, mapping, and literal-oracle stages run only after a valid response envelope. They did not run in R30 and cannot explain its provider-stage result.

## Safe local environment findings

The inspected environment used Python `3.14.7`, HTTPX `0.28.1`, OpenSSL `3.5.7`, and certifi `2026.07.22`; the certifi `cacert.pem` path existed. The read-only original configuration was `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor\config\app.yaml`, with SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`. It configured HTTPS host `api.deepseek.com`, a present API key, and model identities `deepseek-flash` and `deepseek-v4-pro`; no secret value was printed or copied.

The R30 binding selected `deepseek-v4-pro` and locally overrode only `max_retries=0`, `max_output_tokens=8192`, `prompt_version=plan-extract-v6`, overall timeout `65`, transport timeout `30`, and read timeout `60`. The sent request body remains SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`.

No proxy or certificate environment variable among `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, and `CURL_CA_BUNDLE` was present during the offline inspection. Independently, both client layers used `trust_env=False`. Installed HTTPX source confirmed that `trust_env=False` bypasses environment certificate paths and falls back to the certifi CA bundle when verification remains `True`. R31 did not disable TLS verification, add a proxy, change a CA bundle, or alter transport policy.

## Implemented diagnostic contract

R31 adds closed `AIProviderTransientKind` values and never copies exception text, response text, headers, URLs, IP addresses, errno text, Pydantic input/context, prompts, or credentials:

| Source with structural evidence | `transientKind` |
|---|---|
| HTTP 408 | `HTTP_408` |
| HTTP 5xx | `HTTP_5XX` |
| `ConnectError` with a bounded `socket.gaierror` cause chain | `DNS` |
| `ConnectError` with a bounded `ssl.SSLError` cause chain | `TLS` |
| Other `ConnectError` | `CONNECT` |
| `ProxyError` | `PROXY` |
| `ProtocolError` or `UnsupportedProtocol` | `PROTOCOL` |
| `ReadError` / `WriteError` / `CloseError` | `READ` / `WRITE` / `CLOSE` |
| `DecodingError` | `DECODING` |
| Other `NetworkError` | `NETWORK` |
| Unrecognized `RequestError` or legacy transient construction | `UNKNOWN` |

The category is valid only when `providerErrorCode=TRANSIENT`. Timeout and schema diagnostics keep their existing contracts and emit `transientKind=null`. New sidecar records use `version=3`; R27/R29/R30 assessment paths accept both v2 and v3, and a legacy transient without a subtype normalizes to `UNKNOWN`.

## Verification

The combined focused group passed **119/119**, with **2** known installed-Web-asset-dependent R15 cases deselected and one existing Starlette/httpx deprecation warning. Coverage includes:

- all closed transient branches, bounded DNS/TLS cause inspection, `UNKNOWN` fallback, and absence of injected secrets from error state and sidecars;
- HTTP-status retry bounds, one-attempt zero-retry behavior, timeout subtype compatibility, schema diagnostics, normal successful extraction, strict mapping, and literal oracle behavior;
- v2 reader compatibility and v3 sidecar emission;
- the actual R30 guard/factory path with one physical start, zero retry, zero market calls, cleanup completion, audit output, and all business tables empty.

Ruff passed for every changed Python source and test after the implementation. No production configuration, provider, route, request body, prompt, output cap, timeout, retry policy, TLS verification, proxy behavior, holdings, plan state, or R30 evidence was changed.

## External-call accounting

- AI requests: `0`;
- market-data requests: `0`;
- account, balance, model-list, route, pricing, DNS, TCP, TLS, proxy, or certificate probes: `0`;
- retries/resubmissions: `0`;
- R30 replay: `0`;
- new execution claim created or consumed: `0`.

## Minimum next-round recommendation

Do not automatically open or execute R32. If the user later wants one new live acceptance attempt, first prepare a new exact review package and claim for at most `1` AI POST, `0` market calls, and `0` retries while keeping the v6 `LITERAL` request body and SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c` unchanged. The new request could add information because a repeated transient would now distinguish the fixed HTTP/transport categories above rather than only reporting `TRANSIENT`; a valid response would continue into strict schema, mapping, and oracle checks.

If that future attempt reports `UNKNOWN`, do not issue another paid request merely to repeat it. Stop and extend offline structural classification only when a concrete local exception type can be proven. Any new live attempt requires fresh user approval and a fresh one-shot claim.
