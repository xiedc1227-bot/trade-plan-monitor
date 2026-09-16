"""Persistent application service for production plan Web operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import to_thread
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.ai.models import (
    ExplicitPlanDraft,
    PlanExtractionResult,
    PlanExtractionReview,
    PlanMapping,
    RequiredReviewIssue,
    ReviewResolution,
    ServerReviewSnapshot,
    build_plan_extraction_review,
)
from trade_plan_monitor.ai.review import (
    build_server_review_snapshot,
    explicit_draft_sha256,
    load_explicit_plan_draft_json,
    reconcile_plan_mapping,
)
from trade_plan_monitor.domain.plan_codec import load_plan_json, load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan, TradePlan
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    DraftReviewIssue,
    PlanValidationResult,
    ValidationIssue,
    ValidationSeverity,
    validate_trade_plan,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import PlanReviewOrigin, PlanVersionStatus
from trade_plan_monitor.state.repositories import (
    DuplicatePlanVersionError,
    IdempotencyInProgressError,
    IdempotencyKeyReuseError,
    PlanActivationBlockedError,
    PlanExtractionReviewRecord,
    PlanRepository,
    PlanReviewConfirmationRecord,
    PlanSaveBlockedError,
    PlanVersionNotFoundError,
    RepositoryError,
    RevisionConflictError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay, operation_hash
from trade_plan_monitor.web.routers.alerts import _explicit_evidence_view
from trade_plan_monitor.web.routers.plans import (
    MAX_SAFE_INTEGER,
    ActivePlanView,
    ExplicitPlanRuntimeView,
    ExplicitRuleOutcomeView,
    PlanActivationCommand,
    PlanDeactivationCommand,
    PlanDocumentFormat,
    PlanDraftCommand,
    PlanExtractionCommand,
    PlanExtractionView,
    PlanImportCommand,
    PlanMappingView,
    PlanReviewConfirmationCommand,
    PlanReviewConfirmationView,
    PlanVersionPage,
    PlanVersionSummary,
    PlanVersionView,
    RequiredReviewIssueView,
)
from trade_plan_monitor.web.schemas import MutationContext, OperationReceipt

DEFAULT_MONITOR_DATABASE = Path("data/monitor.sqlite3")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_PLAN_ROWS = 10_000
_FILTER_BATCH_SIZE = 100
_INCOMPATIBLE_TABLES = frozenset(
    {
        "backtest_detail",
        "backtest_fill",
        "backtest_job",
        "backtest_job_idempotency",
        "backtest_job_state",
        "backtest_plan_snapshot",
        "backtest_run",
        "backtest_run_input",
        "market_artifact",
        "market_dataset",
        "market_dataset_index_item",
        "market_dataset_item",
        "market_head",
        "market_index_artifact",
        "market_index_head",
        "market_minute_artifact",
        "market_minute_head",
    }
)


class _PlanVersionDetails(Protocol):
    id: str
    plan_id: str
    version: int
    symbol: str
    plan_hash: str
    status: str
    payload_json: str
    source_text: str
    source_hash: str
    review_issues: tuple[DraftReviewIssue, ...]
    review_origin: PlanReviewOrigin
    extraction_id: str | None
    review_confirmed_at: datetime | None
    content_hash: str | None
    review_evidence_hash: str | None
    mapping: PlanMapping | None
    required_review_issues: tuple[RequiredReviewIssue, ...]
    resolutions: tuple[ReviewResolution, ...]
    review_id: str | None
    review_revision: int
    revision: int
    created_at: datetime


class _ActivationState(Protocol):
    symbol: str
    plan_version_id: str | None
    revision: int
    changed_at: datetime


class PersistentPlanWebLifecycle:
    """Own one migrated SQLite engine and expose its plan operation service."""

    def __init__(
        self,
        *,
        database_path: Path = DEFAULT_MONITOR_DATABASE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(database_path, Path):
            raise TypeError("database_path must be a Path")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._database_path = database_path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def operation_service(self) -> PersistentPlanWebLifecycle:
        return self

    async def start(self) -> None:
        """Open and migrate the live store only after lifespan startup begins."""

        await to_thread.run_sync(self._start_sync)

    async def stop(self) -> None:
        """Dispose the owned engine and make further operations fail closed."""

        await to_thread.run_sync(self._stop_sync)

    async def list_plan_versions(
        self,
        *,
        offset: int,
        limit: int,
        symbol: str | None,
        status: PlanVersionStatus | None,
        can_activate: bool | None,
    ) -> PlanVersionPage:
        return await self._run(
            self._list_plan_versions_sync,
            offset=offset,
            limit=limit,
            symbol=symbol,
            status=status,
            can_activate=can_activate,
        )

    async def get_plan_version(self, *, version_id: str) -> PlanVersionView | None:
        return await self._run(self._get_plan_version_sync, version_id=version_id)

    async def get_plan_activation_state(self, *, symbol: str) -> ActivePlanView | None:
        return await self._run(self._get_plan_activation_state_sync, symbol=symbol)

    async def get_explicit_plan_runtime(self, *, symbol: str) -> ExplicitPlanRuntimeView | None:
        return await self._run(self._get_explicit_plan_runtime_sync, symbol=symbol)

    async def save_plan_draft(
        self,
        *,
        command: PlanDraftCommand,
        context: MutationContext,
    ) -> PlanVersionView:
        plan = _load_reviewable_plan(command.plan_json)
        _require_web_safe_plan(plan)
        return await self._run_mutation(
            self._save_plan_sync,
            operation="SAVE_PLAN_DRAFT",
            command=command,
            context=context,
            plan=plan,
            source_text=command.source_text,
            review_issues=command.review_issues,
        )

    async def confirm_plan_review(
        self,
        *,
        command: PlanReviewConfirmationCommand,
        context: MutationContext,
    ) -> PlanReviewConfirmationView:
        return await self._run_mutation(
            self._confirm_plan_review_sync,
            operation="CONFIRM_PLAN_REVIEW",
            command=command,
            context=context,
        )

    async def record_plan_extraction(self, result: PlanExtractionResult) -> None:
        """Persist a successful extraction's server-owned activation review facts."""

        review = build_plan_extraction_review(result)
        await self._run(
            self._record_plan_extraction_sync,
            review=review,
            completed_at=self._clock(),
        )

    async def import_plan(
        self,
        *,
        command: PlanImportCommand,
        context: MutationContext,
    ) -> PlanVersionView:
        plan = (
            load_plan_json(command.document)
            if command.format is PlanDocumentFormat.JSON
            else load_plan_yaml(command.document)
        )
        if isinstance(plan, ExplicitTradePlan):
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        _require_web_safe_plan(plan)
        if plan.symbol != command.symbol:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR)
        return await self._run_mutation(
            self._save_plan_sync,
            operation="IMPORT_PLAN",
            command=command,
            context=context,
            plan=plan,
            source_text=command.document,
            review_issues=(),
        )

    async def activate_plan(
        self,
        *,
        command: PlanActivationCommand,
        context: MutationContext,
    ) -> ActivePlanView:
        return await self._run_mutation(
            self._activate_plan_sync,
            operation="ACTIVATE_PLAN",
            command=command,
            context=context,
        )

    async def deactivate_plan(
        self,
        *,
        command: PlanDeactivationCommand,
        context: MutationContext,
    ) -> ActivePlanView:
        return await self._run_mutation(
            self._deactivate_plan_sync,
            operation="DEACTIVATE_PLAN",
            command=command,
            context=context,
        )

    async def submit_plan_extraction(
        self,
        *,
        command: PlanExtractionCommand,
        context: MutationContext,
    ) -> OperationReceipt:
        del command, context
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)

    async def get_plan_extraction(self, *, operation_id: str) -> PlanExtractionView | None:
        del operation_id
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)

    def _start_sync(self) -> None:
        if self._engine is not None:
            return
        path = self._database_path.expanduser().resolve()
        _reject_incompatible_database(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_sqlite_engine(path)
        try:
            upgrade_database(engine)
        except BaseException:
            engine.dispose()
            raise
        self._engine = engine
        self._session_factory = create_session_factory(engine)

    def _stop_sync(self) -> None:
        engine = self._engine
        self._session_factory = None
        self._engine = None
        if engine is not None:
            engine.dispose()

    async def _run[ResultT](
        self,
        function: Callable[..., ResultT],
        /,
        **kwargs: object,
    ) -> ResultT:
        self._require_session_factory()
        return await to_thread.run_sync(partial(function, **kwargs))

    async def _run_mutation[ResultT](
        self,
        function: Callable[..., ResultT],
        *,
        operation: str,
        command: object,
        context: MutationContext,
        **kwargs: object,
    ) -> ResultT:
        request_hash = operation_hash(operation, command)
        try:
            return await self._run(
                function,
                request_hash=request_hash,
                context=context,
                command=command,
                **kwargs,
            )
        except IdempotencyKeyReuseError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except PlanVersionNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except PlanSaveBlockedError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except (
            DuplicatePlanVersionError,
            IdempotencyInProgressError,
            PlanActivationBlockedError,
            RevisionConflictError,
        ):
            raise ApiError(ApiErrorCode.CONFLICT) from None
        except RepositoryError:
            raise RuntimeError("persistent plan operation failed") from None

    def _list_plan_versions_sync(
        self,
        *,
        offset: int,
        limit: int,
        symbol: str | None,
        status: PlanVersionStatus | None,
        can_activate: bool | None,
    ) -> PlanVersionPage:
        with self._unit_of_work() as work:
            status_value = None if status is None else status.value
            if can_activate is None:
                records, total = work.plans.list_version_details(
                    offset=offset,
                    limit=limit,
                    symbol=symbol,
                    status=status_value,
                )
                items = tuple(_plan_version_summary(record) for record in records)
            else:
                window: list[PlanVersionSummary] = []
                matched_total = 0
                scan_offset = 0
                total_unfiltered = 0
                while scan_offset < _MAX_PLAN_ROWS:
                    records, total_unfiltered = work.plans.list_version_details(
                        offset=scan_offset,
                        limit=_FILTER_BATCH_SIZE,
                        symbol=symbol,
                        status=status_value,
                    )
                    for record in records:
                        summary = _plan_version_summary(record)
                        if summary.can_activate is can_activate:
                            if offset <= matched_total < offset + limit:
                                window.append(summary)
                            matched_total += 1
                        del summary
                    scan_offset += len(records)
                    if not records or scan_offset >= total_unfiltered:
                        break
                if total_unfiltered > _MAX_PLAN_ROWS:
                    raise RuntimeError("plan version collection exceeds its public bound")
                total = matched_total
                items = tuple(window)
        if total > _MAX_PLAN_ROWS:
            raise RuntimeError("plan version collection exceeds its public bound")
        return PlanVersionPage(items=items, offset=offset, limit=limit, total=total)

    def _get_plan_version_sync(self, *, version_id: str) -> PlanVersionView | None:
        with self._unit_of_work() as work:
            record = work.plans.get_version_details(version_id)
            return None if record is None else _plan_version_view(record)

    def _get_plan_activation_state_sync(self, *, symbol: str) -> ActivePlanView | None:
        with self._unit_of_work() as work:
            record = work.plans.get_activation_state(symbol)
            if record is not None:
                return _active_plan_view(record)
            return ActivePlanView(
                symbol=symbol,
                plan_version_id=None,
                active=False,
                revision=0,
                changed_at=_shanghai_datetime(self._clock()),
            )

    def _get_explicit_plan_runtime_sync(self, *, symbol: str) -> ExplicitPlanRuntimeView | None:
        with self._unit_of_work() as work:
            active = work.plans.get_activation_state(symbol)
            if active is None or active.plan_version_id is None:
                return None
            details = work.plans.get_version_details(active.plan_version_id)
            if details is None:
                raise RepositoryError("Active plan version could not be reloaded")
            draft = _load_reviewable_plan(details.payload_json)
            if not isinstance(draft, ExplicitPlanDraft):
                return None
            executable = draft.to_executable()
            if executable is None:
                raise RepositoryError("Active explicit plan must be complete")
            result = work.explicit_rules.latest(
                activation_revision=active.revision,
                plan_hash=plan_sha256(executable),
                symbol=executable.symbol,
            )
            if result is None:
                return ExplicitPlanRuntimeView(
                    activation_revision=active.revision,
                    evaluated_at=None,
                    plan_hash=plan_sha256(executable),
                    plan_version_id=UUID(active.plan_version_id),
                    rule_outcomes=(),
                    status="AWAITING_EVALUATION",
                    symbol=executable.symbol,
                    target_bucket_end=None,
                )
            return ExplicitPlanRuntimeView(
                activation_revision=result.activation_revision,
                evaluated_at=_shanghai_datetime(result.evaluated_at),
                plan_hash=result.plan_hash,
                plan_version_id=UUID(active.plan_version_id),
                rule_outcomes=tuple(
                    ExplicitRuleOutcomeView(
                        action=item.action.type,
                        blockers=item.blockers,
                        condition_code=item.condition_evidence.condition.type,
                        condition_evidence=_explicit_evidence_view(item.condition_evidence),
                        missing_inputs=tuple(
                            value.value for value in item.condition_evidence.missing_inputs
                        ),
                        outcome=item.condition_evidence.outcome.value,
                        rule_id=item.rule_id,
                        suppression_reason=item.suppression_reason,
                    )
                    for item in result.rule_results
                ),
                status="CURRENT",
                symbol=result.symbol,
                target_bucket_end=_shanghai_datetime(result.target_bucket_end),
            )

    def _save_plan_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PlanDraftCommand | PlanImportCommand,
        plan: TradePlan | ExplicitPlanDraft,
        source_text: str,
        review_issues: tuple[DraftReviewIssue, ...],
    ) -> PlanVersionView:
        with self._unit_of_work() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=PlanVersionView,
            )
            if replay is not None:
                return replay
            base_extraction_id: str | None = None
            if isinstance(command, PlanDraftCommand) and command.base_plan_version_id is not None:
                base = work.plans.get_version_details(str(command.base_plan_version_id))
                if base is None:
                    raise PlanVersionNotFoundError("Base plan version was not found")
                _validated_persisted_plan(base)
                base_extraction_id = base.extraction_id
                if plan.plan_id != base.plan_id or plan.symbol != base.symbol:
                    raise PlanSaveBlockedError(
                        "Draft identity does not match its base plan version"
                    )
                next_version = work.plans.next_version(base.plan_id)
                if next_version > MAX_SAFE_INTEGER:
                    raise PlanSaveBlockedError("Plan version sequence is exhausted")
                plan = plan.model_copy(update={"version": next_version})
            (
                review_issues,
                review_origin,
                extraction_id,
                review_confirmed_at,
                explicit_snapshot,
            ) = _resolve_server_review(
                plans=work.plans,
                command=command,
                plan=plan,
                source_text=source_text,
                submitted_issues=review_issues,
                now=self._clock(),
                base_extraction_id=base_extraction_id,
            )
            activation = work.plans.get_activation_state(plan.symbol)
            current_revision = 0 if activation is None else activation.revision
            if command.expected_revision != current_revision:
                raise RevisionConflictError(current_revision)
            saved = work.plans.save_draft(
                plan,
                source_text=source_text,
                review_issues=review_issues,
                review_origin=review_origin,
                extraction_id=extraction_id,
                review_confirmed_at=review_confirmed_at,
                explicit_snapshot=explicit_snapshot,
            )
            details = work.plans.get_version_details(saved.id)
            if details is None:
                raise RepositoryError("Saved plan version could not be reloaded")
            result = _plan_version_view(details)
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _record_plan_extraction_sync(
        self,
        *,
        review: object,
        completed_at: datetime,
    ) -> None:
        with self._unit_of_work() as work:
            work.plans.record_extraction_review(
                cast(PlanExtractionReview, review),
                completed_at=completed_at,
            )
            work.commit()

    def _confirm_plan_review_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PlanReviewConfirmationCommand,
    ) -> PlanReviewConfirmationView:
        with self._unit_of_work() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=PlanReviewConfirmationView,
            )
            if replay is not None:
                return replay
            try:
                record = work.plans.confirm_explicit_review(
                    plan_version_id=str(command.plan_version_id),
                    content_hash=command.content_hash,
                    source_hash=command.source_hash,
                    review_evidence_hash=command.review_evidence_hash,
                    expected_revision=command.expected_revision,
                    resolutions=tuple(
                        ReviewResolution.model_validate(item.model_dump(mode="python"))
                        for item in command.resolutions
                    ),
                )
            except ValueError as error:
                raise PlanSaveBlockedError("Plan review resolution is invalid") from error
            result = _plan_review_confirmation_view(record)
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _activate_plan_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PlanActivationCommand,
    ) -> ActivePlanView:
        with self._unit_of_work() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=ActivePlanView,
            )
            if replay is not None:
                return replay
            details = work.plans.get_version_details(str(command.plan_version_id))
            if details is None:
                raise PlanVersionNotFoundError("Plan version was not found")
            stored_plan = _load_reviewable_plan(details.payload_json)
            if isinstance(stored_plan, ExplicitPlanDraft):
                if (
                    command.review_id is None
                    or command.content_hash is None
                    or details.review_id != str(command.review_id)
                    or details.content_hash != command.content_hash
                    or details.review_confirmed_at is None
                ):
                    raise PlanActivationBlockedError(
                        "Explicit activation requires the current server review binding"
                    )
                executable = stored_plan.to_executable()
                if executable is None:
                    raise PlanActivationBlockedError(
                        "Explicit activation requires a complete executable draft"
                    )
                _draft, validation, can_activate = _validated_plan_state(details)
                if (
                    PlanVersionStatus(details.status) is not PlanVersionStatus.DRAFT
                    or not can_activate
                ):
                    raise PlanActivationBlockedError("Plan is not ready for activation")
                work.plans.activate(
                    executable,
                    expected_revision=command.expected_revision,
                    validation=validation,
                )
                state = work.plans.get_activation_state(executable.symbol)
                if state is None:
                    raise RepositoryError("Activated plan state could not be reloaded")
                result = _active_plan_view(state)
                complete_replay(
                    work,
                    context=context,
                    request_hash=request_hash,
                    response=result,
                )
                work.commit()
                return result
            plan, validation, can_activate = _validated_plan_state(details)
            if PlanVersionStatus(details.status) is not PlanVersionStatus.DRAFT or not can_activate:
                raise PlanActivationBlockedError("Plan is not ready for activation")
            work.plans.activate(
                plan,
                expected_revision=command.expected_revision,
                validation=validation,
            )
            state = work.plans.get_activation_state(plan.symbol)
            if state is None:
                raise RepositoryError("Activated plan state could not be reloaded")
            result = _active_plan_view(state)
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _deactivate_plan_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PlanDeactivationCommand,
    ) -> ActivePlanView:
        with self._unit_of_work() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=ActivePlanView,
            )
            if replay is not None:
                return replay
            work.plans.deactivate(
                command.symbol,
                expected_revision=command.expected_revision,
            )
            state = work.plans.get_activation_state(command.symbol)
            if state is None:
                raise RepositoryError("Deactivated plan state could not be reloaded")
            result = _active_plan_view(state)
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            self._require_session_factory(),
            clock=self._clock,
        )

    def _require_session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        return self._session_factory


