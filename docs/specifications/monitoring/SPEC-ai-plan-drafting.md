# Spec: ai-plan-drafting (AI Plan Drafting)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-ai-plan-drafting.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Convert pasted natural-language trade plans into reviewable `plan-domain` drafts through a user-configured AI service. AI performs extraction and normalization only; it cannot activate plans or participate in live decisions.

The default service is DeepSeek through its OpenAI-format Chat Completions endpoint. The user can change the request profile, base URL, model, secret reference, and bounded request settings, or select another reviewed OpenAI-compatible service. The user can test connectivity, paste a Chinese plan, inspect field evidence, assumptions, and omissions, edit the structured result, run deterministic validation, and activate through a separate explicit action.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- `httpx` asynchronous HTTP client
- Pydantic 2 for AI-output and plan-draft validation
- Internal `AIProvider` protocol with explicit DeepSeek and generic OpenAI-compatible request profiles
- `SecretStore` protocol populated by a bounded configured project-secret file for Web and CLI operations
- SQLite for non-secret configuration and audit metadata only

The first release uses an explicit HTTP adapter rather than a vendor AI SDK to reduce coupling.

## Commands

```powershell
python -m pytest tests/unit/test_ai_plan_drafting.py -q
python -m pytest tests/integration/test_ai_provider_contract.py -q
python -m ruff check src/trade_plan_monitor/ai tests/unit/test_ai_plan_drafting.py tests/integration/test_ai_provider_contract.py
```

## Project Structure

```text
src/trade_plan_monitor/ai/
├── models.py             # AI configuration, extraction result, evidence, and issues
├── provider.py           # AIProvider protocol
├── openai_compatible.py  # Resource-bounded HTTP adapter
├── prompts.py            # Versioned prompt construction
├── extraction.py         # Draft extraction, parsing, and validation flow
├── file_secrets.py       # Bounded project-secret file loader
└── secrets.py            # SecretStore protocol and implementations
tests/unit/
└── test_ai_plan_drafting.py
tests/integration/
└── test_ai_provider_contract.py
```

## Public Contract

```python
class AIProvider(Protocol):
    async def test_connection(self, config: AIProviderConfig) -> ProviderTestResult: ...
    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse: ...
```

Configurable non-secret fields include:

- `providerId`, request profile, display name, provider type, base URL, and model;
- project-secret file/key reference and a boolean “secret configured” status;
- timeout, maximum retries, maximum input characters, and maximum output tokens;
- temperature fixed to 0 by default, allowed range 0–0.3;
- prompt version and enabled status.

Stable first-release bounds are: base URL at most 2,048 characters; project-secret file path at most 1,024 characters; secret file at most 65,536 bytes; timeout 1–120 seconds (default 30); retries 0–2 (default 2); input 1–200,000 characters (default 50,000); output 1–16,384 tokens (default 4,096); and temperature 0–0.3 (default 0). Redirects are never configurable and remain disabled. HTTP is accepted only for literal `localhost`, IPv4 loopback, or IPv6 loopback hosts; all other endpoints require HTTPS. Base URLs with credentials, query strings, or fragments are invalid.

### Provider Adapter Contract

The adapter sends `POST {baseUrl}/chat/completions` with Bearer authentication, never sends tools, and returns model content only as untrusted raw text. The generic `OPENAI_COMPATIBLE` profile uses `messages`, `temperature`, `max_completion_tokens`, and `stream=false`. The default `DEEPSEEK` profile follows the current DeepSeek contract: it uses `max_tokens`, sets `thinking={"type":"disabled"}`, adds `response_format={"type":"json_object"}` for plan extraction, and keeps `stream=false`. DeepSeek defaults are `https://api.deepseek.com`, `deepseek-v4-flash`, and project-secret key `DEEPSEEK_API_KEY`. The file reference is `../.env`, resolved relative to `config/app.yaml`, so the local workspace reads its own ignored project-root secret file.

Both Web and CLI resolve the configured secret path relative to the YAML file, read at most 65,536 bytes as strict UTF-8, select exactly one non-empty assignment matching `api_key_ref.key`, and load it into a process-local store created with environment fallback disabled. Missing files, directories, oversized files, invalid UTF-8, missing keys, empty values, and duplicate keys all fail closed without exposing file contents. The Web composition reads configuration once during startup, keeps it immutable for that server lifetime, and exposes extraction through `/plans`. The maintenance CLI keeps `ai test [--config PATH]` and `ai extract [--config PATH] --source FILE`; `test` sends one bounded connectivity request, while `extract` reads one strict UTF-8 regular file, enforces byte and configured character limits, validates the returned draft, and prints it without activating it.

