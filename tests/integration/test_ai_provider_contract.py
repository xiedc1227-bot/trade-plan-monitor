import asyncio
import gzip
import json
import socket
import ssl
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderProfile,
    PlanExtractionStatus,
    SecretReference,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.provider import (
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderOperation,
    AIUsage,
    PlanExtractionRequest,
    ProviderTestResult,
    RawAIResponse,
)
from trade_plan_monitor.ai.secrets import InMemorySecretStore, SecretWrite
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.runtime.request_control import (
    AIQueueFullError,
    AIRequestController,
)
from trade_plan_monitor.web.ai_diagnostics import append_extraction_diagnostic

PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000016")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000000116")
SECRET_VALUE = "test-api-key-sensitive-value"
SAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
)


def _config(**changes: object) -> AIProviderConfig:
    values: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "display_name": "Local compatible service",
        "base_url": "http://127.0.0.1:18080/v1",
        "model": "test-model",
        "secret_ref": SecretReference(
            key="ai/provider/local-test",
        ),
        "timeout_seconds": 5,
        "max_retries": 2,
        "max_input_chars": 1_000,
        "max_output_tokens": 128,
        "temperature": 0,
        "prompt_version": "plan-extract-v3",
    }
    values.update(changes)
    return AIProviderConfig(**values)


def _secret_store(config: AIProviderConfig) -> InMemorySecretStore:
    store = InMemorySecretStore()
    store.replace(config.secret_ref, SecretWrite(value=SECRET_VALUE))
    return store


def _completion_response(
    *,
    content: str = '{"draft": {}}',
    model: str = "test-model",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "total_tokens": 28,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        },
    )


def _extraction_content() -> str:
    draft = load_plan_yaml(SAMPLE_PLAN_PATH.read_text(encoding="utf-8")).model_dump(mode="json")

    def leaf_paths(value: object, path: str = "") -> list[str]:
        if isinstance(value, dict):
            return [
                leaf_path
                for key, child in value.items()
                for leaf_path in leaf_paths(child, f"{path}.{key}" if path else str(key))
            ]
        if isinstance(value, list):
            return [
                leaf_path
                for index, child in enumerate(value)
                for leaf_path in leaf_paths(child, f"{path}[{index}]")
            ]
        return [path]

    return json.dumps(
        {
            "draft": draft,
            "evidence": [{"path": path, "excerpt": "华亚智能"} for path in leaf_paths(draft)],
            "assumptions": [],
            "warnings": [],
            "unmapped_text": [],
        },
        ensure_ascii=False,
    )


def test_plan_extraction_request_enforces_the_configured_input_limit() -> None:
    config = _config(max_input_chars=4)

    accepted = PlanExtractionRequest(
        request_id=REQUEST_ID,
        config=config,
        prompt="计划四字",
    )

    assert accepted.prompt == "计划四字"
    with pytest.raises(ValidationError, match="max_input_chars"):
        PlanExtractionRequest(
            request_id=REQUEST_ID,
            config=config,
            prompt="计划超过四字",
        )


def test_provider_results_are_strict_immutable_non_secret_values() -> None:
    usage = AIUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    raw = RawAIResponse(
        request_id=REQUEST_ID,
        provider_id=PROVIDER_ID,
        model="test-model",
        content='{"draft": {}}',
        finish_reason="stop",
        usage=usage,
        attempts=1,
    )
    connection = ProviderTestResult(
        provider_id=PROVIDER_ID,
        model="test-model",
        connected=True,
        attempts=1,
    )

    assert raw.usage == usage
    assert connection.connected is True
    with pytest.raises(ValidationError, match="Extra inputs"):
        AIUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details={"cached_tokens": 1},
        )
    with pytest.raises(ValidationError, match="frozen"):
        raw.content = "changed"
    with pytest.raises(ValidationError, match="Extra inputs"):
        ProviderTestResult(
            provider_id=PROVIDER_ID,
            model="test-model",
            connected=True,
            attempts=1,
            api_key="must-not-be-accepted",
        )


def test_ai_provider_protocol_is_structural_and_async() -> None:
    class FakeProvider:
        async def test_connection(self, config: AIProviderConfig) -> ProviderTestResult:
            return ProviderTestResult(
                provider_id=config.provider_id,
                model=config.model,
                connected=True,
                attempts=1,
            )

        async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse:
            return RawAIResponse(
                request_id=request.request_id,
                provider_id=request.config.provider_id,
                model=request.config.model,
                content="{}",
                finish_reason="stop",
                usage=None,
                attempts=1,
            )

    assert isinstance(FakeProvider(), AIProvider)


