# Spec: ai-plan-drafting (AI Plan Drafting)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-ai-plan-drafting.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Convert pasted natural-language trade plans into reviewable `plan-domain` drafts through a user-configured AI service. AI performs extraction and normalization only; it cannot activate plans or participate in live decisions.

The user can configure an OpenAI-compatible service, test connectivity, paste a Chinese plan, inspect field evidence, assumptions, and omissions, edit the structured result, run deterministic validation, and activate through a separate explicit action.

## Tech Stack

- Python 3.11+
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

Every executable field must point to a source location or short evidence excerpt. Unsupported instructions enter `unmapped_text`; they cannot become arbitrary formulas.

### Prompt Contract

The prompt contains:

- the published plan schema and condition allowlist;
- a JSON-only response requirement;
- an instruction to report uncertainty rather than guess;
- an explicit wrapper marking the user's plan as untrusted data;
- no secrets, live positions, or unrelated reports.

Prompts use immutable version identifiers such as `plan-extract-v1`. A prompt change creates a new version and updates golden fixtures.

### Review and Activation Boundary

AI can create drafts only. Activation requires:

- the draft revision is still current;
- no activation-blocking validation error exists;
- the user has resolved all assumptions and warnings;
- every material `unmapped_text` item has an explicit resolution;
- the request carries an optimistic revision and idempotency key.

## Code Style

```python
async def extract_plan(
    request: PlanExtractionRequest,
    provider: AIProvider,
    validator: PlanValidator,
) -> PlanExtractionResult:
    raw = await provider.extract_plan(request)
    parsed = parse_untrusted_json(raw.content)
    draft = TradePlanDraft.model_validate(parsed)
    return build_result(draft=draft, issues=validator.validate_draft(draft))
```

Keep service calls, JSON parsing, domain validation, and persistence separate. Model output is always data, never a command.

## Testing Strategy

- Test configuration bounds, URL validation, secret redaction, prompt construction, JSON parsing, and issue mapping.
- Use a fake OpenAI-compatible service for success, invalid JSON, schema mismatch, timeout, 401/403, 429, 5xx, retry, cancellation, and oversized output.
- Embed prompt-injection samples in plan text and verify they cannot alter the output contract or gain tool access.
- Cover missing dates, ambiguous boundaries, unsupported text, and the Huaya Intelligent example plan.
- Verify AI failure cannot affect already active monitoring plans.
- Verify APIs and logs never return an API key or Authorization header.

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