- API keys exist transiently only in the Authorization header and must contain printable ASCII characters. Requests send `Accept-Encoding: identity`.
- Each attempt has the configured timeout and the complete operation uses at most `1 + max_retries` attempts. Transport failures, timeouts, HTTP 408, 429, and 5xx are retryable; numeric `Retry-After` and exponential delays are capped at 2 seconds. Cancellation always propagates.
- Redirect responses are rejected; 401/403 map to authentication failure; other non-retryable 4xx responses map to rejection. Provider response bodies never cross the adapter error boundary.
- Successful responses must be uncompressed or identity-encoded and are read as raw bytes with a 1,048,576-byte ceiling before JSON parsing. Any other content encoding is rejected without decompression.
- The private provider envelope accepts standard response extensions, including token-detail fields, while mapping only `prompt_tokens`, `completion_tokens`, and `total_tokens` into the strict public `AIUsage` value.
- Stable public error codes are `AUTHENTICATION`, `RATE_LIMITED`, `TRANSIENT`, `TIMEOUT`, `INVALID_RESPONSE`, `RESPONSE_TOO_LARGE`, `UNSAFE_REDIRECT`, `CONFIGURATION`, and `REJECTED`. `AIProviderError` exposes only the code, operation, and attempt count, and retains neither an exception cause nor context.

The public secret-management capability is deliberately write/status-only:

```python
class SecretStore(Protocol):
    def replace(self, reference: SecretReference, secret: SecretWrite) -> SecretStatus: ...
    def status(self, reference: SecretReference) -> SecretStatus: ...
```

`SecretStatus` exposes only configured state, source (`STORE`, `ENVIRONMENT`, or `NONE`), a fixed mask, and replacement generation. The generic store retains its environment capability for existing integrations and isolated tests, but the configured Web and CLI compositions always construct it with an empty environment and insert only the value selected from the configured project-secret file. The concrete store keeps runtime materialization package-private so provider composition can authenticate without widening the public management protocol.

The generic injected API contract can accept a replacement secret, but the project-file production composition disables that mutation with `METHOD_NOT_ALLOWED`; no Web page sends it. No read API returns secret material. Logs, errors, audit records, and plan exports contain only non-secret status or references where the legacy injected contract requires them.

### Extraction Result

```python
class PlanExtractionResult(BaseModel):
    request_id: UUID
    provider_id: UUID
    model: str
    prompt_version: str
    source_text_sha256: str
    draft: TradePlanDraft | None
    evidence: list[FieldEvidence]
    assumptions: list[ExtractionIssue]
    warnings: list[ExtractionIssue]
    unmapped_text: list[UnmappedText]
    validation_issues: list[ValidationIssue]
    usage: AIUsage | None
    status: Literal["SUCCEEDED", "INVALID_OUTPUT", "PROVIDER_ERROR", "CANCELLED"]
```

Every non-null executable draft leaf must point to a source location or evidence excerpt containing at least four source characters. Optional null fields require no evidence. Evidence asserted by the model remains untrusted: every successful extraction includes the activation-blocking warning `AI_EVIDENCE_REVIEW_REQUIRED` until a trusted user reviews it.

Unsupported instructions enter `unmapped_text`; they cannot become arbitrary formulas. Every model-produced `unmapped_text` item is normalized to `material=true` until trusted user review, regardless of the model-provided value.

Raw model output is limited to 1,048,576 UTF-8 bytes, 10,000 JSON nodes, and depth 64. Duplicate JSON keys and non-finite numbers are rejected. The complete rendered prompt, including the generated schema, must fit the configured input-character limit before the provider is called. Provider cancellation propagates from extraction; `CANCELLED` is reserved for later orchestration/API job receipts and is not synthesized by this function.

### Prompt Contract

The prompt contains:

- the published plan schema and condition allowlist;
- a JSON-only response requirement;
- an instruction to report uncertainty rather than guess;
- an explicit wrapper marking the user's plan as untrusted data;
- no secrets, live positions, or unrelated reports.

Prompts use immutable version identifiers such as `plan-extract-v1`. A prompt change creates a new version and updates golden fixtures. The complete `plan-extract-v1` prompt, including its generated schema and canonical `GOLDEN_PLAN_SOURCE`, is locked by SHA-256 `1b42865ce7dda121b64a62e15faa1213dd2be55cf654277f0801cd9c29d0dd22`; any template or schema change requires a new version and golden value.

### Review and Activation Boundary

AI can create drafts only. Activation requires:

- the draft revision is still current;
- no activation-blocking validation error exists;
- the user has resolved all assumptions and warnings;
- every material `unmapped_text` item has an explicit resolution;
- the request carries an optimistic revision and idempotency key.

### T037 HTTP Adapter Boundary

The generic local API still supports an injected `AIOperationService` and the plan extraction submission service. The production Web composition instead constructs `ConfiguredAIWebLifecycle` from `config/app.yaml`, attaches its read-only AI summary and extraction service during lifespan startup, and removes both during shutdown. `GET /api/v1/ai-runtime` exposes only provider ID, display name, safe base URL, model, configured/enabled flags, input/output limits, and revision `0`; it cannot expose the secret file path, selected key name, or value.

