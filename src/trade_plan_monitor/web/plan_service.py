"""Persistent application service for production plan Web operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
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
    PlanMapping,
    RequiredReviewIssue,
    ReviewResolution,
)
from trade_plan_monitor.ai.review import (
    explicit_draft_sha256,
    load_explicit_plan_draft_json,
)
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyPlanDraft,
    daily_draft_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import (
    DraftReviewIssue,
    PlanValidationResult,
    ValidationIssue,
    ValidationSeverity,
)
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
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
    PlanReviewConfirmationRecord,
    PlanSaveBlockedError,
    PlanVersionNotFoundError,
    RepositoryError,
    RevisionConflictError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay, operation_hash
from trade_plan_monitor.web.routers.plans import (
    MAX_SAFE_INTEGER,
    ActivePlanView,
    PlanActivationCommand,
    PlanDeactivationCommand,
    PlanDraftCommand,
    PlanExtractionCommand,
    PlanExtractionView,
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
        source_clock = clock or (lambda: datetime.now(UTC))
        self._clock = lambda: _shanghai_datetime(source_clock())
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

    async def get_reviewed_backtest_plan(self, *, version_id: str):
        """Read approval, source and executable content in one read-only unit of work."""
        return await self._run(self._get_reviewed_backtest_plan_sync, version_id=version_id)

    def _get_reviewed_backtest_plan_sync(self, *, version_id):
        from trade_plan_monitor.backtest.plan_schedule import LoopPlanReview, LoopPlanVersion
        from trade_plan_monitor.backtest.workbench_selection import (
            WorkbenchPlanReference,
            WorkbenchReviewedPlan,
        )
        from trade_plan_monitor.domain.plan_hash import plan_sha256

        with self._unit_of_work() as work:
            details = work.plans.get_version_details(version_id)
            if details is None:
                return None
            draft, _validation, eligible = _validated_plan_state(details)
            if not eligible or details.review_confirmed_at is None:
                raise PlanSaveBlockedError("Reviewed current workbench plan required")
            snapshot = draft.to_executable()
            confirmed_at = details.review_confirmed_at.astimezone(_SHANGHAI)
            reference = WorkbenchPlanReference(
                origin="WORKBENCH", plan_version_id=UUID(details.id),
                plan_hash=details.plan_hash, content_hash=details.content_hash,
                source_hash=details.source_hash, review_evidence_hash=details.review_evidence_hash,
                review_id=UUID(details.review_id), review_revision=details.review_revision,
            )
            version = LoopPlanVersion(
                version_id=details.id,
                snapshot=snapshot,
                plan_hash=plan_sha256(snapshot),
                source_hashes=(details.source_hash,),
                evidence_hash=details.review_evidence_hash,
                available_at=confirmed_at,
                information_cutoff=confirmed_at,
                review=LoopPlanReview(
                    content_hash=details.content_hash,
                    reviewed_at=confirmed_at,
                    confirmed=True,
                    source_hashes=(details.source_hash,),
                    evidence_hash=details.review_evidence_hash,
                    evidence="Original workbench review " + details.review_id,
                ),
            )
            return WorkbenchReviewedPlan(
                reference=reference,
                version=version,
                draft_json=details.payload_json,
                source_text=details.source_text,
                mapping_json=details.daily_mapping.model_dump_json(),
            )

    async def get_plan_activation_state(self, *, symbol: str) -> ActivePlanView | None:
        return await self._run(self._get_plan_activation_state_sync, symbol=symbol)

    async def mutate_daily(self, *, operation, command, context):
        from trade_plan_monitor.web.daily_service import mutate_daily

        return await self._run_mutation(
            partial(mutate_daily, self),
            operation="DAILY_" + operation,
            command=command,
            context=context,
            operation_name=operation,
        )

    async def read_daily(self, *, symbol, trade_date):
        from trade_plan_monitor.web.daily_service import read_daily

        return await self._run(partial(read_daily, self), symbol=symbol, trade_date=trade_date)

    async def read_daily_supplements(self, *, candidate_json):
        from trade_plan_monitor.web.daily_service import read_daily_supplements

        return await self._run(partial(read_daily_supplements, self), candidate_json=candidate_json)

    async def save_plan_draft(
        self,
        *,
        command: PlanDraftCommand,
        context: MutationContext,
    ) -> PlanVersionView:
        plan = _load_reviewable_plan(command.plan_json)
        if plan.schema_version not in {5, 6, 7}:
            raise PlanSaveBlockedError(
                "Historical plan formats are read-only; "
                "extract the preserved source into a current draft"
            )
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

        from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionResult

        if isinstance(result, CurrentPlanExtractionResult):
            await self._run(self._record_daily_extraction_sync, result=result)
            return
        raise PlanSaveBlockedError("Only current extraction results can be recorded")


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

    def _save_plan_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PlanDraftCommand,
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
            if isinstance(command, PlanDraftCommand) and command.base_plan_version_id is not None:
                base = work.plans.get_version_details(str(command.base_plan_version_id))
                if base is None:
                    raise PlanVersionNotFoundError("Base plan version was not found")
                _validated_persisted_plan(base)
                if plan.plan_id != base.plan_id or plan.symbol != base.symbol:
                    raise PlanSaveBlockedError(
                        "Draft identity does not match its base plan version"
                    )
                next_version = work.plans.next_version(base.plan_id)
                if next_version > MAX_SAFE_INTEGER:
                    raise PlanSaveBlockedError("Plan version sequence is exhausted")
                plan = plan.model_copy(update={"version": next_version})
            if isinstance(plan, DailyPlanDraft):
                if (
                    not isinstance(command, PlanDraftCommand)
                    or command.daily_mapping is None
                    or command.mapping is not None
                ):
                    raise PlanSaveBlockedError("Daily draft requires its exact daily source map")
                activation = work.plans.get_activation_state(plan.symbol)
                current_revision = 0 if activation is None else activation.revision
                if command.expected_revision != current_revision:
                    raise RevisionConflictError(current_revision)
                # Candidates are review-only: saving an edit cannot silently replace
                # the active version or inherit an older version's review binding.
                try:
                    identity = save_daily_draft(
                        work,
                        plan,
                        mapping=command.daily_mapping,
                        source_text=source_text,
                        clock=self._clock,
                        extraction_id=None
                        if command.extraction_id is None
                        else str(command.extraction_id),
                    )
                except ValueError as error:
                    raise PlanSaveBlockedError("Daily source mapping is invalid") from error
                result = _plan_version_view(work.plans.get_version_details(identity))
                complete_replay(work, context=context, request_hash=request_hash, response=result)
                work.commit()
                return result
            raise PlanSaveBlockedError("Only current plan candidates can be saved")

    def _record_daily_extraction_sync(self, *, result):
        from trade_plan_monitor.state.daily_review_store import record_daily_extraction

        with self._unit_of_work() as work:
            record_daily_extraction(work, result, clock=self._clock)
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
            details = work.plans.get_version_details(str(command.plan_version_id))
            if (
                details is not None
                and _load_reviewable_plan(details.payload_json).schema_version not in {5, 6, 7}
            ):
                raise PlanSaveBlockedError("Historical review bindings are read-only")
            if details is not None and details.daily_mapping is not None:
                try:
                    record = confirm_daily_review(work, command, clock=self._clock)
                except ValueError as error:
                    raise PlanSaveBlockedError(
                        "Daily review has unresolved or stale evidence"
                    ) from error
                result = PlanReviewConfirmationView(
                    plan_version_id=UUID(record.id),
                    review_id=UUID(record.review_id),
                    content_hash=record.content_hash,
                    source_hash=record.source_hash,
                    review_evidence_hash=record.review_evidence_hash,
                    revision=record.review_revision,
                    confirmed_at=_shanghai_datetime(record.review_confirmed_at),
                    can_activate=True,
                )
                complete_replay(work, context=context, request_hash=request_hash, response=result)
                work.commit()
                return result
            raise PlanSaveBlockedError("Historical review bindings are read-only")

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
            if any(i.code == "DAILY_DRAFT_OBSOLETE" for i in details.daily_issues):
                raise PlanActivationBlockedError(
                    "DAILY_DRAFT_OBSOLETE: re-extract preserved source and review a new draft"
                )
            stored_plan = _load_reviewable_plan(details.payload_json)
            if stored_plan.schema_version not in {5, 6, 7}:
                raise PlanActivationBlockedError(
                    "Historical plan formats require a new current draft and explicit review"
                )
            if isinstance(stored_plan, DailyPlanDraft):
                if (
                    command.review_id is None
                    or details.review_id != str(command.review_id)
                    or details.review_confirmed_at is None
                    or (
                        command.content_hash,
                        command.source_hash,
                        command.review_evidence_hash,
                        command.review_revision,
                    )
                    != (
                        details.content_hash,
                        details.source_hash,
                        details.review_evidence_hash,
                        details.review_revision,
                    )
                    or details.daily_issues
                    or PlanVersionStatus(details.status) is not PlanVersionStatus.DRAFT
                ):
                    raise PlanActivationBlockedError(
                        "Daily activation requires exact current review binding"
                    )
                executable = stored_plan.to_executable()
                if executable is None:
                    raise PlanActivationBlockedError("Daily candidate is incomplete")
                work.plans.activate(
                    executable,
                    expected_revision=command.expected_revision,
                    validation=PlanValidationResult(issues=()),
                )
                result = _active_plan_view(work.plans.get_activation_state(executable.symbol))
                complete_replay(work, context=context, request_hash=request_hash, response=result)
                work.commit()
                return result
            raise PlanActivationBlockedError("Only current reviewed candidates can be activated")

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
        obsolete_reason="DAILY_DRAFT_OBSOLETE"
        if any(i.code == "DAILY_DRAFT_OBSOLETE" for i in details.daily_issues)
        else "LEGACY_PLANS_REQUIRE_REVIEW"
        if not can_activate and _plan is not None and _plan.schema_version not in {5, 6, 7}
        else None,
        revision=details.revision,
        created_at=_shanghai_datetime(details.created_at),
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
        obsolete_reason="DAILY_DRAFT_OBSOLETE"
        if any(i.code == "DAILY_DRAFT_OBSOLETE" for i in details.daily_issues)
        else "LEGACY_PLANS_REQUIRE_REVIEW"
        if plan is not None and plan.schema_version not in {5, 6, 7}
        else None,
        revision=details.revision,
        created_at=_shanghai_datetime(details.created_at),
        content_hash=details.content_hash,
        source_hash=details.source_hash,
        review_evidence_hash=details.review_evidence_hash,
        review_revision=(
            details.review_revision
            if isinstance(plan, ExplicitPlanDraft | DailyPlanDraft)
            or details.daily_mapping is not None
            else None
        ),
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
        daily_mapping=details.daily_mapping,
        daily_issues=details.daily_issues,
    )


def _validated_plan_state(
    details: _PlanVersionDetails,
) -> tuple[TradePlan | ExplicitPlanDraft, PlanValidationResult, bool]:
    if any(i.code == "DAILY_DRAFT_OBSOLETE" for i in details.daily_issues):
        validation = PlanValidationResult(
            issues=tuple(
                ValidationIssue(
                    code=i.code,
                    path=i.path,
                    severity=ValidationSeverity.WARNING,
                    message=i.reason,
                    activation_blocking=True,
                )
                for i in details.daily_issues
            )
        )
        return None, validation, False
    plan = _validated_persisted_plan(details)
    if plan.schema_version not in {5, 6, 7}:
        return (
            plan,
            PlanValidationResult(
                issues=(
                    ValidationIssue(
                        code="LEGACY_PLANS_REQUIRE_REVIEW",
                        path="draft",
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "Historical plan requires a new current draft "
                            "and explicit source review."
                        ),
                        activation_blocking=True,
                    ),
                )
            ),
            False,
        )
    if isinstance(plan, DailyPlanDraft):
        validation = PlanValidationResult(
            issues=tuple(
                ValidationIssue(
                    code=i.code,
                    path=i.path,
                    severity=ValidationSeverity.WARNING,
                    message=i.reason,
                    activation_blocking=True,
                )
                for i in details.daily_issues
            )
        )
        return (
            plan,
            validation,
            plan.to_executable() is not None
            and not details.daily_issues
            and details.review_id is not None,
        )
    raise RuntimeError("current plan is missing its server-owned source review")


def _validated_persisted_plan(
    record: _PlanVersionDetails,
) -> TradePlan | ExplicitPlanDraft:
    try:
        plan = (
            load_daily_draft_json(record.payload_json)
            if record.daily_mapping is not None
            else (
                load_explicit_plan_draft_json(record.payload_json)
                if record.content_hash is not None
                else load_plan_json(record.payload_json)
            )
        )
    except TypeError, ValueError:
        raise RuntimeError("persisted plan state is invalid") from None
    if (
        plan.plan_id != record.plan_id
        or plan.version != record.version
        or plan.symbol != record.symbol
        or (
            daily_draft_sha256(plan)
            if isinstance(plan, DailyPlanDraft)
            else explicit_draft_sha256(plan)
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
        return load_daily_draft_json(document)
    except ValueError:
        pass
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