def test_legacy_transient_provider_error_defaults_to_unknown_category() -> None:
    error = AIProviderError(
        AIProviderErrorCode.TRANSIENT,
        operation=AIProviderOperation.TEST_CONNECTION,
        attempts=1,
    )

    assert error.transient_kind.value == "UNKNOWN"


def test_connection_uses_the_bounded_chat_completions_contract() -> None:
    config = _config()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _completion_response(content="OK")

    async def scenario() -> ProviderTestResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            assert isinstance(provider, AIProvider)
            return await provider.test_connection(config)

    result = asyncio.run(scenario())

    assert result == ProviderTestResult(
        provider_id=PROVIDER_ID,
        model="test-model",
        connected=True,
        attempts=1,
    )
    assert len(captured) == 1
    request = captured[0]
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == "http://127.0.0.1:18080/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {SECRET_VALUE}"
    assert request.headers["Accept-Encoding"] == "identity"
    assert request.headers["Content-Type"] == "application/json"
    assert body["model"] == "test-model"
    assert body["max_completion_tokens"] == 1
    assert body["stream"] is False
    assert "max_tokens" not in body
    assert "tools" not in body
    assert SECRET_VALUE not in request.content.decode("utf-8")


def test_extract_plan_returns_only_validated_envelope_and_untrusted_raw_content() -> None:
    config = _config(max_output_tokens=128, temperature=0.2)
    prompt = "Return the structured draft as JSON only."
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return _completion_response(content='{"zones": []}', model="served-model")

    async def scenario() -> RawAIResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            return await provider.extract_plan(
                PlanExtractionRequest(
                    request_id=REQUEST_ID,
                    config=config,
                    prompt=prompt,
                )
            )

    raw = asyncio.run(scenario())

    assert raw.request_id == REQUEST_ID
    assert raw.provider_id == PROVIDER_ID
    assert raw.model == "served-model"
    assert raw.content == '{"zones": []}'
    assert raw.finish_reason == "stop"
    assert raw.usage == AIUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28)
    assert raw.attempts == 1
    assert captured_body == {
        "model": "test-model",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_completion_tokens": 128,
        "stream": False,
    }


def test_deepseek_profile_uses_current_json_chat_completion_contract() -> None:
    config = _config(
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        max_output_tokens=256,
        temperature=0,
    )
    prompt = "Return the structured draft as JSON only."
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        return _completion_response(content='{"draft": {}}', model="deepseek-v4-flash")

    async def scenario() -> RawAIResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                profile=AIProviderProfile.DEEPSEEK,
            )
            return await provider.extract_plan(
                PlanExtractionRequest(
                    request_id=REQUEST_ID,
                    config=config,
                    prompt=prompt,
                )
            )

    result = asyncio.run(scenario())

    assert result.model == "deepseek-v4-flash"
    assert captured_body == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    assert "max_completion_tokens" not in captured_body


def test_connection_rejects_invalid_json_without_retrying_or_retaining_it() -> None:
    config = _config(max_retries=2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=f"not-json {SECRET_VALUE}".encode())

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.INVALID_RESPONSE
    assert error.attempts == 1
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET_VALUE not in f"{error!r} {vars(error)!r}"
    assert calls == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "test-model", "choices": []},
        {
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": 12},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "{}",
                        "tool_calls": [{"type": "function"}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ],
)
def test_extract_plan_rejects_malformed_or_tool_call_envelopes(payload: object) -> None:
    config = _config()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.extract_plan(
                    PlanExtractionRequest(
                        request_id=REQUEST_ID,
                        config=config,
                        prompt="Return JSON.",
                    )
                )
            assert captured.value.code is AIProviderErrorCode.INVALID_RESPONSE
            assert captured.value.attempts == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (307, AIProviderErrorCode.UNSAFE_REDIRECT),
        (400, AIProviderErrorCode.REJECTED),
        (401, AIProviderErrorCode.AUTHENTICATION),
        (403, AIProviderErrorCode.AUTHENTICATION),
    ],
)
def test_non_retryable_http_failures_have_stable_sanitized_codes(
    status_code: int,
    expected_code: AIProviderErrorCode,
) -> None:
    config = _config(max_retries=2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status_code,
            json={"error": {"message": f"provider echoed {SECRET_VALUE}"}},
            headers={"Location": "http://169.254.169.254/latest/meta-data"},
        )

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is expected_code
    assert error.attempts == 1
    assert calls == 1
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET_VALUE not in str(error)
    assert SECRET_VALUE not in repr(error)
    assert SECRET_VALUE not in repr(vars(error))