The project-file production service returns `METHOD_NOT_ALLOWED` for provider create/update, secret replacement, and provider test. Plan extraction requires `Idempotency-Key`, provider identity, and revision `0`; the service hashes each intent, replays only an identical key/request pair, retains at most 1,000 operation records, and runs at most one extraction concurrently. HTTP responses contain only bounded receipts and validated extraction views. Extra fields, raw provider bodies, authorization data, and secret material fail closed before serialization.

`POST /api/v1/plan-extractions` returns `202` after the in-process Web service accepts bounded work; provider I/O occurs in a background task, never in the request handler, and never activates a plan. Operation state is intentionally process-local and is discarded on restart. `GET /api/v1/plan-extractions/{id}` exposes orchestration state plus validated evidence/issues and canonical draft JSON; it never exposes raw model output. Shutdown cancels unfinished tasks, records their local `CANCELLED` state while closing, and releases the shared HTTP client.

### T045 Frontend Intake and Review Boundary

The Vue `PlanWorkbench` is a thin local composition boundary with typed props and emits. It accepts only the read-only configured runtime view, rejects disabled or unconfigured extraction, and emits extraction, stop-waiting, and issue-resolution intents. It has no provider edit, secret input, provider test, Pinia state, domain rule, activation action, or persistent browser state.

`PlanDraftingView` loads the one safe runtime summary, creates one idempotency key per submission, materializes the `202` receipt, and polls the exact operation ID until `SUCCEEDED`, `INVALID_OUTPUT`, `PROVIDER_ERROR`, or `CANCELLED`. Only one local submission/poll runs at once. Unmount and “stop waiting” abort browser work; stopping browser polling does not claim to cancel an accepted server operation. Error messages are fixed and cannot contain provider response or key material.

The source editor treats pasted plans as untrusted plain text and uses the configured input-character limit with Python-compatible Unicode code-point counting. An over-limit edit is rejected atomically and restores the previous complete value. Evidence is tied to the exact submitted source snapshot and hidden when stale. Extracted evidence, assumptions, warnings, unmapped text, validation issues, usage, errors, and canonical draft JSON render through escaped Vue text interpolation only. Structured editing, diff, validation orchestration, and activation remain T046 responsibilities.

## Code Style

```python
async def extract_plan(
    *,
    request_id: UUID,
    source_text: str,
    config: AIProviderConfig,
    provider: AIProvider,
) -> PlanExtractionResult:
    prompt = build_plan_extraction_prompt(
        source_text,
        prompt_version=config.prompt_version,
    )
    request = PlanExtractionRequest(
        request_id=request_id,
        config=config,
        prompt=prompt,
    )
    raw = await provider.extract_plan(request)
    output = parse_untrusted_output(raw.content)
    return validate_and_build_result(output=output, raw=raw)
```

Keep service calls, JSON parsing, domain validation, and persistence separate. Model output is always data, never a command.

## Testing Strategy

- Test configuration bounds, URL validation, secret redaction, prompt construction, JSON parsing, and issue mapping.
- Use fake DeepSeek-profile and generic OpenAI-compatible services for request-shape validation, success, standard response extensions, invalid JSON, schema mismatch, real timeout, 401/403, 429, 5xx, retry, cancellation, compressed response, and oversized output.
- Embed prompt-injection samples in plan text and verify they cannot alter the output contract or gain tool access.
- Cover missing dates, ambiguous boundaries, unsupported text, and the Huaya Intelligent example plan.
- Verify AI failure cannot affect already active monitoring plans.
- Verify APIs, logs, serialized errors, and exception chains never return or retain an API key or Authorization header.

## Threat Model and Boundaries

- Trust boundaries: user text, file-configured base URL, model output, provider error body, and project secret file.
- Protected assets: AI secret, plan integrity, activation authority, and spending limits.
- Always: require HTTPS for non-loopback AI endpoints; reject embedded credentials and unsafe redirects.
- Always: bound input, output tokens, timeout, retry count, and concurrent extractions.
- Always: validate model output with Pydantic before saving or displaying it.
- Ask first: add a vendor adapter, tool use, file upload, or automatic Web research.
- Never: give AI broker, filesystem, shell, database, browser, or market-data tools.
- Never: auto-activate, silently repair validation errors, or call AI during live evaluation.

## Success Criteria

- The user can configure AI in project files, restart Web, and see a safe read-only summary without the secret value or its file/key reference reaching the page.
- A Chinese plan can produce a structured draft with source evidence.
- Unsupported or ambiguous content is visible and blocks activation until resolved.
- Invalid or malicious model output cannot create executable rules.
- AI outages, rate limits, or output errors do not affect active monitoring.
- Token, retry, and concurrency limits prevent unbounded consumption.

## Open Questions

None. Web AI settings editing is intentionally out of scope; both Web and CLI use the configured, Git-ignored project-secret file with no environment-variable fallback.