def _plan_version_summary(record: object) -> PlanVersionSummary:
    details = cast(_PlanVersionDetails, record)
    _plan, _validation, can_activate = _validated_plan_state(details)
    return PlanVersionSummary(
        id=UUID(details.id),
        plan_id=details.plan_id,
        version=details.version,
        symbol=details.symbol,
        plan_hash=details.plan_hash,
        status=PlanVersionStatus(details.status),
        can_activate=can_activate,
        revision=details.revision,
        created_at=_shanghai_datetime(details.created_at),
    )


def _resolve_server_review(
    *,
    plans: PlanRepository,
    command: PlanDraftCommand | PlanImportCommand,
    plan: TradePlan | ExplicitPlanDraft,
    source_text: str,
    submitted_issues: tuple[DraftReviewIssue, ...],
    now: datetime,
    base_extraction_id: str | None,
) -> tuple[
    tuple[DraftReviewIssue, ...],
    PlanReviewOrigin,
    str | None,
    datetime | None,
    ServerReviewSnapshot | None,
]:
    source_hash = sha256(source_text.encode("utf-8")).hexdigest()
    draft_hash = (
        explicit_draft_sha256(plan) if isinstance(plan, ExplicitPlanDraft) else plan_sha256(plan)
    )
    requested_extraction_id = (
        str(command.extraction_id)
        if isinstance(command, PlanDraftCommand) and command.extraction_id is not None
        else base_extraction_id
    )
    extraction: PlanExtractionReviewRecord | None
    if isinstance(plan, ExplicitPlanDraft):
        if not isinstance(command, PlanDraftCommand):
            raise PlanSaveBlockedError("Explicit drafts require the review-only save endpoint")
        extraction = (
            plans.get_extraction_review(requested_extraction_id)
            if requested_extraction_id is not None
            else plans.find_extraction_review_by_source_hash(source_hash)
        )
        if (
            extraction is None
            or extraction.prompt_version
            not in {"plan-extract-v4", "plan-extract-v5", "plan-extract-v6"}
            or extraction.mapping is None
            or extraction.source_hash != source_hash
        ):
            raise PlanSaveBlockedError("Explicit draft has no matching v4 extraction evidence")
        from trade_plan_monitor.ai.source_processing import upgrade_source_mapping

        try:
            supplied_mapping = (
                command.mapping.to_domain() if command.mapping is not None else extraction.mapping
            )
            # Version numbering is assigned by the repository, not a trading input.
            # Keep only an existing technical CONTRACT binding synchronized when
            # saving an immutable successor; source/user bindings are never rewritten.
            if command.base_plan_version_id is not None:
                supplied_mapping = supplied_mapping.model_copy(
                    update={
                        "field_bindings": tuple(
                            binding.model_copy(update={"value": plan.version})
                            if binding.path == "version" and binding.origin.value == "CONTRACT"
                            else binding
                            for binding in supplied_mapping.field_bindings
                        )
                    }
                )
            mapping = upgrade_source_mapping(
                draft=plan,
                mapping=reconcile_plan_mapping(draft=plan, mapping=supplied_mapping),
                source_text=source_text,
            )
            snapshot = build_server_review_snapshot(
                draft=plan,
                mapping=mapping,
                source_text=source_text,
            )
        except ValueError:
            raise PlanSaveBlockedError(
                "Submitted mapping does not match the current source"
            ) from None
        origin = (
            PlanReviewOrigin.AI_EXTRACTION
            if extraction.draft_hash == draft_hash
            else PlanReviewOrigin.AI_EDITED
        )
        return (), origin, extraction.extraction_id, None, snapshot

    exact_source = False
    if requested_extraction_id is not None:
        extraction = plans.get_extraction_review(requested_extraction_id)
        if extraction is None or extraction.source_hash != source_hash:
            raise PlanSaveBlockedError("Extraction identity does not match the submitted draft")
        if extraction.draft_hash != draft_hash:
            return (*_pending_edited_review(extraction), None)
        exact_source = True
    else:
        extraction = plans.find_extraction_review(
            draft_hash=draft_hash,
            source_hash=source_hash,
        )
        if extraction is not None:
            exact_source = True
        else:
            extraction = plans.find_extraction_review_by_source_hash(source_hash)
            if extraction is not None:
                return (*_pending_edited_review(extraction), None)
            extraction = plans.find_extraction_review(draft_hash=draft_hash)

    if extraction is None:
        return submitted_issues, PlanReviewOrigin.MANUAL, None, None, None
    if not exact_source:
        return (
            tuple(
                issue.model_copy(update={"resolved": False}) for issue in extraction.review_issues
            ),
            PlanReviewOrigin.AI_REIMPORT,
            extraction.extraction_id,
            None,
            None,
        )

    resolved = _merge_review_confirmations(
        required=extraction.review_issues,
        submitted=submitted_issues,
    )
    confirmed_at = _shanghai_datetime(now) if all(issue.resolved for issue in resolved) else None
    return (
        resolved,
        PlanReviewOrigin.AI_EXTRACTION,
        extraction.extraction_id,
        confirmed_at,
        None,
    )