def test_rate_limit_honors_retry_after_then_returns_the_second_attempt() -> None:
    config = _config(max_retries=2)
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.75"})
        return _completion_response()

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> RawAIResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                sleep=sleeper,
            )
            return await provider.extract_plan(
                PlanExtractionRequest(
                    request_id=REQUEST_ID,
                    config=config,
                    prompt="Return JSON.",
                )
            )

    raw = asyncio.run(scenario())

    assert raw.attempts == 2
    assert calls == 2
    assert delays == [0.75]


def test_5xx_retries_stop_at_the_configured_bound() -> None:
    config = _config(max_retries=2)
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, content=b"provider internal details")

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                sleep=sleeper,
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.TRANSIENT
    assert error.transient_kind.value == "HTTP_5XX"
    assert error.attempts == 3
    assert calls == 3
    assert delays == [0.25, 0.5]


def test_timeout_retries_stop_at_the_configured_bound() -> None:
    config = _config(max_retries=2)
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider timeout details", request=request)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                sleep=sleeper,
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.TIMEOUT
    assert error.attempts == 3
    assert calls == 3
    assert delays == [0.25, 0.5]


def test_oversized_response_is_stopped_before_json_parsing() -> None:
    config = _config(max_retries=2)
    calls = 0
    yielded_chunks = 0

    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal yielded_chunks
            for _ in range(20):
                yielded_chunks += 1
                yield b"x" * 65_536

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=OversizedStream())

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.RESPONSE_TOO_LARGE
    assert error.attempts == 1
    assert calls == 1
    assert yielded_chunks == 17


def test_compressed_response_is_rejected_without_decompression() -> None:
    config = _config(max_retries=2)
    captured: list[httpx.Request] = []
    compressed = gzip.compress(
        json.dumps(
            {
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            content=compressed,
            headers={"Content-Encoding": "gzip"},
        )

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured_error:
                await provider.test_connection(config)
            return captured_error.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.INVALID_RESPONSE
    assert error.attempts == 1
    assert len(captured) == 1
    assert captured[0].headers["Accept-Encoding"] == "identity"


def test_transport_error_never_exposes_the_authorization_header() -> None:
    config = _config(max_retries=0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"connection failed with {request.headers['Authorization']}",
            request=request,
        )

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())
    serialized_error = f"{error!r} {error} {vars(error)!r}"

    assert error.code is AIProviderErrorCode.TRANSIENT
    assert error.transient_kind.value == "CONNECT"
    assert error.attempts == 1
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET_VALUE not in serialized_error


@pytest.mark.parametrize(
    ("failure_name", "expected_kind"),
    [
        ("http_408", "HTTP_408"),
        ("http_503", "HTTP_5XX"),
        ("dns", "DNS"),
        ("tls", "TLS"),
        ("connect", "CONNECT"),
        ("proxy", "PROXY"),
        ("protocol", "PROTOCOL"),
        ("read", "READ"),
        ("write", "WRITE"),
        ("close", "CLOSE"),
        ("decoding", "DECODING"),
        ("network", "NETWORK"),
        ("unknown", "UNKNOWN"),
    ],
)
def test_transient_failures_preserve_only_closed_safe_categories(
    failure_name: str,
    expected_kind: str,
) -> None:
    config = _config(max_retries=0)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure_name == "http_408":
            return httpx.Response(408, text=f"provider echoed {SECRET_VALUE}")
        if failure_name == "http_503":
            return httpx.Response(503, text=f"provider echoed {SECRET_VALUE}")
        if failure_name == "dns":
            try:
                raise socket.gaierror(-2, SECRET_VALUE)
            except socket.gaierror as cause:
                raise httpx.ConnectError(SECRET_VALUE, request=request) from cause
        if failure_name == "tls":
            try:
                raise ssl.SSLError(1, SECRET_VALUE)
            except ssl.SSLError as cause:
                raise httpx.ConnectError(SECRET_VALUE, request=request) from cause
        error_types = {
            "connect": httpx.ConnectError,
            "proxy": httpx.ProxyError,
            "protocol": httpx.RemoteProtocolError,
            "read": httpx.ReadError,
            "write": httpx.WriteError,
            "close": httpx.CloseError,
            "decoding": httpx.DecodingError,
            "network": httpx.NetworkError,
            "unknown": httpx.RequestError,
        }
        raise error_types[failure_name](SECRET_VALUE, request=request)

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())
    serialized_error = f"{error!r} {error} {vars(error)!r}"

    assert error.code is AIProviderErrorCode.TRANSIENT
    assert error.transient_kind.value == expected_kind
    assert error.attempts == 1
    assert calls == 1
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET_VALUE not in serialized_error


