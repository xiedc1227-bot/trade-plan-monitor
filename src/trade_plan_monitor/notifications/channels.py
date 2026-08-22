"""Bounded notification-channel adapters for committed alert events."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

import httpx
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from trade_plan_monitor.notifications.models import AlertEvent

WebhookHost = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=253),
]
ConsoleWriter = Callable[[str], None]


class DeliveryChannel(StrEnum):
    """Closed channel vocabulary persisted with each delivery attempt."""

    IN_APP = "IN_APP"
    CONSOLE = "CONSOLE"
    WEBHOOK = "WEBHOOK"


class ChannelErrorCode(StrEnum):
    """Stable redacted channel outcomes suitable for durable health state."""

    WEBHOOK_DISABLED = "WEBHOOK_DISABLED"
    CONSOLE_WRITE_FAILED = "CONSOLE_WRITE_FAILED"
    WEBHOOK_TIMEOUT = "WEBHOOK_TIMEOUT"
    WEBHOOK_TRANSPORT = "WEBHOOK_TRANSPORT"
    UNSAFE_REDIRECT = "UNSAFE_REDIRECT"
    WEBHOOK_REJECTED = "WEBHOOK_REJECTED"
    WEBHOOK_TRANSIENT = "WEBHOOK_TRANSIENT"
    CHANNEL_FAILURE = "CHANNEL_FAILURE"


class ChannelDeliveryResult(BaseModel):
    """One secret-free result returned by a channel adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    channel: DeliveryChannel
    delivered: bool = Field(strict=True)
    retryable: bool = Field(strict=True)
    response_code: int | None = Field(default=None, strict=True, ge=100, le=599)
    error_code: ChannelErrorCode | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.delivered:
            if self.retryable or self.error_code is not None:
                raise ValueError("a delivered channel result cannot be an error")
        elif self.error_code is None:
            raise ValueError("a failed channel result requires an error code")
        return self


class NotificationChannel(Protocol):
    """Minimal asynchronous adapter contract consumed by the dispatcher."""

    channel: DeliveryChannel
    enabled: bool

    async def deliver(self, event: AlertEvent) -> ChannelDeliveryResult: ...


