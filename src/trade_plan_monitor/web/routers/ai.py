"""Typed non-secret AI-provider configuration and operation adapters."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import AnyHttpUrl, Field, model_validator

from trade_plan_monitor.ai.models import (
    AIProviderConfig,
    AIProviderType,
    SecretReference,
)
from trade_plan_monitor.ai.secrets import SecretSource, SecretWrite
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import (
    ApiValue,
    MutationContext,
    MutationContextDependency,
    OperationKind,
    OperationReceipt,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["ai"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_ROWS = 10_000
_MAX_EXPECTED_REVISION = 9_223_372_036_854_775_806

OffsetQuery = Annotated[int, Query(ge=0, le=_MAX_ROWS)]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
ProviderIdPath = Annotated[UUID, Path()]
NonNegativeRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_EXPECTED_REVISION),
]


class SecretReferenceView(ApiValue):
    key: Annotated[
        str,
        Field(
            strict=True,
            min_length=13,
            max_length=140,
            pattern=r"^ai/provider/[A-Za-z0-9_-]{1,128}$",
        ),
    ]
    environment_variable: (
        Annotated[
            str,
            Field(
                strict=True,
                min_length=1,
                max_length=128,
                pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
            ),
        ]
        | None
    ) = None

    def to_domain(self) -> SecretReference:
        return SecretReference(
            key=self.key,
            environment_variable=self.environment_variable,
        )


class AIProviderConfiguration(ApiValue):
    """Complete non-secret provider settings in camelCase API form."""

    provider_id: UUID = Field(strict=False)
    display_name: Annotated[
        str,
        Field(
            strict=True,
            min_length=1,
            max_length=100,
            pattern=r"^[^\x00-\x1f\x7f]+$",
        ),
    ]
    provider_type: AIProviderType = Field(
        default=AIProviderType.OPENAI_COMPATIBLE,
        strict=False,
    )
    base_url: AnyHttpUrl
    model: Annotated[
        str,
        Field(
            strict=True,
            min_length=1,
            max_length=200,
            pattern=r"^[^\s\x00-\x1f\x7f]+$",
        ),
    ]
    secret_reference: SecretReferenceView
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=120)] = 30
    max_retries: Annotated[int, Field(strict=True, ge=0, le=2)] = 2
    max_input_chars: Annotated[int, Field(strict=True, ge=1, le=200_000)] = 50_000
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=16_384)] = 4_096
    temperature: Annotated[float, Field(strict=True, ge=0, le=0.3)] = 0
    prompt_version: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
    ] = "plan-extract-v2"
    allow_redirects: Literal[False] = False
    enabled: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def validate_domain_configuration(self) -> Self:
        self.to_domain()
        return self

    def to_domain(self) -> AIProviderConfig:
        """Revalidate through the concrete class-local sanitized provider validator."""

        return AIProviderConfig(
            provider_id=self.provider_id,
            display_name=self.display_name,
            provider_type=self.provider_type,
            base_url=self.base_url,
            model=self.model,
            secret_ref=self.secret_reference.to_domain(),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            max_input_chars=self.max_input_chars,
            max_output_tokens=self.max_output_tokens,
            temperature=self.temperature,
            prompt_version=self.prompt_version,
            allow_redirects=self.allow_redirects,
            enabled=self.enabled,
        )


class SecretStatusView(ApiValue):
    configured: bool = Field(strict=True)
    source: SecretSource
    masked_value: Literal["********"] | None
    generation: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def validate_masked_state(self) -> Self:
        expected_configured = self.source is not SecretSource.NONE
        if self.configured != expected_configured:
            raise ValueError("configured and source must describe the same state")
        expected_mask = "********" if self.configured else None
        if self.masked_value != expected_mask:
            raise ValueError("masked_value must reflect configured state")
        if self.source is SecretSource.STORE:
            if self.generation < 1:
                raise ValueError("stored secrets require a positive generation")
        elif self.generation != 0:
            raise ValueError("only stored secrets have a positive generation")
        return self


class AIProviderView(ApiValue):
    config: AIProviderConfiguration
    secret_status: SecretStatusView
    revision: NonNegativeRevision
    created_at: ShanghaiDatetime
    updated_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("provider update cannot precede creation")
        return self


class AIProviderPage(ApiValue):
    items: tuple[AIProviderView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit or (
            self.items and self.offset + len(self.items) > self.total
        ):
            raise ValueError("AI provider page metadata is inconsistent")
        identities = tuple(item.config.provider_id for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("AI provider identities must be unique")
        return self


class ConfiguredAIRuntimeView(ApiValue):
    """Read-only non-secret AI settings loaded for the current Web lifetime."""

    provider_id: UUID = Field(strict=False)
    display_name: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"),
    ]
    base_url: AnyHttpUrl
    model: Annotated[
        str,
        Field(strict=True, min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
    ]
    configured: bool = Field(strict=True)
    enabled: bool = Field(strict=True)
    max_input_chars: Annotated[int, Field(strict=True, ge=1, le=200_000)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=16_384)]
    revision: Literal[0] = 0


class AIProviderConfigurationCommand(ApiValue):
    config: AIProviderConfiguration
    expected_revision: NonNegativeRevision


class AIProviderSecretCommand(ApiValue):
    provider_id: UUID = Field(strict=False)
    secret: SecretWrite
    expected_revision: NonNegativeRevision


class AIProviderTestCommand(ApiValue):
    provider_id: UUID = Field(strict=False)
    expected_revision: NonNegativeRevision


class AIOperationService(Protocol):
    """Application service owning provider persistence, audit, and queued operations."""

    async def list_ai_providers(self, *, offset: int, limit: int) -> AIProviderPage: ...

    async def get_configured_ai(self) -> ConfiguredAIRuntimeView: ...

    async def create_ai_provider(
        self,
        *,
        command: AIProviderConfigurationCommand,
        context: MutationContext,
    ) -> AIProviderView: ...

    async def update_ai_provider(
        self,
        *,
        provider_id: str,
        command: AIProviderConfigurationCommand,
        context: MutationContext,
    ) -> AIProviderView | None: ...

    async def replace_ai_provider_secret(
        self,
        *,
        command: AIProviderSecretCommand,
        context: MutationContext,
    ) -> AIProviderView: ...

    async def submit_ai_provider_test(
        self,
        *,
        command: AIProviderTestCommand,
        context: MutationContext,
    ) -> OperationReceipt: ...


def get_ai_operation_service(request: Request) -> AIOperationService:
    service = getattr(request.app.state, "ai_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(AIOperationService, service)


AIServiceDependency = Annotated[
    AIOperationService,
    Depends(get_ai_operation_service),
]


@router.get("/ai-runtime", response_model=ConfiguredAIRuntimeView)
async def get_configured_ai(service: AIServiceDependency) -> ConfiguredAIRuntimeView:
    return validate_api_response(
        await service.get_configured_ai(),
        ConfiguredAIRuntimeView,
    )


@router.get("/ai-providers", response_model=AIProviderPage)
async def list_ai_providers(
    service: AIServiceDependency,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> AIProviderPage:
    page = validate_api_response(
        await service.list_ai_providers(offset=offset, limit=limit),
        AIProviderPage,
    )
    if page.offset != offset or page.limit != limit:
        raise RuntimeError("AI provider service returned mismatched pagination")
    return page


@router.post("/ai-providers", response_model=AIProviderView)
async def create_ai_provider(
    command: AIProviderConfigurationCommand,
    context: MutationContextDependency,
    service: AIServiceDependency,
) -> AIProviderView:
    if command.expected_revision != 0:
        raise ApiError(ApiErrorCode.CONFLICT)
    result = validate_api_response(
        await service.create_ai_provider(command=command, context=context),
        AIProviderView,
    )
    _ensure_configuration_matches(result, command.config)
    if result.revision != 0:
        raise RuntimeError("AI provider create returned an invalid initial revision")
    return result


@router.patch("/ai-providers/{provider_id}", response_model=AIProviderView)
async def update_ai_provider(
    provider_id: ProviderIdPath,
    command: AIProviderConfigurationCommand,
    context: MutationContextDependency,
    service: AIServiceDependency,
) -> AIProviderView:
    if command.config.provider_id != provider_id:
        raise ApiError(ApiErrorCode.BAD_REQUEST)
    value = await service.update_ai_provider(
        provider_id=str(provider_id),
        command=command,
        context=context,
    )
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    result = validate_api_response(value, AIProviderView)
    _ensure_configuration_matches(result, command.config)
    if result.revision != command.expected_revision + 1:
        raise RuntimeError("AI provider update returned a stale revision")
    return result


@router.post("/ai-provider-secrets", response_model=AIProviderView)
async def replace_ai_provider_secret(
    command: AIProviderSecretCommand,
    context: MutationContextDependency,
    service: AIServiceDependency,
) -> AIProviderView:
    result = validate_api_response(
        await service.replace_ai_provider_secret(command=command, context=context),
        AIProviderView,
    )
    if result.config.provider_id != command.provider_id:
        raise RuntimeError("secret service returned a mismatched provider")
    if result.revision != command.expected_revision + 1:
        raise RuntimeError("secret service returned a stale revision")
    if not result.secret_status.configured or result.secret_status.source is not SecretSource.STORE:
        raise RuntimeError("secret service did not confirm stored replacement")
    return result


@router.post(
    "/ai-provider-tests",
    response_model=OperationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_ai_provider_test(
    command: AIProviderTestCommand,
    context: MutationContextDependency,
    service: AIServiceDependency,
) -> OperationReceipt:
    receipt = validate_api_response(
        await service.submit_ai_provider_test(command=command, context=context),
        OperationReceipt,
    )
    if receipt.kind is not OperationKind.AI_PROVIDER_TEST:
        raise RuntimeError("AI provider service returned a mismatched operation kind")
    return receipt


def _ensure_configuration_matches(
    result: AIProviderView,
    requested: AIProviderConfiguration,
) -> None:
    if result.config.to_domain() != requested.to_domain():
        raise RuntimeError("AI provider service returned a mismatched configuration")


__all__ = [
    "AIOperationService",
    "AIProviderConfigurationCommand",
    "ConfiguredAIRuntimeView",
    "AIProviderPage",
    "AIProviderSecretCommand",
    "AIProviderTestCommand",
    "AIProviderView",
    "router",
]