def test_transient_category_reaches_the_content_free_extraction_sidecar(tmp_path: Path) -> None:
    config = _config(max_retries=0, max_input_chars=50_000)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError(SECRET_VALUE, request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            return await extract_plan(
                request_id=REQUEST_ID,
                source_text="华亚智能",
                config=config,
                provider=provider,
            )

    result = asyncio.run(scenario())
    path = tmp_path / "monitor.ai-extraction-diagnostics.jsonl"
    append_extraction_diagnostic(
        path,
        result=result,
        configured_model=config.model,
        completed_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    record = json.loads(path.read_text(encoding="utf-8"))

    assert result.status is PlanExtractionStatus.PROVIDER_ERROR
    assert result.diagnostic is not None
    assert result.diagnostic.provider_error_code == "TRANSIENT"
    assert result.diagnostic.transient_kind == "PROXY"
    assert record["version"] == 3
    assert record["providerErrorCode"] == "TRANSIENT"
    assert record["transientKind"] == "PROXY"
    assert SECRET_VALUE not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("secret_value", [None, "line-one\nline-two", "密钥"])
def test_missing_or_header_unsafe_secret_fails_before_transport(secret_value: str | None) -> None:
    config = _config()
    calls = 0
    store = InMemorySecretStore()
    if secret_value is not None:
        store.replace(config.secret_ref, SecretWrite(value=secret_value))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _completion_response()

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(client=client, secret_store=store)
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.CONFIGURATION
    assert error.attempts == 0
    assert calls == 0
    assert error.__context__ is None
    assert error.__cause__ is None
    if secret_value is not None:
        assert secret_value not in f"{error!r} {vars(error)!r}"


def test_configured_timeout_cancels_a_stalled_transport() -> None:
    config = _config(timeout_seconds=1, max_retries=0)
    transport_cancelled = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            transport_cancelled = True
            raise
        raise AssertionError("unreachable")

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            with pytest.raises(AIProviderError) as captured:
                await asyncio.wait_for(provider.test_connection(config), timeout=2.0)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.TIMEOUT
    assert error.attempts == 1
    assert error.__context__ is None
    assert error.__cause__ is None
    assert transport_cancelled is True


def test_disabled_provider_fails_before_secret_or_transport_access() -> None:
    config = _config(enabled=False)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _completion_response()

    async def scenario() -> AIProviderError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=InMemorySecretStore(),
            )
            with pytest.raises(AIProviderError) as captured:
                await provider.test_connection(config)
            return captured.value

    error = asyncio.run(scenario())

    assert error.code is AIProviderErrorCode.CONFIGURATION
    assert error.attempts == 0
    assert calls == 0


def test_cancellation_during_transport_propagates_without_retry() -> None:
    config = _config(max_retries=2)

    async def scenario() -> int:
        calls = 0
        started = asyncio.Event()
        blocked = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            started.set()
            await blocked.wait()
            return _completion_response()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            task = asyncio.create_task(provider.test_connection(config))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return calls

    assert asyncio.run(scenario()) == 1


def test_cancellation_during_retry_delay_stops_future_attempts() -> None:
    config = _config(max_retries=2)

    async def scenario() -> int:
        calls = 0
        sleep_started = asyncio.Event()
        blocked = asyncio.Event()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        async def sleeper(delay: float) -> None:
            sleep_started.set()
            await blocked.wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                sleep=sleeper,
            )
            task = asyncio.create_task(provider.test_connection(config))
            await sleep_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return calls

    assert asyncio.run(scenario()) == 1


def test_extraction_service_uses_real_adapter_but_returns_only_an_unactivated_draft() -> None:
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.ai.daily_review import daily_source_clauses
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    source_text = "华亚智能交易计划，低吸区 63.00–64.50，按既有白名单条件监控。"
    config = _config(max_input_chars=50_000, max_output_tokens=4_096)
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        raw = unified_payload()
        raw.update(symbol="003043.SZ", market="SZSE")
        draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
        return _completion_response(content=json.dumps({
            "draft": draft.model_dump(mode="json"),
            "clauses": [c.model_dump(mode="json") for c in daily_source_clauses(source_text)],
            "bindings": [],
        }))

    async def scenario() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            return await extract_plan(
                request_id=REQUEST_ID,
                source_text=source_text,
                config=config,
                provider=provider,
            )

    result = asyncio.run(scenario())

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft is not None
    assert result.draft.symbol == "003043.SZ"
    assert result.draft.schema_version == 5
    assert result.draft.to_executable() is not None
    assert any(i.code == "DAILY_SOURCE_BINDING_REQUIRED" for i in result.validation_issues)
    assert all(i.activation_blocking for i in result.validation_issues)
    assert result.daily_mapping.supplements == ()
    assert len(captured) == 1
    request_payload = json.loads(captured[0].content)
    assert "tools" not in request_payload
    assert "UNTRUSTED_PLAN_DATA_START" in request_payload["messages"][0]["content"]
    assert "plan-extract-v10" in request_payload["messages"][0]["content"]