class WebhookConfig(BaseModel):
    """Disabled-by-default configuration for one generic HTTPS webhook."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
        strict=True,
    )

    enabled: bool = False
    endpoint: AnyHttpUrl | None = None
    allowlisted_hosts: tuple[WebhookHost, ...] = Field(default=(), max_length=64)
    timeout_seconds: int = Field(default=5, strict=True, ge=1, le=30)
    allow_redirects: Literal[False] = False

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy configuration without bypassing its network-security invariants."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
        info: ValidationInfo,
    ) -> Self:
        if info.mode == "json" and isinstance(value, Mapping):
            json_hosts = value.get("allowlisted_hosts")
            if isinstance(json_hosts, list):
                value = {**value, "allowlisted_hosts": tuple(json_hosts)}
        safe_error: ValidationError | None = None
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = _validation_error_without_inputs(error)
        if safe_error is not None:
            raise safe_error
        raise AssertionError("validation boundary completed without a result")

    @field_validator("endpoint")
    @classmethod
    def require_safe_endpoint(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return None
        if len(str(value)) > 2_048:
            raise ValueError("webhook endpoint must not exceed 2048 characters")
        if value.scheme != "https":
            raise ValueError("webhook endpoint must use HTTPS")
        if value.username is not None or value.password is not None:
            raise ValueError("webhook endpoint must not contain embedded credentials")
        if value.query is not None or value.fragment is not None:
            raise ValueError("webhook endpoint must not contain a query or fragment")
        return value

    @field_validator("allowlisted_hosts")
    @classmethod
    def normalize_allowlisted_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for host in value:
            canonical = host.casefold()
            if host != host.strip() or "*" in host or "/" in host or "@" in host or "://" in host:
                raise ValueError("webhook allowlisted hosts must be exact host names")
            normalized.append(canonical)
        if len(set(normalized)) != len(normalized):
            raise ValueError("webhook allowlisted hosts must be unique")
        return tuple(normalized)

    @model_validator(mode="after")
    def require_enabled_endpoint_in_allowlist(self) -> Self:
        if not self.enabled:
            return self
        if self.endpoint is None:
            raise ValueError("enabled webhook requires an endpoint")
        host = self.endpoint.host
        if host is None or host.casefold() not in self.allowlisted_hosts:
            raise ValueError("webhook endpoint host must be explicitly allowlisted")
        return self


class InAppChannel:
    """Mark a committed outbox event as available to the mandatory local app."""

    channel = DeliveryChannel.IN_APP
    enabled = True

    async def deliver(self, event: AlertEvent) -> ChannelDeliveryResult:
        _require_event(event)
        return _delivered(self.channel)


class ConsoleChannel:
    """Write the deterministic alert and stable event identity to a local sink."""

    channel = DeliveryChannel.CONSOLE
    enabled = True

    def __init__(self, *, write_line: ConsoleWriter = print) -> None:
        if not callable(write_line):
            raise TypeError("write_line must be callable")
        self._write_line = write_line

    async def deliver(self, event: AlertEvent) -> ChannelDeliveryResult:
        _require_event(event)
        line = f"[alert event_id={event.event_id} sequence={event.sequence}] {event.message_text}"
        try:
            self._write_line(line)
        except Exception:
            return _failed(
                self.channel,
                ChannelErrorCode.CONSOLE_WRITE_FAILED,
                retryable=True,
            )
        return _delivered(self.channel)


class WebhookChannel:
    """Send a bounded public alert envelope through one generic webhook."""

    channel = DeliveryChannel.WEBHOOK

    def __init__(self, *, client: httpx.AsyncClient, config: WebhookConfig) -> None:
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client must be an httpx.AsyncClient")
        if type(config) is not WebhookConfig:
            raise TypeError("config must be a WebhookConfig")
        self._client = client
        self._config = WebhookConfig.model_validate(config)

    @property
    def enabled(self) -> bool:
        """Expose the validated immutable enablement state as read-only."""

        return self._config.enabled

    async def deliver(self, event: AlertEvent) -> ChannelDeliveryResult:
        _require_event(event)
        if not self._config.enabled or self._config.endpoint is None:
            return _failed(
                self.channel,
                ChannelErrorCode.WEBHOOK_DISABLED,
                retryable=False,
            )

        try:
            async with asyncio.timeout(self._config.timeout_seconds):
                async with self._client.stream(
                    "POST",
                    str(self._config.endpoint),
                    headers={"Accept-Encoding": "identity"},
                    json=_webhook_payload(event),
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                    follow_redirects=False,
                ) as response:
                    return _http_result(response.status_code)
        except TimeoutError, httpx.TimeoutException:
            return _failed(
                self.channel,
                ChannelErrorCode.WEBHOOK_TIMEOUT,
                retryable=True,
            )
        except httpx.RequestError:
            return _failed(
                self.channel,
                ChannelErrorCode.WEBHOOK_TRANSPORT,
                retryable=True,
            )
        except Exception:
            return _failed(
                self.channel,
                ChannelErrorCode.WEBHOOK_TRANSPORT,
                retryable=True,
            )

    async def aclose(self) -> None:
        """Close the injected client when this channel owns its lifecycle."""

        await self._client.aclose()


def _webhook_payload(event: AlertEvent) -> dict[str, object]:
    return {
        "createdAt": event.created_at.isoformat(),
        "eventId": str(event.event_id),
        "messageText": event.message_text,
        "sequence": event.sequence,
        "severity": event.severity.value,
        "signalType": event.signal_type.value,
        "symbol": event.symbol,
    }


def _http_result(status_code: int) -> ChannelDeliveryResult:
    if 200 <= status_code < 300:
        return _delivered(DeliveryChannel.WEBHOOK, response_code=status_code)
    if 300 <= status_code < 400:
        return _failed(
            DeliveryChannel.WEBHOOK,
            ChannelErrorCode.UNSAFE_REDIRECT,
            retryable=False,
            response_code=status_code,
        )
    if status_code in (408, 429) or 500 <= status_code < 600:
        return _failed(
            DeliveryChannel.WEBHOOK,
            ChannelErrorCode.WEBHOOK_TRANSIENT,
            retryable=True,
            response_code=status_code,
        )
    return _failed(
        DeliveryChannel.WEBHOOK,
        ChannelErrorCode.WEBHOOK_REJECTED,
        retryable=False,
        response_code=status_code,
    )


def _delivered(
    channel: DeliveryChannel,
    *,
    response_code: int | None = None,
) -> ChannelDeliveryResult:
    return ChannelDeliveryResult(
        channel=channel,
        delivered=True,
        retryable=False,
        response_code=response_code,
        error_code=None,
    )


def _failed(
    channel: DeliveryChannel,
    error_code: ChannelErrorCode,
    *,
    retryable: bool,
    response_code: int | None = None,
) -> ChannelDeliveryResult:
    return ChannelDeliveryResult(
        channel=channel,
        delivered=False,
        retryable=retryable,
        response_code=response_code,
        error_code=error_code,
    )


def _require_event(event: AlertEvent) -> None:
    if type(event) is not AlertEvent:
        raise TypeError("event must be an AlertEvent")


def _validation_error_without_inputs(error: ValidationError) -> ValidationError:
    line_errors = error.errors(include_url=False)
    for line_error in line_errors:
        line_error.pop("input", None)
    return ValidationError.from_exception_data(
        error.title,
        line_errors,
        hide_input=True,
    )


__all__ = [
    "ChannelDeliveryResult",
    "ChannelErrorCode",
    "ConsoleChannel",
    "DeliveryChannel",
    "InAppChannel",
    "NotificationChannel",
    "WebhookChannel",
    "WebhookConfig",
]
