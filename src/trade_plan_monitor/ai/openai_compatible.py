"""Resource-bounded OpenAI-compatible Chat Completions adapter.

The HTTP shape and streaming behavior follow the current official contracts:
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
https://api-docs.deepseek.com/api/create-chat-completion/
https://api-docs.deepseek.com/guides/json_mode/
https://www.python-httpx.org/async/#streaming-responses
https://www.python-httpx.org/advanced/timeouts/
https://docs.python.org/3/library/asyncio-task.html#timeouts
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from collections.abc import Awaitable, Callable
from math import isfinite
from time import monotonic_ns
from typing import Annotated, Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, ValidationError

from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderProfile,
    SecretReference,
)
from trade_plan_monitor.ai.provider import (
    AIProviderError,
    AIProviderErrorCode,
    AIProviderOperation,
    AIProviderTimeoutKind,
    AIProviderTransientKind,
    AIUsage,
    PlanExtractionRequest,
    ProviderTestResult,
    RawAIResponse,
)

_MAX_RESPONSE_BYTES = 1_048_576
_STREAM_CHUNK_BYTES = 65_536
_CONNECTION_TEST_PROMPT = "Reply with OK."
_RETRY_BASE_SECONDS = 0.25
_MAX_RETRY_DELAY_SECONDS = 2.0

_ResponseModelName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
_ResponseContent = Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]
_FinishReason = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class _SecretMaterializer(Protocol):
    def _materialize(self, reference: SecretReference) -> SecretStr: ...


_Sleep = Callable[[float], Awaitable[None]]


class _AttemptFailure(Exception):
    def __init__(
        self,
        code: AIProviderErrorCode,
        *,
        retryable: bool,
        retry_after: float | None = None,
        transient_kind: AIProviderTransientKind | None = None,
        timeout_kind: AIProviderTimeoutKind | None = None,
        timeout_elapsed_ms: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.transient_kind = transient_kind
        self.timeout_kind = timeout_kind
        self.timeout_elapsed_ms = timeout_elapsed_ms
        super().__init__(code.value)


class _ProviderEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class _AssistantMessage(_ProviderEnvelope):
    role: Literal["assistant"]
    content: _ResponseContent
    tool_calls: list[object] | None = None


class _CompletionChoice(_ProviderEnvelope):
    index: Literal[0]
    message: _AssistantMessage
    finish_reason: _FinishReason


class _ProviderUsage(_ProviderEnvelope):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class _CompletionEnvelope(_ProviderEnvelope):
    model: _ResponseModelName
    choices: list[_CompletionChoice] = Field(min_length=1, max_length=1)
    usage: _ProviderUsage | None = None


class OpenAICompatibleProvider:
    """Explicit HTTP adapter returning raw model text without executing it."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        secret_store: _SecretMaterializer,
        profile: AIProviderProfile = AIProviderProfile.OPENAI_COMPATIBLE,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        if not isinstance(profile, AIProviderProfile):
            raise TypeError("profile must be an AIProviderProfile")
        self._client = client
        self._secret_store = secret_store
        self._profile = profile
        self._sleep = sleep

    async def test_connection(self, config: AIProviderConfig) -> ProviderTestResult:
        envelope, attempts = await self._complete(
            config=config,
            prompt=_CONNECTION_TEST_PROMPT,
            max_completion_tokens=1,
            operation=AIProviderOperation.TEST_CONNECTION,
        )
        return ProviderTestResult(
            provider_id=config.provider_id,
            model=envelope.model,
            connected=True,
            attempts=attempts,
        )

    async def extract_plan(self, request: PlanExtractionRequest) -> RawAIResponse:
        envelope, attempts = await self._complete(
            config=request.config,
            prompt=request.prompt,
            max_completion_tokens=request.config.max_output_tokens,
            operation=AIProviderOperation.EXTRACT_PLAN,
        )
        choice = envelope.choices[0]
        return RawAIResponse(
            request_id=request.request_id,
            provider_id=request.config.provider_id,
            model=envelope.model,
            content=choice.message.content,
            finish_reason=choice.finish_reason,
            usage=_public_usage(envelope.usage),
            attempts=attempts,
        )

    async def _complete(
        self,
        *,
        config: AIProviderConfig,
        prompt: str,
        max_completion_tokens: int,
        operation: AIProviderOperation,
    ) -> tuple[_CompletionEnvelope, int]:
        if not config.enabled:
            raise AIProviderError(
                AIProviderErrorCode.CONFIGURATION,
                operation,
                attempts=0,
            )
        headers = self._authorization_headers(config, operation)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.temperature,
            "stream": False,
        }
        if self._profile is AIProviderProfile.DEEPSEEK:
            payload["max_tokens"] = max_completion_tokens
            payload["thinking"] = {"type": "disabled"}
            if operation is AIProviderOperation.EXTRACT_PLAN:
                payload["response_format"] = {"type": "json_object"}
        else:
            payload["max_completion_tokens"] = max_completion_tokens
        max_attempts = config.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            failure: _AttemptFailure | None = None
            attempt_started_ns = monotonic_ns()
            try:
                content = await self._request_once(
                    config=config,
                    headers=headers,
                    payload=payload,
                )
            except _AttemptFailure as caught:
                failure = _AttemptFailure(
                    caught.code,
                    retryable=caught.retryable,
                    retry_after=caught.retry_after,
                    transient_kind=caught.transient_kind,
                    timeout_kind=caught.timeout_kind,
                    timeout_elapsed_ms=caught.timeout_elapsed_ms,
                )
            except httpx.ConnectTimeout:
                failure = _timeout_failure(AIProviderTimeoutKind.CONNECT, attempt_started_ns)
            except httpx.ReadTimeout:
                failure = _timeout_failure(AIProviderTimeoutKind.READ, attempt_started_ns)
            except httpx.WriteTimeout:
                failure = _timeout_failure(AIProviderTimeoutKind.WRITE, attempt_started_ns)
            except httpx.PoolTimeout:
                failure = _timeout_failure(AIProviderTimeoutKind.POOL, attempt_started_ns)
            except TimeoutError:
                failure = _timeout_failure(
                    AIProviderTimeoutKind.OVERALL_DEADLINE,
                    attempt_started_ns,
                )
            except httpx.TimeoutException:
                failure = _timeout_failure(AIProviderTimeoutKind.UNKNOWN, attempt_started_ns)
            except httpx.RequestError as error:
                failure = _AttemptFailure(
                    AIProviderErrorCode.TRANSIENT,
                    retryable=True,
                    transient_kind=_classify_request_error(error),
                )

            if failure is not None:
                if not failure.retryable or attempt == max_attempts:
                    raise AIProviderError(
                        failure.code,
                        operation,
                        attempts=attempt,
                        transient_kind=failure.transient_kind,
                        timeout_kind=failure.timeout_kind,
                        timeout_elapsed_ms=failure.timeout_elapsed_ms,
                    ) from None
                await self._sleep(_retry_delay(attempt, failure.retry_after))
                continue

            envelope: _CompletionEnvelope | None = None
            try:
                envelope = _CompletionEnvelope.model_validate_json(content, strict=True)
            except ValidationError:
                pass
            if envelope is None:
                raise AIProviderError(
                    AIProviderErrorCode.INVALID_RESPONSE,
                    operation,
                    attempts=attempt,
                ) from None
            choice = envelope.choices[0]
            if choice.message.tool_calls or choice.finish_reason == "tool_calls":
                raise AIProviderError(
                    AIProviderErrorCode.INVALID_RESPONSE,
                    operation,
                    attempts=attempt,
                )
            return envelope, attempt
        raise AssertionError("bounded provider attempt loop exhausted without a result")

    async def _request_once(
        self,
        *,
        config: AIProviderConfig,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> bytes:
        async with asyncio.timeout(config.timeout_seconds):
            async with self._client.stream(
                "POST",
                _completion_url(config),
                headers=headers,
                json=payload,
                timeout=_transport_timeout(config),
                follow_redirects=False,
            ) as response:
                failure = _classify_http_failure(response)
                if failure is not None:
                    raise failure
                return await _read_limited_response(response)

    def _authorization_headers(
        self,
        config: AIProviderConfig,
        operation: AIProviderOperation,
    ) -> dict[str, str]:
        secret: str | None = None
        try:
            secret = self._secret_store._materialize(config.secret_ref).get_secret_value()
        except Exception:
            pass
        if secret is None:
            raise AIProviderError(
                AIProviderErrorCode.CONFIGURATION,
                operation,
                attempts=0,
            ) from None
        if any(not 0x20 <= ord(character) <= 0x7E for character in secret):
            raise AIProviderError(
                AIProviderErrorCode.CONFIGURATION,
                operation,
                attempts=0,
            )
        return {
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }


async def _read_limited_response(
    response: httpx.Response,
) -> bytes:
    content_encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    if content_encoding not in ("", "identity"):
        raise _AttemptFailure(
            AIProviderErrorCode.INVALID_RESPONSE,
            retryable=False,
        )

    declared_length = response.headers.get("Content-Length")
    if declared_length is not None:
        try:
            if int(declared_length) > _MAX_RESPONSE_BYTES:
                raise _AttemptFailure(
                    AIProviderErrorCode.RESPONSE_TOO_LARGE,
                    retryable=False,
                )
        except ValueError:
            pass

    if response.is_stream_consumed:
        content = response.content
        if len(content) > _MAX_RESPONSE_BYTES:
            raise _AttemptFailure(
                AIProviderErrorCode.RESPONSE_TOO_LARGE,
                retryable=False,
            )
        return content

    chunks: list[bytes] = []
    consumed = 0
    async for chunk in response.aiter_raw(chunk_size=_STREAM_CHUNK_BYTES):
        consumed += len(chunk)
        if consumed > _MAX_RESPONSE_BYTES:
            raise _AttemptFailure(
                AIProviderErrorCode.RESPONSE_TOO_LARGE,
                retryable=False,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _public_usage(usage: _ProviderUsage | None) -> AIUsage | None:
    if usage is None:
        return None
    return AIUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _completion_url(config: AIProviderConfig) -> str:
    return f"{str(config.base_url).rstrip('/')}/chat/completions"


def _transport_timeout(config: AIProviderConfig) -> httpx.Timeout:
    phase_timeout = config.transport_timeout_seconds or config.timeout_seconds
    read_timeout = config.read_timeout_seconds or phase_timeout
    return httpx.Timeout(
        connect=phase_timeout,
        read=read_timeout,
        write=phase_timeout,
        pool=phase_timeout,
    )


def _classify_http_failure(response: httpx.Response) -> _AttemptFailure | None:
    status_code = response.status_code
    if status_code == 200:
        return None
    if 300 <= status_code < 400:
        return _AttemptFailure(AIProviderErrorCode.UNSAFE_REDIRECT, retryable=False)
    if status_code in (401, 403):
        return _AttemptFailure(AIProviderErrorCode.AUTHENTICATION, retryable=False)
    if status_code == 429:
        return _AttemptFailure(
            AIProviderErrorCode.RATE_LIMITED,
            retryable=True,
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )
    if status_code == 408:
        return _AttemptFailure(
            AIProviderErrorCode.TRANSIENT,
            retryable=True,
            transient_kind=AIProviderTransientKind.HTTP_408,
        )
    if 500 <= status_code < 600:
        return _AttemptFailure(
            AIProviderErrorCode.TRANSIENT,
            retryable=True,
            transient_kind=AIProviderTransientKind.HTTP_5XX,
        )
    return _AttemptFailure(AIProviderErrorCode.REJECTED, retryable=False)


def _classify_request_error(error: httpx.RequestError) -> AIProviderTransientKind:
    if isinstance(error, httpx.ProxyError):
        return AIProviderTransientKind.PROXY
    if isinstance(error, httpx.ConnectError):
        if _cause_chain_contains(error, ssl.SSLError):
            return AIProviderTransientKind.TLS
        if _cause_chain_contains(error, socket.gaierror):
            return AIProviderTransientKind.DNS
        return AIProviderTransientKind.CONNECT
    if isinstance(error, httpx.ProtocolError | httpx.UnsupportedProtocol):
        return AIProviderTransientKind.PROTOCOL
    if isinstance(error, httpx.ReadError):
        return AIProviderTransientKind.READ
    if isinstance(error, httpx.WriteError):
        return AIProviderTransientKind.WRITE
    if isinstance(error, httpx.CloseError):
        return AIProviderTransientKind.CLOSE
    if isinstance(error, httpx.DecodingError):
        return AIProviderTransientKind.DECODING
    if isinstance(error, httpx.NetworkError):
        return AIProviderTransientKind.NETWORK
    return AIProviderTransientKind.UNKNOWN


def _cause_chain_contains(error: BaseException, kind: type[BaseException]) -> bool:
    current = error.__cause__
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        if isinstance(current, kind):
            return True
        seen.add(id(current))
        current = current.__cause__
    return False


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        return None
    if not isfinite(delay) or delay < 0:
        return None
    return min(delay, _MAX_RETRY_DELAY_SECONDS)


def _retry_delay(attempt: int, retry_after: float | None) -> float:
    exponential = min(
        _RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
        _MAX_RETRY_DELAY_SECONDS,
    )
    if retry_after is None:
        return exponential
    return min(max(exponential, retry_after), _MAX_RETRY_DELAY_SECONDS)


def _timeout_failure(
    kind: AIProviderTimeoutKind,
    attempt_started_ns: int,
) -> _AttemptFailure:
    elapsed_ms = max(0, (monotonic_ns() - attempt_started_ns) // 1_000_000)
    return _AttemptFailure(
        AIProviderErrorCode.TIMEOUT,
        retryable=True,
        timeout_kind=kind,
        timeout_elapsed_ms=elapsed_ms,
    )


__all__ = ["OpenAICompatibleProvider"]
