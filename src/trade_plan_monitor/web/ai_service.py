"""Read-only Web composition for configured AI models in application configuration."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import BoundedSemaphore
from typing import Final, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx

from trade_plan_monitor.ai.composition import (
    ConfiguredAIProviderBinding,
    compose_configured_ai_providers,
)
from trade_plan_monitor.ai.configured_secrets import create_configured_secret_store
from trade_plan_monitor.ai.extraction import extract_plan
from trade_plan_monitor.ai.loop_plan_extraction import extract_loop_plan
from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    PlanExtractionResult,
    PlanExtractionStatus,
)
from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateContext, extract_plan_update
from trade_plan_monitor.ai.review import dump_explicit_plan_draft_json
from trade_plan_monitor.ai.secrets import InMemorySecretStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor
from trade_plan_monitor.config import AIConfiguration, load_application_config
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.web.ai_diagnostics import (
    append_extraction_diagnostic,
    ensure_diagnostic_sink,
)
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.ai import (
    AIProviderConfiguration,
    AIProviderPage,
    AIProviderView,
    ConfiguredAIProviderRuntimeView,
    ConfiguredAIRuntimeView,
    SecretReferenceView,
    SecretStatusView,
)
from trade_plan_monitor.web.routers.plans import (
    AIUsageView,
    PlanExtractionCommand,
    PlanExtractionOperationStatus,
    PlanExtractionView,
    PlanMappingView,
)
from trade_plan_monitor.web.schemas import (
    MutationContext,
    OperationKind,
    OperationReceipt,
)

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_MAX_RETAINED_OPERATIONS: Final = 1_000
_MAX_CONCURRENT_EXTRACTIONS: Final = 1

AIClientFactory = Callable[[], httpx.AsyncClient]


class PlanExtractionReviewStore(Protocol):
    async def record_plan_extraction(self, result: PlanExtractionResult) -> None: ...


class ConfiguredAIWebLifecycle:
    """Own immutable directly configured AI model bindings for a Web lifetime."""

    def __init__(
        self,
        *,
        config_path: Path,
        client_factory: AIClientFactory | None = None,
        review_store: PlanExtractionReviewStore | None = None,
        diagnostic_path: Path | None = None,
    ) -> None:
        if not isinstance(config_path, Path):
            raise TypeError("config_path must be a Path")
        self._config_path = config_path
        self._client_factory = client_factory or _default_client
        self._review_store = review_store
        self._diagnostic_path = diagnostic_path
        self._diagnostic_sink_available: bool | None = None
        self._client: httpx.AsyncClient | None = None
        self._settings: AIConfiguration | None = None
        self._secret_store: InMemorySecretStore | None = None
        self._binding: ConfiguredAIProviderBinding | None = None
        self._bindings: dict[UUID, ConfiguredAIProviderBinding] = {}
        self._configured_at: datetime | None = None
        self._operations: dict[UUID, PlanExtractionView] = {}
        self._receipts: dict[str, tuple[str, OperationReceipt]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._extraction_slots = BoundedSemaphore(_MAX_CONCURRENT_EXTRACTIONS)

    @property
    def ai_operation_service(self) -> ConfiguredAIWebLifecycle:
        return self

    @property
    def plan_extraction_service(self) -> ConfiguredAIWebLifecycle:
        return self

    async def start(self) -> dict[str, object]:
        """Read configuration once and create the provider client before serving requests."""

        if self._client is not None:
            raise RuntimeError("configured AI Web lifecycle is already started")
        settings = load_application_config(self._config_path).ai
        if self._diagnostic_path is not None:
            try:
                await asyncio.to_thread(ensure_diagnostic_sink, self._diagnostic_path)
            except OSError:
                self._diagnostic_sink_available = False
            else:
                self._diagnostic_sink_available = True
        client = self._client_factory()
        if not isinstance(client, httpx.AsyncClient):
            raise TypeError("client_factory must return an httpx.AsyncClient")
        secret_store = create_configured_secret_store(settings=settings)
        self._settings = settings
        self._client = client
        self._secret_store = secret_store
        bindings = compose_configured_ai_providers(
            settings=settings,
            client=client,
            secret_store=secret_store,
        )
        self._binding = bindings[0] if bindings else None
        self._bindings = {binding.config.provider_id: binding for binding in bindings}
        self._configured_at = _now()
        return {
            "configured": self._binding is not None,
            "providerCount": len(self._bindings),
            "diagnosticAvailable": self._diagnostic_sink_available,
        }

    async def stop(self) -> None:
        """Cancel unfinished extraction work and release the provider HTTP client."""

        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        client = self._client
        self._client = None
        self._settings = None
        self._secret_store = None
        self._binding = None
        self._bindings = {}
        self._configured_at = None
        self._diagnostic_sink_available = None
        if client is not None:
            await client.aclose()

    async def list_ai_providers(self, *, offset: int, limit: int) -> AIProviderPage:
        items = tuple(self._provider_view(binding) for binding in self._bindings.values())
        return AIProviderPage(
            items=items[offset : offset + limit],
            offset=offset,
            limit=limit,
            total=len(items),
        )

    async def get_configured_ai(self) -> ConfiguredAIRuntimeView:
        binding = self._require_binding()
        secret_store = self._secret_store
        if secret_store is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        config = binding.config
        alternatives = tuple(
            self._runtime_provider_view(alternative)
            for alternative in self._bindings.values()
            if alternative.config.provider_id != config.provider_id
        )
        return ConfiguredAIRuntimeView(
            provider_id=config.provider_id,
            display_name=config.display_name,
            base_url=config.base_url,
            model=config.model,
            configured=secret_store.status(config.secret_ref).configured,
            enabled=config.enabled,
            max_input_chars=config.max_input_chars,
            max_output_tokens=config.max_output_tokens,
            revision=0,
            alternative_providers=alternatives or None,
        )

    async def submit_plan_extraction(
        self,
        *,
        command: PlanExtractionCommand,
        context: MutationContext,
    ) -> OperationReceipt:
        binding = self._require_binding(command.provider_id)
        if command.expected_revision != 0:
            raise ApiError(ApiErrorCode.CONFLICT)
        request_hash = _extraction_request_hash(command)
        replay = self._receipts.get(context.idempotency_key)
        if replay is not None:
            previous_hash, previous_receipt = replay
            if previous_hash != request_hash:
                raise ApiError(ApiErrorCode.CONFLICT)
            return previous_receipt
        if len(self._operations) >= _MAX_RETAINED_OPERATIONS:
            raise ApiError(ApiErrorCode.RATE_LIMITED, retry_after_seconds=60)

        operation_id = uuid4()
        submitted_at = _now()
        receipt = OperationReceipt(
            operation_id=operation_id,
            kind=OperationKind.PLAN_EXTRACTION,
            status="QUEUED",
            submitted_at=submitted_at,
        )
        self._operations[operation_id] = PlanExtractionView(
            id=operation_id,
            provider_id=binding.config.provider_id,
            status=PlanExtractionOperationStatus.QUEUED,
            submitted_at=submitted_at,
        )
        self._receipts[context.idempotency_key] = (request_hash, receipt)
        task = asyncio.create_task(
            self._run_extraction(
                operation_id=operation_id,
                source_text=command.source_text,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return receipt

    async def get_plan_extraction(self, *, operation_id: str) -> PlanExtractionView | None:
        try:
            identity = UUID(operation_id)
        except ValueError:
            return None
        return self._operations.get(identity)

    def backtest_extractor(self, provider_id: UUID | None = None) -> PreparationExtractor:
        """Capture immutable settings; each owned call creates and closes its own transport."""
        binding = self._require_binding(provider_id)
        secret_store = self._secret_store
        factory = self._client_factory
        slots = self._extraction_slots
        config = binding.config.model_copy(update={"max_retries": 0,
            "max_output_tokens": self._settings.backtest_max_output_tokens,
            "timeout_seconds": self._settings.backtest_timeout_seconds})

        def call(
            identity, source, token, *, context: PlanUpdateContext | None = None,
            feedback=(), repair_context=None,
        ):
            while not slots.acquire(timeout=0.05):
                if token.cancelled:
                    return None
            try:
                if token.cancelled:
                    return None
                if self._client is None or self._secret_store is not secret_store:
                    raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)

                async def extract():
                    client = factory()
                    if not isinstance(client, httpx.AsyncClient):
                        raise TypeError("client_factory must return an httpx.AsyncClient")
                    async with client:
                        provider = OpenAICompatibleProvider(
                            client=client, secret_store=secret_store, profile=binding.profile,
                        )
                        if context is not None:
                            return await extract_plan_update(
                                request_id=identity, source=source, context=context,
                                config=config, provider=provider, compact=True,
                                feedback=feedback,
                                repair_context=repair_context,
                            )
                        return await extract_loop_plan(
                            request_id=identity, source=source, config=config, provider=provider,
                            compact=True,
                            feedback=feedback,
                            repair_context=repair_context,
                        )

                return asyncio.run(extract())
            finally:
                slots.release()

        return PreparationExtractor(call, max_retries=binding.config.max_retries, max_repairs=2)

    @asynccontextmanager
    async def _extraction_slot(self):
        # The existing capacity of one is shared across the ordinary and owned event loops.
        while not self._extraction_slots.acquire(blocking=False):
            await asyncio.sleep(0.01)
        try:
            yield
        finally:
            self._extraction_slots.release()

    async def _run_extraction(self, *, operation_id: UUID, source_text: str) -> None:
        queued = self._operations[operation_id]
        try:
            async with self._extraction_slot():
                started_at = _now()
                self._operations[operation_id] = PlanExtractionView(
                    id=operation_id,
                    provider_id=queued.provider_id,
                    status=PlanExtractionOperationStatus.RUNNING,
                    submitted_at=queued.submitted_at,
                    started_at=started_at,
                )
                binding = self._require_binding(queued.provider_id)
                result = await extract_plan(
                    request_id=operation_id,
                    source_text=source_text,
                    config=binding.config.model_copy(update={"prompt_version": "plan-extract-v10"}),
                    provider=binding.provider,
                )
                completed_at = _now()
                if result.status is PlanExtractionStatus.SUCCEEDED:
                    review_store = self._review_store
                    if review_store is None:
                        raise RuntimeError("plan extraction review store is unavailable")
                    await review_store.record_plan_extraction(result)
                diagnostic_status = None
                if self._diagnostic_path is not None:
                    try:
                        await asyncio.to_thread(
                            append_extraction_diagnostic,
                            self._diagnostic_path,
                            result=result,
                            configured_model=binding.config.model,
                            completed_at=completed_at,
                        )
                    except OSError, ValueError:
                        self._diagnostic_sink_available = False
                        diagnostic_status = "WRITE_FAILED"
                    else:
                        self._diagnostic_sink_available = True
                        diagnostic_status = "RECORDED"
                completed_view = _completed_extraction_view(
                    result=result,
                    submitted_at=queued.submitted_at,
                    started_at=started_at,
                    completed_at=completed_at,
                    diagnostic_status=diagnostic_status,
                )
                self._operations[operation_id] = completed_view
        except asyncio.CancelledError:
            current = self._operations[operation_id]
            self._operations[operation_id] = PlanExtractionView(
                id=operation_id,
                provider_id=queued.provider_id,
                status=PlanExtractionOperationStatus.CANCELLED,
                submitted_at=queued.submitted_at,
                started_at=current.started_at,
                completed_at=_now(),
            )
            raise
        except Exception:
            current = self._operations[operation_id]
            self._operations[operation_id] = PlanExtractionView(
                id=operation_id,
                provider_id=queued.provider_id,
                status=PlanExtractionOperationStatus.PROVIDER_ERROR,
                submitted_at=queued.submitted_at,
                started_at=current.started_at or _now(),
                completed_at=_now(),
            )

    def _provider_view(self, binding: ConfiguredAIProviderBinding) -> AIProviderView:
        configured_at = self._configured_at
        secret_store = self._secret_store
        if configured_at is None or secret_store is None:
            raise RuntimeError("configured AI Web lifecycle is not started")
        config = binding.config
        status = secret_store.status(config.secret_ref)
        return AIProviderView(
            config=AIProviderConfiguration(
                provider_id=config.provider_id,
                display_name=config.display_name,
                provider_type=config.provider_type,
                base_url=config.base_url,
                model=config.model,
                secret_reference=SecretReferenceView(
                    key=config.secret_ref.key,
                ),
                timeout_seconds=config.timeout_seconds,
                max_retries=config.max_retries,
                max_input_chars=config.max_input_chars,
                max_output_tokens=config.max_output_tokens,
                temperature=config.temperature,
                prompt_version=config.prompt_version,
                allow_redirects=False,
                enabled=config.enabled,
            ),
            secret_status=SecretStatusView(
                configured=status.configured,
                source=status.source,
                masked_value=status.masked_value,
                generation=status.generation,
            ),
            revision=0,
            created_at=configured_at,
            updated_at=configured_at,
        )

    def _runtime_provider_view(
        self,
        binding: ConfiguredAIProviderBinding,
    ) -> ConfiguredAIProviderRuntimeView:
        secret_store = self._secret_store
        if secret_store is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        config = binding.config
        return ConfiguredAIProviderRuntimeView(
            provider_id=config.provider_id,
            display_name=config.display_name,
            base_url=config.base_url,
            model=config.model,
            configured=secret_store.status(config.secret_ref).configured,
            enabled=config.enabled,
            max_input_chars=config.max_input_chars,
            max_output_tokens=config.max_output_tokens,
            revision=0,
        )

    def _require_binding(
        self,
        provider_id: UUID | None = None,
    ) -> ConfiguredAIProviderBinding:
        if self._client is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        binding = self._binding if provider_id is None else self._bindings.get(provider_id)
        if binding is None:
            error_code = (
                ApiErrorCode.SERVICE_UNAVAILABLE if provider_id is None else ApiErrorCode.NOT_FOUND
            )
            raise ApiError(error_code)
        return binding


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(30),
        trust_env=False,
    )


def _completed_extraction_view(
    *,
    result: PlanExtractionResult,
    submitted_at: datetime,
    started_at: datetime,
    completed_at: datetime,
    diagnostic_status: str | None = None,
) -> PlanExtractionView:
    status = PlanExtractionOperationStatus(result.status.value)
    if result.status is not PlanExtractionStatus.SUCCEEDED:
        return PlanExtractionView(
            id=result.request_id,
            provider_id=result.provider_id,
            status=status,
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
            validation_issues=result.validation_issues,
            diagnostic_status=diagnostic_status,
        )
    usage = None
    if result.usage is not None:
        usage = AIUsageView(
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
        )
    from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionResult

    if isinstance(result, CurrentPlanExtractionResult):
        from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json

        return PlanExtractionView(
            id=result.request_id,
            provider_id=result.provider_id,
            status=status,
            submitted_at=submitted_at,
            started_at=started_at,
            completed_at=completed_at,
            source_text_sha256=result.source_text_sha256,
            model=result.model,
            prompt_version=result.prompt_version,
            draft_plan_json=daily_draft_json(result.draft),
            daily_mapping=result.daily_mapping,
            assumptions=result.assumptions,
            warnings=result.warnings,
            validation_issues=result.validation_issues,
            usage=usage,
            diagnostic_status=diagnostic_status,
        )
    return PlanExtractionView(
        id=result.request_id,
        provider_id=result.provider_id,
        status=status,
        submitted_at=submitted_at,
        started_at=started_at,
        completed_at=completed_at,
        source_text_sha256=result.source_text_sha256,
        model=result.model,
        prompt_version=result.prompt_version,
        draft_plan_json=(
            dump_explicit_plan_draft_json(result.draft)
            if isinstance(result.draft, ExplicitPlanDraft)
            else dump_plan_json(result.draft)
        ),
        mapping=(None if result.mapping is None else PlanMappingView.from_domain(result.mapping)),
        evidence=result.evidence,
        assumptions=result.assumptions,
        warnings=result.warnings,
        unmapped_text=result.unmapped_text,
        validation_issues=result.validation_issues,
        usage=usage,
        diagnostic_status=diagnostic_status,
    )


def _extraction_request_hash(command: PlanExtractionCommand) -> str:
    payload = json.dumps(
        {
            "expectedRevision": command.expected_revision,
            "kind": OperationKind.PLAN_EXTRACTION.value,
            "providerId": str(command.provider_id),
            "sourceText": command.source_text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now() -> datetime:
    return datetime.now(_SHANGHAI)


__all__ = ["ConfiguredAIWebLifecycle"]