def _pending_edited_review(
    extraction: PlanExtractionReviewRecord,
) -> tuple[
    tuple[DraftReviewIssue, ...],
    PlanReviewOrigin,
    str,
    None,
]:
    """Invalidate prior approval when an AI-derived document hash changes."""

    return (
        tuple(issue.model_copy(update={"resolved": False}) for issue in extraction.review_issues),
        PlanReviewOrigin.AI_EDITED,
        extraction.extraction_id,
        None,
    )


def _merge_review_confirmations(
    *,
    required: tuple[DraftReviewIssue, ...],
    submitted: tuple[DraftReviewIssue, ...],
) -> tuple[DraftReviewIssue, ...]:
    def identity(issue: DraftReviewIssue) -> tuple[object, str, bool]:
        return issue.kind, issue.path, issue.material

    submitted_by_identity: dict[tuple[object, str, bool], DraftReviewIssue] = {}
    for issue in submitted:
        key = identity(issue)
        if key in submitted_by_identity:
            raise PlanSaveBlockedError("Review confirmation identities must be unique")
        submitted_by_identity[key] = issue
    required_identities = {identity(issue) for issue in required}
    if not submitted_by_identity.keys() <= required_identities:
        raise PlanSaveBlockedError("Review confirmation contains an unknown issue")
    counts: dict[tuple[object, str, bool], int] = {}
    for issue in required:
        key = identity(issue)
        counts[key] = counts.get(key, 0) + 1
    return tuple(
        issue.model_copy(
            update={
                "resolved": (
                    counts[identity(issue)] == 1
                    and submitted_by_identity.get(identity(issue), issue).resolved
                )
            }
        )
        for issue in required
    )


