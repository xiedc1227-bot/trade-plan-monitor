# Spec: ai-plan-drafting (AI Plan Drafting)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-ai-plan-drafting.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Convert pasted natural-language trade plans into reviewable `plan-domain` drafts through a user-configured AI service. AI performs extraction and normalization only; it cannot activate plans or participate in live decisions.

The user can configure an OpenAI-compatible service, test connectivity, paste a Chinese plan, inspect field evidence, assumptions, and omissions, edit the structured result, run deterministic validation, and activate through a separate explicit action.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- `httpx` asynchronous HTTP client
- Pydantic 2 for AI-output and plan-draft validation
- Internal `AIProvider` protocol with an OpenAI-compatible adapter
- `SecretStore` protocol backed by the operating-system credential store, with environment-variable references as a required fallback
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

- `providerId`, display name, provider type, base URL, and model;
- secret reference and a boolean “secret configured” status;
- timeout, maximum retries, maximum input characters, and maximum output tokens;
- temperature fixed to 0 by default, allowed range 0–0.3;
- prompt version and enabled status.

Stable first-release bounds are: base URL at most 2,048 characters; timeout 1–120 seconds (default 30); retries 0–2 (default 2); input 1–200,000 characters (default 50,000); output 1–16,384 tokens (default 4,096); and temperature 0–0.3 (default 0). Redirects are never configurable and remain disabled. HTTP is accepted only for literal `localhost`, IPv4 loopback, or IPv6 loopback hosts; all other endpoints require HTTPS. Base URLs with credentials, query strings, or fragments are invalid.

### Provider Adapter Contract

The first adapter sends `POST {baseUrl}/chat/completions` with Bearer authentication. It uses `messages`, `temperature`, `max_completion_tokens`, and `stream=false`; it never sends tools and returns model content only as untrusted raw text.

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

`SecretStatus` exposes only configured state, source (`STORE`, `ENVIRONMENT`, or `NONE`), a fixed mask, and replacement generation. A non-empty named environment variable is the required fallback when the process-local store has no replacement. The concrete store keeps runtime materialization package-private so provider composition can authenticate without widening the public management protocol. The process-local implementation supports scaffolding and deterministic tests; selecting the durable operating-system credential adapter remains an explicit open question.

The API can accept a replacement secret and write it to the secret store, but no read API returns it. Logs, errors, audit records, and plan exports contain only a secret reference and masked metadata.

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

The local API exposes AI only through an injected `AIOperationService` and the plan extraction submission method on `PlanOperationService`. Configuration requests contain the complete non-secret `AIProviderConfig` shape in camelCase plus `expectedRevision`; `PATCH /api/v1/ai-providers/{id}` is a full revision-guarded replacement, not a partial merge. The HTTP schema calls the concrete `AIProviderConfig` class-local wrap validator and does not move sanitization to `_AIValue`. Secret replacement embeds the existing `SecretWrite` value so its own class-local wrap validator remains authoritative; no base-class validator is introduced.

Every provider create/update, secret replacement, provider test, and plan extraction requires `Idempotency-Key` and `expectedRevision`. The injected application service atomically owns request hashing, duplicate/replay handling, revision comparison, persistence, and audit insertion. HTTP responses expose only non-secret provider configuration, fixed masked secret status, or bounded operation receipts. Extra service fields, raw provider bodies, authorization data, and secret material fail closed before serialization.

`POST /api/v1/plan-extractions` and `POST /api/v1/ai-provider-tests` return `202` only after the application service durably accepts bounded work. The request handler does not call the provider, execute extraction, or activate a plan. `GET /api/v1/plan-extractions/{id}` exposes orchestration states plus validated evidence/issues and canonical draft JSON; it never exposes raw model output. `CANCELLED` is represented only by this orchestration status boundary and remains absent from the pure T017 extraction function.

### T045 Frontend Intake and Review Boundary

The Vue `PlanWorkbench` is a thin local composition boundary with typed props and emits. It selects only enabled providers for extraction, submits revision-guarded provider-test, secret-replacement, extraction, cancellation, and issue-resolution intents, and owns no API client, Pinia state, domain rule, activation action, or persistent browser state. Provider-test receipts require an explicit provider identity and pending/settlement state so an old receipt cannot be attributed to the current provider and rapid retries cannot create duplicate durable work.

Secret input is transient, write-only, cleared when provider identity changes and before replacement is emitted, and never rendered after submission. Secret and source limits use Python-compatible Unicode code-point counting. An over-limit edit is rejected atomically, restores the previous complete valid value, exposes an accessible error, and cannot emit a silently truncated secret or plan. Whitespace-only secrets, disabled providers, oversized final commands, duplicate pending submissions, and retry-before-receipt paths fail closed.

The source editor treats pasted plans as untrusted plain text. It locks immediately around submission, binds evidence to the exact submitted source snapshot, releases local pending state when submission fails before a new operation identity, and exposes cancellation only for a real `QUEUED` or `RUNNING` operation. Extracted evidence, assumptions, warnings, unmapped text, validation issues, usage, and bounded errors render through Vue text interpolation only. Duplicate review identities cannot be resolved, long unbroken text wraps, and stale evidence is hidden after source changes. Structured editing, diff, validation orchestration, and activation remain T046 responsibilities.

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
- Use a fake OpenAI-compatible service for success, standard response extensions, invalid JSON, schema mismatch, real timeout, 401/403, 429, 5xx, retry, cancellation, compressed response, and oversized output.
- Embed prompt-injection samples in plan text and verify they cannot alter the output contract or gain tool access.
- Cover missing dates, ambiguous boundaries, unsupported text, and the Huaya Intelligent example plan.
- Verify AI failure cannot affect already active monitoring plans.
- Verify APIs, logs, serialized errors, and exception chains never return or retain an API key or Authorization header.

## Threat Model and Boundaries

- Trust boundaries: user text, configurable base URL, model output, provider error body, and secret input.
- Protected assets: AI secret, plan integrity, activation authority, and spending limits.
- Always: require HTTPS for non-loopback AI endpoints; reject embedded credentials and unsafe redirects.
- Always: bound input, output tokens, timeout, retry count, and concurrent extractions.
- Always: validate model output with Pydantic before saving or displaying it.
- Ask first: add a vendor adapter, tool use, file upload, or automatic Web research.
- Never: give AI broker, filesystem, shell, database, browser, or market-data tools.
- Never: auto-activate, silently repair validation errors, or call AI during live evaluation.

## Success Criteria

- The user can configure and test an AI service without secrets appearing in read responses.
- A Chinese plan can produce a structured draft with source evidence.
- Unsupported or ambiguous content is visible and blocks activation until resolved.
- Invalid or malicious model output cannot create executable rules.
- AI outages, rate limits, or output errors do not affect active monitoring.
- Token, retry, and concurrency limits prevent unbounded consumption.

## Open Questions

Select the concrete operating-system secret-store implementation after confirming Windows Credential Manager support during scaffolding; environment-variable references remain the required fallback.