def test_extraction_service_maps_adapter_failure_without_leaking_secret() -> None:
    source_text = "华亚智能交易计划"
    config = _config(max_input_chars=50_000, max_retries=0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"Authorization: Bearer {SECRET_VALUE}")

    async def scenario() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
            )
            return await extract_plan(
                request_id=REQUEST_ID,
                source_text=source_text,
                config=config,
                provider=provider,
            )

    result = asyncio.run(scenario())
    serialized = result.model_dump_json()

    assert result.status is PlanExtractionStatus.PROVIDER_ERROR
    assert result.draft is None
    assert result.validation_issues[0].code == "AI_PROVIDER_ERROR"
    assert SECRET_VALUE not in serialized
    assert "Authorization" not in serialized


def test_ai_concurrency_one_queue_limit_five_and_tushare_thread_isolation() -> None:
    async def scenario() -> tuple[list[int], int, set[str], int, int]:
        controller = AIRequestController()
        release = asyncio.Event()
        first_started = asyncio.Event()
        active = 0
        maximum_active = 0
        thread_names: set[str] = set()

        async def work(value: int) -> int:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            thread_names.add(threading.current_thread().name)
            if value == 0:
                first_started.set()
            await release.wait()
            active -= 1
            return value

        first = asyncio.create_task(controller.execute(lambda: work(0)))
        await first_started.wait()
        queued = [
            asyncio.create_task(controller.execute(lambda value=value: work(value)))
            for value in range(1, 6)
        ]
        for _ in range(1_000):
            if controller.queue_depth == 5:
                break
            await asyncio.sleep(0)
        assert controller.queue_depth == 5

        with pytest.raises(AIQueueFullError):
            await controller.execute(lambda: work(6))

        release.set()
        results = await asyncio.gather(first, *queued)
        return (
            results,
            maximum_active,
            thread_names,
            controller.active_count,
            controller.queue_depth,
        )

    results, maximum_active, thread_names, active_count, queue_depth = asyncio.run(scenario())

    assert results == [0, 1, 2, 3, 4, 5]
    assert maximum_active == 1
    assert all(not name.startswith("trade-plan-tushare") for name in thread_names)
    assert active_count == 0
    assert queue_depth == 0


def test_ai_concurrency_waiter_and_active_cancellation_release_owned_capacity() -> None:
    async def scenario() -> tuple[int, int, str]:
        controller = AIRequestController()
        release = asyncio.Event()
        started = asyncio.Event()

        async def blocked() -> None:
            started.set()
            await release.wait()

        active = asyncio.create_task(controller.execute(blocked))
        await started.wait()
        waiter = asyncio.create_task(controller.execute(blocked))
        for _ in range(1_000):
            if controller.queue_depth == 1:
                break
            await asyncio.sleep(0)
        assert controller.queue_depth == 1

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert controller.queue_depth == 0

        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        result = await controller.execute(lambda: asyncio.sleep(0, result="ready"))
        return controller.active_count, controller.queue_depth, result

    active_count, queue_depth, result = asyncio.run(scenario())

    assert active_count == 0
    assert queue_depth == 0
    assert result == "ready"


def test_ai_retry_admission_does_not_duplicate_provider_owned_retries() -> None:
    config = _config(max_retries=2)

    async def scenario() -> tuple[int, AIProviderError]:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                client=client,
                secret_store=_secret_store(config),
                sleep=lambda _: asyncio.sleep(0),
            )
            controller = AIRequestController()
            with pytest.raises(AIProviderError) as captured:
                await controller.execute(lambda: provider.test_connection(config))
            return calls, captured.value

    calls, error = asyncio.run(scenario())

    assert calls == 3
    assert error.code is AIProviderErrorCode.TRANSIENT
    assert error.attempts == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"max_concurrency": 0},
        {"max_concurrency": 2},
        {"queue_limit": 0},
        {"queue_limit": 6},
    ],
)
def test_ai_concurrency_rejects_values_above_the_approved_bounds(
    changes: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        AIRequestController(**changes)