def _plan_version_view(record: object) -> PlanVersionView:
    details = cast(_PlanVersionDetails, record)
    plan, validation, can_activate = _validated_plan_state(details)
    resolved_ids = tuple(item.issue_id for item in details.resolutions)
    unresolved = tuple(
        issue for issue in details.required_review_issues if issue.issue_id not in set(resolved_ids)
    )
    return PlanVersionView(
        id=UUID(details.id),
        plan_id=details.plan_id,
        version=details.version,
        symbol=details.symbol,
        plan_hash=details.plan_hash,
        status=PlanVersionStatus(details.status),
        plan_json=details.payload_json,
        source_text=details.source_text,
        review_issues=details.review_issues,
        validation_issues=validation.issues,
        can_activate=can_activate,
        revision=details.revision,
        created_at=_shanghai_datetime(details.created_at),
        content_hash=details.content_hash,
        source_hash=(details.source_hash if isinstance(plan, ExplicitPlanDraft) else None),
        review_evidence_hash=details.review_evidence_hash,
        review_revision=(details.review_revision if isinstance(plan, ExplicitPlanDraft) else None),
        review_id=(None if details.review_id is None else UUID(details.review_id)),
        mapping=(None if details.mapping is None else PlanMappingView.from_domain(details.mapping)),
        required_review_issues=tuple(
            RequiredReviewIssueView.from_domain(issue) for issue in details.required_review_issues
        ),
        resolved_issue_ids=resolved_ids,
        unresolved_review_issues=tuple(
            RequiredReviewIssueView.from_domain(issue) for issue in unresolved
        ),
        execution_readiness=("NOT_EVALUATED" if isinstance(plan, ExplicitPlanDraft) else None),
    )


def _validated_plan_state(
    details: _PlanVersionDetails,
) -> tuple[TradePlan | ExplicitPlanDraft, PlanValidationResult, bool]:
    plan = _validated_persisted_plan(details)
    if isinstance(plan, ExplicitPlanDraft):
        resolved = {item.issue_id for item in details.resolutions}
        unresolved = tuple(
            issue for issue in details.required_review_issues if issue.issue_id not in resolved
        )
        validation = PlanValidationResult(
            issues=tuple(
                ValidationIssue(
                    code=issue.code,
                    path=issue.path,
                    severity=ValidationSeverity.WARNING,
                    message=issue.reason,
                    activation_blocking=True,
                )
                for issue in unresolved
            )
        )
        can_activate = (
            plan.to_executable() is not None
            and details.review_id is not None
            and details.review_confirmed_at is not None
            and not unresolved
        )
        return plan, validation, can_activate
    validation = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=details.review_issues,
    )
    if (
        details.review_origin is PlanReviewOrigin.LEGACY_PENDING
        and PlanVersionStatus(details.status) is not PlanVersionStatus.ACTIVE
    ):
        validation = validation.model_copy(
            update={
                "issues": (
                    *validation.issues,
                    ValidationIssue(
                        code="LEGACY_REVIEW_REQUIRED",
                        path="draft",
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "Legacy plan review provenance must be confirmed before activation."
                        ),
                        activation_blocking=True,
                    ),
                )
            }
        )
    review_confirmed = (
        details.review_origin
        not in {
            PlanReviewOrigin.AI_EXTRACTION,
            PlanReviewOrigin.AI_EDITED,
            PlanReviewOrigin.AI_REIMPORT,
        }
        or details.review_confirmed_at is not None
    )
    can_activate = (
        validation.can_activate
        and review_confirmed
        and not any(not issue.resolved for issue in details.review_issues)
    )
    return plan, validation, can_activate


def _validated_persisted_plan(
    record: _PlanVersionDetails,
) -> TradePlan | ExplicitPlanDraft:
    try:
        plan = (
            load_explicit_plan_draft_json(record.payload_json)
            if record.content_hash is not None
            else load_plan_json(record.payload_json)
        )
    except TypeError, ValueError:
        raise RuntimeError("persisted plan state is invalid") from None
    if (
        plan.plan_id != record.plan_id
        or plan.version != record.version
        or plan.symbol != record.symbol
        or (
            explicit_draft_sha256(plan)
            if isinstance(plan, ExplicitPlanDraft)
            else plan_sha256(plan)
        )
        != record.plan_hash
    ):
        raise RuntimeError("persisted plan identity is invalid")
    return plan


def _active_plan_view(record: object) -> ActivePlanView:
    state = cast(_ActivationState, record)
    return ActivePlanView(
        symbol=state.symbol,
        plan_version_id=(None if state.plan_version_id is None else UUID(state.plan_version_id)),
        active=state.plan_version_id is not None,
        revision=state.revision,
        changed_at=_shanghai_datetime(state.changed_at),
    )


def _require_web_safe_plan(plan: TradePlan | ExplicitPlanDraft) -> None:
    if plan.version > MAX_SAFE_INTEGER:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)


def _load_reviewable_plan(document: str) -> TradePlan | ExplicitPlanDraft:
    try:
        return load_explicit_plan_draft_json(document)
    except ValueError:
        return load_plan_json(document)


def _plan_review_confirmation_view(
    record: PlanReviewConfirmationRecord,
) -> PlanReviewConfirmationView:
    return PlanReviewConfirmationView(
        plan_version_id=UUID(record.plan_version_id),
        review_id=None if record.review_id is None else UUID(record.review_id),
        content_hash=record.content_hash,
        source_hash=record.source_hash,
        review_evidence_hash=record.review_evidence_hash,
        revision=record.revision,
        confirmed_at=(
            None if record.confirmed_at is None else _shanghai_datetime(record.confirmed_at)
        ),
        unresolved_issues=tuple(
            RequiredReviewIssueView.from_domain(item) for item in record.unresolved_issues
        ),
        can_activate=record.can_activate,
    )


def _shanghai_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("persisted timestamp is invalid")
    return value.astimezone(_SHANGHAI)


def _reject_incompatible_database(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        return
    if not path.is_file():
        raise ValueError("monitor database_path must point to a file")
    try:
        with closing(
            sqlite3.connect(
                f"{path.as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=5,
            )
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                ).fetchall()
            }
    except OSError, sqlite3.Error:
        raise ValueError("monitor database_path must be a readable SQLite file") from None
    if tables & _INCOMPATIBLE_TABLES:
        raise ValueError("monitor database_path belongs to another storage domain")


__all__ = ["DEFAULT_MONITOR_DATABASE", "PersistentPlanWebLifecycle"]
