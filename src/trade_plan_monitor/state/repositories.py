"""Narrow repository contracts for durable strategy state."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_plan_monitor.ai.models import PlanExtractionReview
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import (
    DraftReviewIssue,
    PlanValidationResult,
    validate_trade_plan,
)
from trade_plan_monitor.market_data.aggregation import (
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.models import (
    DailyBar as NormalizedDailyBar,
)
from trade_plan_monitor.market_data.models import (
    DailyLimit as NormalizedDailyLimit,
)
from trade_plan_monitor.market_data.models import (
    MinuteBar as NormalizedMinuteBar,
)
from trade_plan_monitor.market_data.models import (
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.models import (
    TradingDay as NormalizedTradingDay,
)
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventLog,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    DailyPriceLimit,
    EvaluationKind,
    EvaluationLedger,
    IdempotencyStatus,
    LatestQuote,
    PendingOfficialClose,
    PlanActivationState,
    PlanReviewOrigin,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
    PlanVersionStatus,
    PositionBucket,
    PositionLot,
    ProviderHealth,
    RequestIdempotency,
    RiskState,
    StoredPlanExtractionReview,
    SymbolHealth,
    SymbolHealthStatus,
    TradingCalendar,
    ZoneEpisode,
)
from trade_plan_monitor.state.models import (
    DailyBar as DailyBarRow,
)
from trade_plan_monitor.state.models import (
    FiveMinuteBar as FiveMinuteBarRow,
)
from trade_plan_monitor.state.models import (
    MinuteBar as MinuteBarRow,
)

IdFactory = Callable[[], str]
Clock = Callable[[], datetime]


class RepositoryError(RuntimeError):
    """Base for sanitized persistence errors exposed to application services."""

    code = "REPOSITORY_ERROR"


class DuplicatePlanVersionError(RepositoryError):
    """A plan identity cannot be overwritten by another immutable payload."""

    code = "PLAN_VERSION_EXISTS"

    def __init__(self, plan_id: str, version: int) -> None:
        super().__init__(f"Plan version already exists: {plan_id} version {version}")


class PlanActivationBlockedError(RepositoryError):
    """The domain validation result does not allow plan activation."""

    code = "PLAN_ACTIVATION_BLOCKED"


class PlanSaveBlockedError(RepositoryError):
    """Cross-field domain errors prevent persisting a plan draft."""

    code = "PLAN_SAVE_BLOCKED"


class PlanVersionNotFoundError(RepositoryError):
    """The requested immutable version is absent or does not match its hash."""

    code = "PLAN_VERSION_NOT_FOUND"


class RevisionConflictError(RepositoryError):
    """A mutable record changed after the caller last observed it."""

    code = "CONFLICT"

    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"Revision conflict; current revision is {current_revision}")


class IdempotencyKeyReuseError(RepositoryError):
    """One idempotency key was presented for a different request hash."""

    code = "IDEMPOTENCY_KEY_REUSED"


class IdempotencyInProgressError(RepositoryError):
    """The same request is still pending in another completed transaction."""

    code = "IDEMPOTENCY_IN_PROGRESS"


class IdempotencyClaimNotFoundError(RepositoryError):
    """A response cannot complete an absent request claim."""

    code = "IDEMPOTENCY_CLAIM_NOT_FOUND"


class BoardLotViolationError(RepositoryError):
    """A manual buy quantity is not a positive whole board lot."""

    code = "BOARD_LOT_VIOLATION"


class MaxPositionExceededError(RepositoryError):
    """A manual buy would exceed the plan's maximum open quantity."""

    code = "MAX_POSITION_EXCEEDED"


class PositionLotNotFoundError(RepositoryError):
    """The requested position lot does not exist."""

    code = "POSITION_LOT_NOT_FOUND"


class PositionReductionError(RepositoryError):
    """A manual reduction exceeds the lot's remaining quantity."""

    code = "POSITION_REDUCTION_EXCEEDS_REMAINING"


class PositionT1LockedError(RepositoryError):
    """A lot acquired on the current or a later trade date is not sellable."""

    code = "POSITION_T1_LOCKED"


class EpisodeIdentityConflictError(RepositoryError):
    """An episode identifier is already bound to another immutable identity."""

    code = "EPISODE_IDENTITY_CONFLICT"


class EpisodeNotFoundError(RepositoryError):
    """The requested low-zone episode does not exist."""

    code = "EPISODE_NOT_FOUND"


class EpisodeTransitionError(RepositoryError):
    """An episode revision would violate monotonic low/progress invariants."""

    code = "EPISODE_TRANSITION_INVALID"


class EvaluationIdentityConflictError(RepositoryError):
    """One evaluation identity cannot be associated with two result hashes."""

    code = "EVALUATION_IDENTITY_CONFLICT"


class ProviderHealthConflictError(RepositoryError):
    """One provider observation time contains inconsistent health facts."""

    code = "PROVIDER_HEALTH_OBSERVATION_CONFLICT"


class MarketDataIdentityConflictError(RepositoryError):
    """One immutable market identity contains conflicting equal-version facts."""

    code = "MARKET_DATA_IDENTITY_CONFLICT"


class PlanVersionRecord(BaseModel):
    """Read-only application DTO for one persisted plan version."""

    model_config = ConfigDict(frozen=True)

    id: str
    plan_id: str
    version: int
    symbol: str
    plan_hash: str
    status: str
    payload_json: str
    source_id: str
    revision: int
    created_at: datetime


class PlanVersionDetailsRecord(PlanVersionRecord):
    """Persisted plan version with its source and bounded review state."""

    source_text: str
    review_issues: tuple[DraftReviewIssue, ...] = ()
    review_origin: PlanReviewOrigin
    extraction_id: str | None
    review_confirmed_at: datetime | None


class PlanExtractionReviewRecord(BaseModel):
    """Read-only server-owned extraction review snapshot."""

    model_config = ConfigDict(frozen=True)

    extraction_id: str
    provider_id: str
    model: str
    prompt_version: str
    source_hash: str
    draft_hash: str
    review_issues: tuple[DraftReviewIssue, ...]
    completed_at: datetime


class PlanActivationStateRecord(BaseModel):
    """Monotone per-symbol activation state, including inactive revisions."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    plan_version_id: str | None
    revision: int
    changed_at: datetime


class ActivePlanRecord(BaseModel):
    """Read-only DTO for the active immutable version of one symbol."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    plan_version_id: str
    activated_at: datetime
    revision: int


class IdempotencyRecord(BaseModel):
    """Read-only request claim or completed replay result."""

    model_config = ConfigDict(frozen=True)

    idempotency_key: str
    request_hash: str
    status: str
    response_code: int | None
    response_json: str | None
    created_at: datetime
    updated_at: datetime


class PositionLotRecord(BaseModel):
    """Read-only application DTO for one manual position lot."""

    model_config = ConfigDict(frozen=True)

    id: str
    symbol: str
    bucket: PositionBucket
    quantity: int
    remaining_qty: int
    acquired_trade_date: date
    cost_fen: int
    related_alert_id: str | None
    closed_at: datetime | None


class EpisodeRecord(BaseModel):
    """Read-only low-zone episode state keyed by a replay-stable identity."""

    model_config = ConfigDict(frozen=True)

    id: str
    plan_hash: str
    symbol: str
    zone: str
    started_at: datetime
    episode_low_fen: int
    bars_since_low: int
    status: str
    alerted_signal: str | None
    last_processed_bucket_end: datetime


class RiskStateRecord(BaseModel):
    """Read-only official-close risk state with optimistic revision."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    plan_hash: str
    status: str
    breach_trade_date: date | None
    prior_close_fen: int
    revision: int
    updated_at: datetime


class EvaluationRecord(BaseModel):
    """Read-only exactly-once evaluation ledger entry."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    plan_hash: str
    symbol: str
    evaluation_kind: EvaluationKind
    bucket_end: datetime | None
    official_trade_date: date | None
    formula_version: str
    result_hash: str
    evaluated_at: datetime

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy while revalidating the discriminated target shape."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="after")
    def validate_target_shape(self) -> Self:
        if self.evaluation_kind is EvaluationKind.INTRADAY:
            if self.bucket_end is None or self.official_trade_date is not None:
                raise ValueError("INTRADAY record requires only bucket_end")
            expected_five_minute_ends(self.bucket_end)
        elif self.bucket_end is not None or self.official_trade_date is None:
            raise ValueError("OFFICIAL_CLOSE record requires only official_trade_date")
        return self


class EvaluationClaimRecord(BaseModel):
    """Result of claiming an evaluation identity."""

    model_config = ConfigDict(frozen=True)

    record: EvaluationRecord
    created: bool


class ProviderHealthRecord(BaseModel):
    """Latest non-stale observation for one provider capability."""

    model_config = ConfigDict(frozen=True)

    capability: str
    status: ProviderCapabilityStatus
    checked_at: datetime
    latency_ms: int
    error_code: str | None
    next_retry_at: datetime | None


class SymbolHealthRecord(BaseModel):
    """Read-only isolated health state for one monitored symbol."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    status: SymbolHealthStatus
    latest_bar_end: datetime | None
    data_age_seconds: int
    gap_json: str
    error_streak: int
    revision: int


class FiveMinuteBarRecord(BaseModel):
    """Read-only deterministic five-minute persistence value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: str
    bar_end: datetime
    formula_version: str
    open_fen: int
    high_fen: int
    low_fen: int
    close_fen: int
    volume_shares: int
    amount_yuan: Decimal


class LatestQuoteRecord(BaseModel):
    """Read-only latest complete-minute projection for one symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: str
    price_fen: int
    bar_end: datetime
    received_at: datetime


class PlanRepository:
    """Persist immutable plan versions without exposing a raw Session."""

    _MAX_PAGE_LIMIT = 100
    _MAX_READ_ROWS = 10_000

    def __init__(
        self,
        session: Session,
        *,
        clock: Clock,
        id_factory: IdFactory,
        events: MonitorEventLog,
    ) -> None:
        self._session = session
        self._clock = clock
        self._id_factory = id_factory
        self._events = events

    def record_extraction_review(
        self,
        review: PlanExtractionReview,
        *,
        completed_at: datetime,
    ) -> PlanExtractionReviewRecord:
        if not isinstance(review, PlanExtractionReview):
            raise TypeError("review must be a PlanExtractionReview")
        timestamp = _aware_datetime(completed_at, "completed_at")
        expected = PlanExtractionReviewRecord(
            extraction_id=str(review.extraction_id),
            provider_id=str(review.provider_id),
            model=review.model,
            prompt_version=review.prompt_version,
            source_hash=review.source_text_sha256,
            draft_hash=review.draft_sha256,
            review_issues=review.review_issues,
            completed_at=timestamp,
        )
        model = StoredPlanExtractionReview(
            id=str(review.extraction_id),
            provider_id=str(review.provider_id),
            model=review.model,
            prompt_version=review.prompt_version,
            source_hash=review.source_text_sha256,
            draft_hash=review.draft_sha256,
            review_issues_json=_plan_review_issues_json(review.review_issues),
            completed_at=timestamp.isoformat(),
        )
        try:
            with self._session.begin_nested():
                self._session.add(model)
                self._session.flush()
        except IntegrityError:
            existing = self.get_extraction_review(str(review.extraction_id))
            if existing is not None and _same_extraction_review(existing, expected):
                return existing
            raise RepositoryError("Extraction review identity is already bound") from None
        return _plan_extraction_review_record(model)

    def get_extraction_review(self, extraction_id: str) -> PlanExtractionReviewRecord | None:
        model = self._session.get(
            StoredPlanExtractionReview,
            _uuid_identifier(extraction_id, "extraction_id"),
        )
        return None if model is None else _plan_extraction_review_record(model)

    def find_extraction_review(
        self,
        *,
        draft_hash: str,
        source_hash: str | None = None,
    ) -> PlanExtractionReviewRecord | None:
        filters = [StoredPlanExtractionReview.draft_hash == _sha256_hash(draft_hash, "draft_hash")]
        if source_hash is not None:
            filters.append(
                StoredPlanExtractionReview.source_hash == _sha256_hash(source_hash, "source_hash")
            )
        model = self._session.scalar(
            select(StoredPlanExtractionReview)
            .where(*filters)
            .order_by(
                StoredPlanExtractionReview.completed_at.desc(),
                StoredPlanExtractionReview.id.desc(),
            )
            .limit(1)
        )
        return None if model is None else _plan_extraction_review_record(model)

    def save_draft(
        self,
        plan: TradePlan,
        *,
        source_text: str,
        review_issues: Sequence[DraftReviewIssue] = (),
        review_origin: PlanReviewOrigin = PlanReviewOrigin.MANUAL,
        extraction_id: str | None = None,
        review_confirmed_at: datetime | None = None,
    ) -> PlanVersionRecord:
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        if not isinstance(source_text, str):
            raise TypeError("source_text must be a string")
        try:
            normalized_origin = PlanReviewOrigin(review_origin)
        except TypeError, ValueError:
            raise ValueError("review_origin is invalid") from None
        normalized_extraction_id = (
            None if extraction_id is None else _uuid_identifier(extraction_id, "extraction_id")
        )
        if (normalized_origin in {PlanReviewOrigin.LEGACY_PENDING, PlanReviewOrigin.MANUAL}) != (
            normalized_extraction_id is None
        ):
            raise ValueError("review origin and extraction identity are inconsistent")
        normalized_confirmed_at = (
            None
            if review_confirmed_at is None
            else _aware_datetime(review_confirmed_at, "review_confirmed_at")
        )
        normalized_review_issues = _plan_review_issues(review_issues)
        if normalized_origin in {PlanReviewOrigin.LEGACY_PENDING, PlanReviewOrigin.MANUAL}:
            if normalized_confirmed_at is not None:
                raise ValueError("manual and legacy review state cannot have a confirmation time")
        elif normalized_origin is PlanReviewOrigin.AI_EXTRACTION:
            if (normalized_confirmed_at is not None) != all(
                issue.resolved for issue in normalized_review_issues
            ):
                raise ValueError("AI extraction confirmation state is inconsistent")
        elif normalized_confirmed_at is not None or any(
            issue.resolved for issue in normalized_review_issues
        ):
            raise ValueError("AI reimport review state must remain unresolved")
        if not validate_trade_plan(
            plan,
            available_market_evidence=set(),
            review_issues=normalized_review_issues,
        ).can_save:
            raise PlanSaveBlockedError("Plan has save-blocking validation errors")

        created_at = _aware_now(self._clock).isoformat()
        source = PlanSource(
            id=self._id_factory(),
            source_text=source_text,
            source_hash=sha256(source_text.encode("utf-8")).hexdigest(),
            created_at=created_at,
        )
        version = PlanVersion(
            id=self._id_factory(),
            plan_id=plan.plan_id,
            version=plan.version,
            symbol=plan.symbol,
            plan_hash=plan_sha256(plan),
            status=PlanVersionStatus.DRAFT,
            payload_json=dump_plan_json(plan),
            source_id=source.id,
            revision=0,
            created_at=created_at,
        )
        review = PlanVersionReview(
            plan_version_id=version.id,
            review_issues_json=_plan_review_issues_json(normalized_review_issues),
        )
        provenance = PlanReviewProvenance(
            plan_version_id=version.id,
            origin=normalized_origin.value,
            extraction_id=normalized_extraction_id,
            source_hash=source.source_hash,
            draft_hash=version.plan_hash,
            confirmed_at=(
                None if normalized_confirmed_at is None else normalized_confirmed_at.isoformat()
            ),
        )
        try:
            with self._session.begin_nested():
                self._session.add_all((source, version))
                self._session.execute(
                    sqlite_insert(PlanActivationState)
                    .values(
                        symbol=plan.symbol,
                        plan_version_id=None,
                        revision=0,
                        changed_at=created_at,
                    )
                    .on_conflict_do_nothing(index_elements=[PlanActivationState.symbol])
                )
                self._session.flush()
                self._session.add_all((review, provenance))
                self._session.flush()
        except IntegrityError:
            existing = self.get_version(plan.plan_id, plan.version)
            if existing is not None:
                raise DuplicatePlanVersionError(plan.plan_id, plan.version) from None
            raise RepositoryError("Plan version could not be persisted") from None
        self._append_draft_audit(version)
        return _plan_version_record(version)

    def get_version(self, plan_id: str, version: int) -> PlanVersionRecord | None:
        model = self._session.scalar(
            select(PlanVersion).where(
                PlanVersion.plan_id == plan_id,
                PlanVersion.version == version,
            )
        )
        return None if model is None else _plan_version_record(model)

    def next_version(self, plan_id: str) -> int:
        """Return the next append-only version for one validated plan identity."""

        normalized_plan_id = _plan_id(plan_id)
        latest = self._session.scalar(
            select(func.max(PlanVersion.version)).where(PlanVersion.plan_id == normalized_plan_id)
        )
        if latest is None:
            return 1
        if type(latest) is not int or not 1 <= latest < 9_223_372_036_854_775_807:
            raise RepositoryError("Stored plan version sequence is invalid")
        return latest + 1

    def get_version_details(self, version_id: str) -> PlanVersionDetailsRecord | None:
        normalized_id = _uuid_identifier(version_id, "version_id")
        row = self._session.execute(
            select(
                PlanVersion,
                PlanSource,
                PlanVersionReview,
                PlanReviewProvenance,
                StoredPlanExtractionReview,
            )
            .outerjoin(PlanSource, PlanSource.id == PlanVersion.source_id)
            .outerjoin(
                PlanVersionReview,
                PlanVersionReview.plan_version_id == PlanVersion.id,
            )
            .outerjoin(
                PlanReviewProvenance,
                PlanReviewProvenance.plan_version_id == PlanVersion.id,
            )
            .outerjoin(
                StoredPlanExtractionReview,
                StoredPlanExtractionReview.id == PlanReviewProvenance.extraction_id,
            )
            .where(PlanVersion.id == normalized_id)
        ).one_or_none()
        if row is None:
            return None
        if row[1] is None or row[2] is None or row[3] is None:
            raise RepositoryError("Stored plan version details are invalid")
        return _plan_version_details_record(row[0], row[1], row[2], row[3], row[4])

    def list_version_details(
        self,
        *,
        offset: int,
        limit: int,
        symbol: str | None = None,
        status: str | PlanVersionStatus | None = None,
    ) -> tuple[tuple[PlanVersionDetailsRecord, ...], int]:
        normalized_offset = _nonnegative_integer(offset, "offset")
        normalized_limit = _positive_integer(limit, "limit")
        if normalized_offset > self._MAX_READ_ROWS:
            raise ValueError("offset exceeds the plan-version read limit")
        if normalized_limit > self._MAX_PAGE_LIMIT:
            raise ValueError("limit exceeds the plan-version page limit")
        filters = []
        if symbol is not None:
            filters.append(PlanVersion.symbol == _symbol(symbol))
        if status is not None:
            try:
                normalized_status = PlanVersionStatus(status)
            except TypeError, ValueError:
                raise ValueError("status must be DRAFT, ACTIVE, or SUPERSEDED") from None
            filters.append(PlanVersion.status == normalized_status)

        total = self._session.scalar(select(func.count()).select_from(PlanVersion).where(*filters))
        if type(total) is not int or not 0 <= total <= self._MAX_READ_ROWS:
            raise RepositoryError("Plan-version collection exceeds its read limit")
        rows = self._session.execute(
            select(
                PlanVersion,
                PlanSource,
                PlanVersionReview,
                PlanReviewProvenance,
                StoredPlanExtractionReview,
            )
            .outerjoin(PlanSource, PlanSource.id == PlanVersion.source_id)
            .outerjoin(
                PlanVersionReview,
                PlanVersionReview.plan_version_id == PlanVersion.id,
            )
            .outerjoin(
                PlanReviewProvenance,
                PlanReviewProvenance.plan_version_id == PlanVersion.id,
            )
            .outerjoin(
                StoredPlanExtractionReview,
                StoredPlanExtractionReview.id == PlanReviewProvenance.extraction_id,
            )
            .where(*filters)
            .order_by(PlanVersion.created_at.desc(), PlanVersion.id.desc())
            .offset(normalized_offset)
            .limit(normalized_limit)
        ).all()
        details: list[PlanVersionDetailsRecord] = []
        for row in rows:
            if row[1] is None or row[2] is None or row[3] is None:
                raise RepositoryError("Stored plan version details are invalid")
            details.append(_plan_version_details_record(row[0], row[1], row[2], row[3], row[4]))
        return tuple(details), total

    def get_activation_state(self, symbol: str) -> PlanActivationStateRecord | None:
        normalized_symbol = _symbol(symbol)
        record = self._get_activation_state(normalized_symbol)
        active = self.get_active(normalized_symbol)
        self._consistent_activation_revision(state=record, active=active)
        return record

    def _get_activation_state(
        self,
        symbol: str,
        *,
        require_active_version: bool = True,
    ) -> PlanActivationStateRecord | None:
        model = self._session.get(PlanActivationState, symbol)
        if model is None:
            return None
        record = _plan_activation_state_record(model)
        if record.plan_version_id is not None:
            version = self._session.get(PlanVersion, record.plan_version_id)
            if (
                version is None
                or version.symbol != record.symbol
                or (require_active_version and version.status != PlanVersionStatus.ACTIVE)
            ):
                raise RepositoryError("Stored plan activation state is invalid")
        return record

    def get_active(self, symbol: str) -> ActivePlanRecord | None:
        model = self._session.get(ActivePlan, symbol)
        return None if model is None else _active_plan_record(model)

    def activate(
        self,
        plan: TradePlan,
        *,
        expected_revision: int,
        validation: PlanValidationResult,
    ) -> ActivePlanRecord:
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        if not isinstance(validation, PlanValidationResult):
            raise TypeError("validation must be a PlanValidationResult")
        if not validation.can_activate:
            raise PlanActivationBlockedError("Plan is not ready for activation")

        try:
            with self._session.begin_nested():
                self._lock_plan_activation_writer(plan.symbol)
                target = self.get_version(plan.plan_id, plan.version)
                if target is None or target.plan_hash != plan_sha256(plan):
                    raise PlanVersionNotFoundError("Plan version was not found")
                unresolved_close = self._session.scalar(
                    select(PendingOfficialClose).where(PendingOfficialClose.symbol == plan.symbol)
                )
                if unresolved_close is not None and (
                    unresolved_close.plan_hash != target.plan_hash
                    or unresolved_close.formula_version != plan.monitoring.indicator_formula_version
                ):
                    raise PlanActivationBlockedError(
                        "Another plan has an unresolved official close"
                    )

                before = self.get_active(plan.symbol)
                before_state = self.get_activation_state(plan.symbol)
                current_revision = self._consistent_activation_revision(
                    state=before_state,
                    active=before,
                )
                if expected_revision != current_revision:
                    raise RevisionConflictError(current_revision)

                activated_at = _aware_now(self._clock)
                state_statement = sqlite_insert(PlanActivationState).values(
                    symbol=plan.symbol,
                    plan_version_id=target.id,
                    changed_at=activated_at.isoformat(),
                    revision=1,
                )
                state_statement = state_statement.on_conflict_do_update(
                    index_elements=[PlanActivationState.symbol],
                    set_={
                        "plan_version_id": target.id,
                        "changed_at": activated_at.isoformat(),
                        "revision": PlanActivationState.revision + 1,
                    },
                    where=PlanActivationState.revision == expected_revision,
                )
                state_result = self._session.execute(state_statement)
                if state_result.rowcount != 1:
                    self._session.expire_all()
                    current_state = self._get_activation_state(plan.symbol)
                    raise RevisionConflictError(
                        0 if current_state is None else current_state.revision
                    )
                self._session.expire_all()
                changed_state = self._get_activation_state(
                    plan.symbol,
                    require_active_version=False,
                )
                if (
                    changed_state is None
                    or changed_state.plan_version_id != target.id
                    or changed_state.revision != expected_revision + 1
                ):
                    raise RepositoryError("Activated plan state could not be reloaded")

                active_statement = sqlite_insert(ActivePlan).values(
                    symbol=plan.symbol,
                    plan_version_id=target.id,
                    activated_at=activated_at.isoformat(),
                    revision=changed_state.revision,
                )
                active_statement = active_statement.on_conflict_do_update(
                    index_elements=[ActivePlan.symbol],
                    set_={
                        "plan_version_id": target.id,
                        "activated_at": activated_at.isoformat(),
                        "revision": changed_state.revision,
                    },
                    where=ActivePlan.revision == expected_revision,
                )
                active_result = self._session.execute(active_statement)
                if active_result.rowcount != 1:
                    raise RepositoryError("Active plan pointer could not be synchronized")

                if before is not None and before.plan_version_id != target.id:
                    self._session.execute(
                        update(PlanVersion)
                        .where(PlanVersion.id == before.plan_version_id)
                        .values(
                            status=PlanVersionStatus.SUPERSEDED,
                            revision=PlanVersion.revision + 1,
                        )
                    )
                self._session.execute(
                    update(PlanVersion)
                    .where(PlanVersion.id == target.id)
                    .values(
                        status=PlanVersionStatus.ACTIVE,
                        revision=PlanVersion.revision + 1,
                    )
                )
                self._session.flush()
                self._session.expire_all()
                after = self.get_active(plan.symbol)
                if after is None:
                    raise RepositoryError("Activated plan could not be reloaded")
                self._append_activation_audit(
                    before=before,
                    before_state=before_state,
                    after=after,
                )
                self._events.append(
                    MonitorEventDraft(
                        event_id=monitor_event_id(
                            MonitorEventType.PLAN_ACTIVATED,
                            after.symbol,
                            str(after.revision),
                        ),
                        event_type=MonitorEventType.PLAN_ACTIVATED,
                        aggregate_id=after.symbol,
                        payload=MonitorEventPayload(
                            entity_id=after.plan_version_id,
                            symbol=after.symbol,
                            revision=after.revision,
                        ),
                        occurred_at=after.activated_at,
                    )
                )
        except IntegrityError:
            raise RepositoryError("Plan activation could not be persisted") from None
        return after

    def deactivate(
        self,
        symbol: str,
        *,
        expected_revision: int,
    ) -> PlanActivationStateRecord:
        normalized_symbol = _symbol(symbol)
        normalized_revision = _nonnegative_integer(expected_revision, "expected_revision")
        try:
            with self._session.begin_nested():
                self._lock_plan_activation_writer(normalized_symbol)
                before = self.get_active(normalized_symbol)
                before_state = self.get_activation_state(normalized_symbol)
                current_revision = self._consistent_activation_revision(
                    state=before_state,
                    active=before,
                )
                if normalized_revision != current_revision:
                    raise RevisionConflictError(current_revision)
                if before is None or before_state is None:
                    raise PlanVersionNotFoundError("Active plan was not found")
                unresolved_close = self._session.scalar(
                    select(PendingOfficialClose).where(
                        PendingOfficialClose.symbol == normalized_symbol
                    )
                )
                if unresolved_close is not None:
                    raise PlanActivationBlockedError("Plan has an unresolved official close")

                changed_at = _aware_now(self._clock)
                state_result = self._session.execute(
                    update(PlanActivationState)
                    .where(
                        PlanActivationState.symbol == normalized_symbol,
                        PlanActivationState.plan_version_id == before.plan_version_id,
                        PlanActivationState.revision == normalized_revision,
                    )
                    .values(
                        plan_version_id=None,
                        revision=PlanActivationState.revision + 1,
                        changed_at=changed_at.isoformat(),
                    )
                    .execution_options(synchronize_session=False)
                )
                if state_result.rowcount != 1:
                    self._session.expire_all()
                    current_state = self._get_activation_state(normalized_symbol)
                    raise RevisionConflictError(
                        0 if current_state is None else current_state.revision
                    )

                active_result = self._session.execute(
                    delete(ActivePlan).where(
                        ActivePlan.symbol == normalized_symbol,
                        ActivePlan.plan_version_id == before.plan_version_id,
                        ActivePlan.revision == normalized_revision,
                    )
                )
                if active_result.rowcount != 1:
                    raise RepositoryError("Active plan pointer could not be removed")
                version_result = self._session.execute(
                    update(PlanVersion)
                    .where(
                        PlanVersion.id == before.plan_version_id,
                        PlanVersion.status == PlanVersionStatus.ACTIVE,
                    )
                    .values(
                        status=PlanVersionStatus.SUPERSEDED,
                        revision=PlanVersion.revision + 1,
                    )
                )
                if version_result.rowcount != 1:
                    raise RepositoryError("Active plan version could not be superseded")

                self._session.flush()
                self._session.expire_all()
                after = self.get_activation_state(normalized_symbol)
                if (
                    after is None
                    or after.plan_version_id is not None
                    or after.revision != normalized_revision + 1
                ):
                    raise RepositoryError("Deactivated plan state could not be reloaded")
                self._append_deactivation_audit(before=before, after=after)
                self._events.append(
                    MonitorEventDraft(
                        event_id=monitor_event_id(
                            MonitorEventType.PLAN_DEACTIVATED,
                            after.symbol,
                            str(after.revision),
                        ),
                        event_type=MonitorEventType.PLAN_DEACTIVATED,
                        aggregate_id=after.symbol,
                        payload=MonitorEventPayload(
                            entity_id=after.symbol,
                            symbol=after.symbol,
                            revision=after.revision,
                        ),
                        occurred_at=after.changed_at,
                    )
                )
        except IntegrityError:
            raise RepositoryError("Plan deactivation could not be persisted") from None
        return after

    def _lock_plan_activation_writer(self, symbol: str) -> None:
        self._session.execute(
            update(PlanActivationState)
            .where(PlanActivationState.symbol == symbol)
            .values(revision=PlanActivationState.revision)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def _consistent_activation_revision(
        *,
        state: PlanActivationStateRecord | None,
        active: ActivePlanRecord | None,
    ) -> int:
        if state is None:
            if active is not None:
                raise RepositoryError("Stored plan activation state is invalid")
            return 0
        if active is None:
            if state.plan_version_id is not None:
                raise RepositoryError("Stored plan activation state is invalid")
            return state.revision
        if (
            state.plan_version_id != active.plan_version_id
            or state.revision != active.revision
            or state.changed_at != active.activated_at
        ):
            raise RepositoryError("Stored plan activation state is invalid")
        return state.revision

    def _append_activation_audit(
        self,
        *,
        before: ActivePlanRecord | None,
        before_state: PlanActivationStateRecord | None,
        after: ActivePlanRecord,
    ) -> None:
        details = {
            "planVersionId": after.plan_version_id,
            "revision": after.revision,
            "symbol": after.symbol,
        }
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action="PLAN_ACTIVATED",
                entity_type="ACTIVE_PLAN",
                entity_id=after.symbol,
                before_hash=(
                    _active_plan_hash(before)
                    if before is not None
                    else (
                        _plan_activation_state_hash(before_state)
                        if before_state is not None and before_state.revision > 0
                        else None
                    )
                ),
                after_hash=_active_plan_hash(after),
                details_json=_canonical_json(details),
                created_at=after.activated_at.isoformat(),
            )
        )
        self._session.flush()

    def _append_deactivation_audit(
        self,
        *,
        before: ActivePlanRecord,
        after: PlanActivationStateRecord,
    ) -> None:
        details = {
            "planVersionId": before.plan_version_id,
            "revision": after.revision,
            "symbol": after.symbol,
        }
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action="PLAN_DEACTIVATED",
                entity_type="ACTIVE_PLAN",
                entity_id=after.symbol,
                before_hash=_active_plan_hash(before),
                after_hash=_plan_activation_state_hash(after),
                details_json=_canonical_json(details),
                created_at=after.changed_at.isoformat(),
            )
        )
        self._session.flush()

    def _append_draft_audit(self, version: PlanVersion) -> None:
        details = {
            "planId": version.plan_id,
            "planVersionId": version.id,
            "symbol": version.symbol,
            "version": version.version,
        }
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action="PLAN_DRAFT_SAVED",
                entity_type="PLAN_VERSION",
                entity_id=version.id,
                before_hash=None,
                after_hash=version.plan_hash,
                details_json=_canonical_json(details),
                created_at=version.created_at,
            )
        )
        self._session.flush()


class PositionRepository:
    """Persist explicit manual buys and T+1-safe lot reductions."""

    _MAX_PAGE_LIMIT = 100
    _MAX_READ_ROWS = 10_000

    def __init__(
        self,
        session: Session,
        *,
        clock: Clock,
        id_factory: IdFactory,
        events: MonitorEventLog,
    ) -> None:
        self._session = session
        self._clock = clock
        self._id_factory = id_factory
        self._events = events

    def record_buy(
        self,
        *,
        symbol: str,
        bucket: str | PositionBucket,
        quantity: int,
        acquired_trade_date: date,
        cost_fen: int,
        board_lot: int,
        max_position_qty: int,
        related_alert_id: str | None = None,
    ) -> PositionLotRecord:
        normalized_symbol = _symbol(symbol)
        normalized_bucket = _position_bucket(bucket)
        normalized_quantity = _positive_integer(quantity, "quantity")
        normalized_board_lot = _positive_integer(board_lot, "board_lot")
        normalized_maximum = _positive_integer(max_position_qty, "max_position_qty")
        normalized_cost = _positive_integer(cost_fen, "cost_fen")
        normalized_date = _calendar_date(acquired_trade_date, "acquired_trade_date")
        if normalized_quantity % normalized_board_lot != 0:
            raise BoardLotViolationError("Buy quantity must be a whole board lot")
        if normalized_maximum % normalized_board_lot != 0:
            raise BoardLotViolationError("Maximum position must be a whole board lot")
        if related_alert_id is not None:
            _bounded_text(related_alert_id, "related_alert_id", maximum=36)

        # A no-op write serializes SQLite writers before the maximum-position read,
        # including when this symbol does not yet have a lot.
        self._session.execute(
            update(PositionLot)
            .where(PositionLot.symbol == normalized_symbol)
            .values(remaining_qty=PositionLot.remaining_qty)
            .execution_options(synchronize_session=False)
        )
        open_quantity = sum(
            self._session.scalars(
                select(PositionLot.remaining_qty).where(
                    PositionLot.symbol == normalized_symbol,
                    PositionLot.remaining_qty > 0,
                )
            ).all()
        )
        if open_quantity + normalized_quantity > normalized_maximum:
            raise MaxPositionExceededError("Buy would exceed the maximum position")

        model = PositionLot(
            id=self._id_factory(),
            symbol=normalized_symbol,
            bucket=normalized_bucket,
            quantity=normalized_quantity,
            remaining_qty=normalized_quantity,
            acquired_trade_date=normalized_date,
            cost_fen=normalized_cost,
            related_alert_id=related_alert_id,
            closed_at=None,
        )
        try:
            with self._session.begin_nested():
                self._session.add(model)
                self._session.flush()
        except IntegrityError:
            raise RepositoryError("Position lot could not be persisted") from None
        record = _position_lot_record(model)
        occurred_at = self._append_audit(
            action="POSITION_BUY_RECORDED",
            before=None,
            after=record,
            quantity=normalized_quantity,
        )
        self._append_position_event(record, occurred_at=occurred_at)
        return record

    def get_lot(self, lot_id: str) -> PositionLotRecord:
        normalized_id = _bounded_text(lot_id, "lot_id", maximum=36)
        model = self._session.get(PositionLot, normalized_id)
        if model is None:
            raise PositionLotNotFoundError("Position lot was not found")
        return _position_lot_record(model)

    def list_open_lots(self, symbol: str) -> tuple[PositionLotRecord, ...]:
        models = self._session.scalars(
            select(PositionLot)
            .where(
                PositionLot.symbol == _symbol(symbol),
                PositionLot.remaining_qty > 0,
            )
            .order_by(PositionLot.acquired_trade_date, PositionLot.id)
        ).all()
        return tuple(_position_lot_record(model) for model in models)

    def list_lots(
        self,
        symbol: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[tuple[PositionLotRecord, ...], int]:
        """Return a bounded stable page including exhausted lots for reconciliation."""

        normalized_symbol = _symbol(symbol)
        normalized_offset = _nonnegative_integer(offset, "offset")
        normalized_limit = _positive_integer(limit, "limit")
        if normalized_offset > self._MAX_READ_ROWS:
            raise ValueError("offset exceeds the position-lot read limit")
        if normalized_limit > self._MAX_PAGE_LIMIT:
            raise ValueError("limit exceeds the position-lot page limit")
        total = self._session.scalar(
            select(func.count())
            .select_from(PositionLot)
            .where(PositionLot.symbol == normalized_symbol)
        )
        if type(total) is not int or not 0 <= total <= self._MAX_READ_ROWS:
            raise RepositoryError("Position-lot collection exceeds its read limit")
        models = self._session.scalars(
            select(PositionLot)
            .where(PositionLot.symbol == normalized_symbol)
            .order_by(PositionLot.acquired_trade_date, PositionLot.id)
            .offset(normalized_offset)
            .limit(normalized_limit)
        ).all()
        return tuple(_position_lot_record(model) for model in models), total

    def sellable_quantity(
        self,
        symbol: str,
        *,
        trade_date: date,
        bucket: str | PositionBucket | None = None,
    ) -> int:
        statement = select(PositionLot.remaining_qty).where(
            PositionLot.symbol == _symbol(symbol),
            PositionLot.remaining_qty > 0,
            PositionLot.acquired_trade_date < _calendar_date(trade_date, "trade_date"),
        )
        if bucket is not None:
            statement = statement.where(PositionLot.bucket == _position_bucket(bucket))
        return sum(self._session.scalars(statement).all())

    def reduce_lot(
        self,
        lot_id: str,
        *,
        quantity: int,
        trade_date: date,
        expected_revision: int | None = None,
        board_lot: int = 100,
    ) -> PositionLotRecord:
        normalized_id = _bounded_text(lot_id, "lot_id", maximum=36)
        normalized_quantity = _positive_integer(quantity, "quantity")
        normalized_date = _calendar_date(trade_date, "trade_date")
        normalized_board_lot = _positive_integer(board_lot, "board_lot")
        normalized_revision = (
            None
            if expected_revision is None
            else _nonnegative_integer(expected_revision, "expected_revision")
        )
        if normalized_quantity % normalized_board_lot != 0:
            raise BoardLotViolationError("Reduction quantity must be a whole board lot")
        self._session.execute(
            update(PositionLot)
            .where(PositionLot.id == normalized_id)
            .values(remaining_qty=PositionLot.remaining_qty)
            .execution_options(synchronize_session=False)
        )
        self._session.expire_all()
        model = self._session.get(PositionLot, normalized_id)
        if model is None:
            raise PositionLotNotFoundError("Position lot was not found")
        before = _position_lot_record(model)
        reduced_quantity = model.quantity - model.remaining_qty
        if reduced_quantity % normalized_board_lot != 0:
            raise RepositoryError("Stored position lot has an invalid revision")
        current_revision = reduced_quantity // normalized_board_lot
        if normalized_revision is not None and normalized_revision != current_revision:
            raise RevisionConflictError(current_revision)
        if model.acquired_trade_date >= normalized_date:
            raise PositionT1LockedError("Position lot is not sellable on this trade date")
        if normalized_quantity > model.remaining_qty:
            raise PositionReductionError("Reduction exceeds the lot's remaining quantity")

        model.remaining_qty -= normalized_quantity
        if model.remaining_qty == 0:
            model.closed_at = _aware_now(self._clock).isoformat()
        self._session.flush()
        after = _position_lot_record(model)
        occurred_at = self._append_audit(
            action="POSITION_REDUCTION_RECORDED",
            before=before,
            after=after,
            quantity=normalized_quantity,
        )
        self._append_position_event(after, occurred_at=occurred_at)
        return after

    def _append_audit(
        self,
        *,
        action: str,
        before: PositionLotRecord | None,
        after: PositionLotRecord,
        quantity: int,
    ) -> datetime:
        occurred_at = _aware_now(self._clock)
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action=action,
                entity_type="POSITION_LOT",
                entity_id=after.id,
                before_hash=None if before is None else _position_lot_hash(before),
                after_hash=_position_lot_hash(after),
                details_json=_canonical_json(
                    {
                        "bucket": after.bucket,
                        "quantity": quantity,
                        "symbol": after.symbol,
                    }
                ),
                created_at=occurred_at.isoformat(),
            )
        )
        self._session.flush()
        return occurred_at

    def _append_position_event(
        self,
        position: PositionLotRecord,
        *,
        occurred_at: datetime,
    ) -> None:
        status = "CLOSED" if position.remaining_qty == 0 else "OPEN"
        self._events.append(
            MonitorEventDraft(
                event_id=monitor_event_id(
                    MonitorEventType.POSITION_UPDATED,
                    position.id,
                    str(position.remaining_qty),
                ),
                event_type=MonitorEventType.POSITION_UPDATED,
                aggregate_id=position.id,
                payload=MonitorEventPayload(
                    entity_id=position.id,
                    symbol=position.symbol,
                    status=status,
                ),
                occurred_at=occurred_at,
            )
        )


class EpisodeRepository:
    """Persist replay-stable low-zone episodes without schema-only revisions."""

    def __init__(self, session: Session, *, clock: Clock, id_factory: IdFactory) -> None:
        self._session = session
        self._clock = clock
        self._id_factory = id_factory

    def start(
        self,
        *,
        episode_id: str,
        plan_hash: str,
        symbol: str,
        zone: str,
        started_at: datetime,
        episode_low_fen: int,
        last_processed_bucket_end: datetime,
    ) -> EpisodeRecord:
        normalized_id = _bounded_text(episode_id, "episode_id", maximum=36)
        normalized_hash = _sha256_hash(plan_hash, "plan_hash")
        normalized_symbol = _symbol(symbol)
        normalized_zone = _identifier(zone, "zone", maximum=64)
        normalized_started_at = _aware_datetime(started_at, "started_at")
        normalized_low = _positive_integer(episode_low_fen, "episode_low_fen")
        normalized_cursor = _episode_cursor(last_processed_bucket_end)
        if normalized_cursor < five_minute_bucket_end(normalized_started_at):
            raise ValueError("last_processed_bucket_end cannot precede the touch bucket")
        statement = sqlite_insert(ZoneEpisode).values(
            id=normalized_id,
            plan_hash=normalized_hash,
            symbol=normalized_symbol,
            zone=normalized_zone,
            started_at=normalized_started_at.isoformat(),
            episode_low_fen=normalized_low,
            bars_since_low=0,
            status="ACTIVE",
            alerted_signal=None,
            last_processed_bucket_end=normalized_cursor.isoformat(),
        )
        result = self._session.execute(
            statement.on_conflict_do_nothing(index_elements=[ZoneEpisode.id])
        )
        self._session.flush()
        self._session.expire_all()
        model = self._session.get(ZoneEpisode, normalized_id)
        if model is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Zone episode could not be reloaded")
        record = _episode_record(model)
        if result.rowcount != 1:
            expected_identity = (
                normalized_hash,
                normalized_symbol,
                normalized_zone,
                normalized_started_at,
            )
            actual_identity = (
                record.plan_hash,
                record.symbol,
                record.zone,
                record.started_at,
            )
            if actual_identity != expected_identity:
                raise EpisodeIdentityConflictError(
                    "Episode identifier is bound to another identity"
                )
            candidate_initial = EpisodeRecord(
                id=normalized_id,
                plan_hash=normalized_hash,
                symbol=normalized_symbol,
                zone=normalized_zone,
                started_at=normalized_started_at,
                episode_low_fen=normalized_low,
                bars_since_low=0,
                status="ACTIVE",
                alerted_signal=None,
                last_processed_bucket_end=normalized_cursor,
            )
            initial_hashes = tuple(
                self._session.scalars(
                    select(AuditLog.after_hash)
                    .where(
                        AuditLog.entity_type == "ZONE_EPISODE",
                        AuditLog.entity_id == normalized_id,
                        AuditLog.action == "ZONE_EPISODE_STARTED",
                    )
                    .limit(2)
                )
            )
            if len(initial_hashes) != 1 or initial_hashes[0] != _episode_hash(candidate_initial):
                raise EpisodeIdentityConflictError(
                    "Episode identifier has conflicting initial state"
                )
            return record
        self._append_audit(action="ZONE_EPISODE_STARTED", before=None, after=record)
        return record

    def get(self, episode_id: str) -> EpisodeRecord:
        normalized_id = _bounded_text(episode_id, "episode_id", maximum=36)
        model = self._session.get(ZoneEpisode, normalized_id)
        if model is None:
            raise EpisodeNotFoundError("Zone episode was not found")
        return _episode_record(model)

    def revise(
        self,
        episode_id: str,
        *,
        episode_low_fen: int,
        bars_since_low: int,
        status: str,
        alerted_signal: str | None,
        last_processed_bucket_end: datetime,
    ) -> EpisodeRecord:
        normalized_id = _bounded_text(episode_id, "episode_id", maximum=36)
        normalized_low = _positive_integer(episode_low_fen, "episode_low_fen")
        normalized_bars = _nonnegative_integer(bars_since_low, "bars_since_low")
        normalized_status = _identifier(status, "status", maximum=32)
        normalized_signal = (
            None
            if alerted_signal is None
            else _identifier(alerted_signal, "alerted_signal", maximum=64)
        )
        normalized_cursor = _episode_cursor(last_processed_bucket_end)
        self._session.execute(
            update(ZoneEpisode)
            .where(ZoneEpisode.id == normalized_id)
            .values(bars_since_low=ZoneEpisode.bars_since_low)
            .execution_options(synchronize_session=False)
        )
        model = self._session.get(ZoneEpisode, normalized_id)
        if model is None:
            raise EpisodeNotFoundError("Zone episode was not found")
        before = _episode_record(model)
        if normalized_cursor < before.last_processed_bucket_end:
            raise EpisodeTransitionError("Episode cursor cannot move backwards")
        incoming_state = (
            normalized_low,
            normalized_bars,
            normalized_status,
            normalized_signal,
        )
        current_state = (
            before.episode_low_fen,
            before.bars_since_low,
            before.status,
            before.alerted_signal,
        )
        if normalized_cursor == before.last_processed_bucket_end:
            if incoming_state == current_state:
                return before
            raise EpisodeTransitionError("Episode state cannot change at the same cursor")
        _validate_episode_lifecycle_transition(
            before=before,
            status=normalized_status,
            alerted_signal=normalized_signal,
        )
        if normalized_low > before.episode_low_fen:
            raise EpisodeTransitionError("Episode low cannot increase")
        if normalized_low < before.episode_low_fen and normalized_bars != 0:
            raise EpisodeTransitionError("A new episode low must reset bar progress")
        if normalized_low == before.episode_low_fen and normalized_bars < before.bars_since_low:
            raise EpisodeTransitionError("Episode bar progress cannot move backwards")
        model.episode_low_fen = normalized_low
        model.bars_since_low = normalized_bars
        model.status = normalized_status
        model.alerted_signal = normalized_signal
        model.last_processed_bucket_end = normalized_cursor.isoformat()
        self._session.flush()
        after = _episode_record(model)
        self._append_audit(action="ZONE_EPISODE_REVISED", before=before, after=after)
        return after

    def _append_audit(
        self,
        *,
        action: str,
        before: EpisodeRecord | None,
        after: EpisodeRecord,
    ) -> None:
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action=action,
                entity_type="ZONE_EPISODE",
                entity_id=after.id,
                before_hash=None if before is None else _episode_hash(before),
                after_hash=_episode_hash(after),
                details_json=_canonical_json(
                    {
                        "barsSinceLow": after.bars_since_low,
                        "lastProcessedBucketEnd": after.last_processed_bucket_end.isoformat(),
                        "status": after.status,
                        "symbol": after.symbol,
                        "zone": after.zone,
                    }
                ),
                created_at=_aware_now(self._clock).isoformat(),
            )
        )
        self._session.flush()


class RiskRepository:
    """Persist official-close risk transitions with optimistic revisions."""

    def __init__(self, session: Session, *, clock: Clock, id_factory: IdFactory) -> None:
        self._session = session
        self._clock = clock
        self._id_factory = id_factory

    def get(self, symbol: str) -> RiskStateRecord | None:
        model = self._session.get(RiskState, _symbol(symbol))
        return None if model is None else _risk_state_record(model)

    def upsert(
        self,
        *,
        symbol: str,
        plan_hash: str,
        status: str,
        breach_trade_date: date | None,
        prior_close_fen: int,
        expected_revision: int,
    ) -> RiskStateRecord:
        normalized_symbol = _symbol(symbol)
        normalized_hash = _sha256_hash(plan_hash, "plan_hash")
        normalized_status = _identifier(status, "status", maximum=32)
        normalized_close = _positive_integer(prior_close_fen, "prior_close_fen")
        normalized_revision = _nonnegative_integer(expected_revision, "expected_revision")
        if breach_trade_date is not None:
            normalized_breach_date = _calendar_date(breach_trade_date, "breach_trade_date")
        else:
            normalized_breach_date = None
        if normalized_status == "CLEAR" and normalized_breach_date is not None:
            raise ValueError("CLEAR risk state cannot retain a breach trade date")
        if normalized_status != "CLEAR" and normalized_breach_date is None:
            raise ValueError("A non-clear risk state requires a breach trade date")

        self._session.execute(
            update(RiskState)
            .where(RiskState.symbol == normalized_symbol)
            .values(revision=RiskState.revision)
            .execution_options(synchronize_session=False)
        )
        before = self.get(normalized_symbol)
        if before is None and normalized_revision != 0:
            raise RevisionConflictError(0)
        updated_at = _aware_now(self._clock)
        statement = sqlite_insert(RiskState).values(
            symbol=normalized_symbol,
            plan_hash=normalized_hash,
            status=normalized_status,
            breach_trade_date=normalized_breach_date,
            prior_close_fen=normalized_close,
            revision=1,
            updated_at=updated_at.isoformat(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[RiskState.symbol],
            set_={
                "plan_hash": normalized_hash,
                "status": normalized_status,
                "breach_trade_date": normalized_breach_date,
                "prior_close_fen": normalized_close,
                "revision": RiskState.revision + 1,
                "updated_at": updated_at.isoformat(),
            },
            where=RiskState.revision == normalized_revision,
        )
        result = self._session.execute(statement)
        if result.rowcount != 1:
            self._session.expire_all()
            current = self.get(normalized_symbol)
            raise RevisionConflictError(0 if current is None else current.revision)
        self._session.flush()
        self._session.expire_all()
        after = self.get(normalized_symbol)
        if after is None:  # pragma: no cover - protected by successful upsert
            raise RepositoryError("Risk state could not be reloaded")
        self._append_audit(before=before, after=after)
        return after

    def _append_audit(
        self,
        *,
        before: RiskStateRecord | None,
        after: RiskStateRecord,
    ) -> None:
        self._session.add(
            AuditLog(
                id=self._id_factory(),
                action="RISK_STATE_UPDATED",
                entity_type="RISK_STATE",
                entity_id=after.symbol,
                before_hash=None if before is None else _risk_state_hash(before),
                after_hash=_risk_state_hash(after),
                details_json=_canonical_json(
                    {
                        "revision": after.revision,
                        "status": after.status,
                        "symbol": after.symbol,
                    }
                ),
                created_at=after.updated_at.isoformat(),
            )
        )
        self._session.flush()


class EvaluationRepository:
    """Claim complete-bar evaluation identities exactly once."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def has_claim(
        self,
        *,
        plan_hash: str,
        symbol: str,
        evaluation_kind: str | EvaluationKind,
        bucket_end: datetime | None,
        official_trade_date: date | None,
        formula_version: str,
    ) -> bool:
        """Return whether one exact evaluation identity is durably claimed."""

        normalized_kind, target_value = _evaluation_target(
            evaluation_kind=evaluation_kind,
            bucket_end=bucket_end,
            official_trade_date=official_trade_date,
        )
        identity = (
            _sha256_hash(plan_hash, "plan_hash"),
            _symbol(symbol),
            normalized_kind.value,
            target_value,
            _token(formula_version, "formula_version", maximum=32),
        )
        return self._session.get(EvaluationLedger, identity) is not None

    def claim(
        self,
        *,
        plan_hash: str,
        symbol: str,
        evaluation_kind: str | EvaluationKind,
        bucket_end: datetime | None,
        official_trade_date: date | None,
        formula_version: str,
        result_hash: str,
        evaluated_at: datetime,
    ) -> EvaluationClaimRecord:
        normalized_plan_hash = _sha256_hash(plan_hash, "plan_hash")
        normalized_symbol = _symbol(symbol)
        normalized_kind, target_value = _evaluation_target(
            evaluation_kind=evaluation_kind,
            bucket_end=bucket_end,
            official_trade_date=official_trade_date,
        )
        normalized_formula = _token(formula_version, "formula_version", maximum=32)
        normalized_result_hash = _sha256_hash(result_hash, "result_hash")
        normalized_evaluated_at = _canonical_market_datetime(evaluated_at, "evaluated_at")
        identity = (
            normalized_plan_hash,
            normalized_symbol,
            normalized_kind.value,
            target_value,
            normalized_formula,
        )
        statement = sqlite_insert(EvaluationLedger).values(
            plan_hash=identity[0],
            symbol=identity[1],
            evaluation_kind=identity[2],
            target_value=identity[3],
            formula_version=identity[4],
            result_hash=normalized_result_hash,
            evaluated_at=normalized_evaluated_at.isoformat(),
        )
        result = self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=[
                    EvaluationLedger.plan_hash,
                    EvaluationLedger.symbol,
                    EvaluationLedger.evaluation_kind,
                    EvaluationLedger.target_value,
                    EvaluationLedger.formula_version,
                ]
            )
        )
        self._session.flush()
        self._session.expire_all()
        model = self._session.get(EvaluationLedger, identity)
        if model is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Evaluation claim could not be reloaded")
        record = _evaluation_record(model)
        if record.result_hash != normalized_result_hash:
            raise EvaluationIdentityConflictError(
                "Evaluation identity already has another result hash"
            )
        return EvaluationClaimRecord(record=record, created=result.rowcount == 1)


class HealthRepository:
    """Persist provider observations and independently revised symbol health."""

    _MAX_GAP_JSON_BYTES = 64 * 1024

    def __init__(self, session: Session, *, clock: Clock, events: MonitorEventLog) -> None:
        self._session = session
        self._clock = clock
        self._events = events

    def get_provider(self, capability: str) -> ProviderHealthRecord | None:
        model = self._session.get(
            ProviderHealth,
            _token(capability, "capability", maximum=64),
        )
        return None if model is None else _provider_health_record(model)

    def upsert_provider(
        self,
        *,
        capability: str,
        status: str | ProviderCapabilityStatus,
        checked_at: datetime,
        latency_ms: int,
        error_code: str | None,
        next_retry_at: datetime | None,
    ) -> ProviderHealthRecord:
        normalized_capability = _token(capability, "capability", maximum=64)
        normalized_status = _provider_status(status)
        normalized_checked_at = _canonical_market_datetime(checked_at, "checked_at")
        normalized_latency = _nonnegative_integer(latency_ms, "latency_ms")
        normalized_error = (
            None if error_code is None else _identifier(error_code, "error_code", maximum=64)
        )
        normalized_retry = (
            None
            if next_retry_at is None
            else _canonical_market_datetime(next_retry_at, "next_retry_at")
        )
        if normalized_retry is not None and normalized_retry < normalized_checked_at:
            raise ValueError("next_retry_at cannot precede checked_at")

        self._session.execute(
            update(ProviderHealth)
            .where(ProviderHealth.capability == normalized_capability)
            .values(latency_ms=ProviderHealth.latency_ms)
            .execution_options(synchronize_session=False)
        )
        current = self.get_provider(normalized_capability)
        incoming = ProviderHealthRecord(
            capability=normalized_capability,
            status=normalized_status,
            checked_at=normalized_checked_at,
            latency_ms=normalized_latency,
            error_code=normalized_error,
            next_retry_at=normalized_retry,
        )
        if current is not None and current.checked_at > normalized_checked_at:
            return current
        if current is not None and current.checked_at == normalized_checked_at:
            if current == incoming:
                return current
            raise ProviderHealthConflictError("Provider observation time has conflicting facts")

        if current is None:
            self._session.add(
                ProviderHealth(
                    capability=normalized_capability,
                    status=normalized_status,
                    checked_at=normalized_checked_at.isoformat(),
                    latency_ms=normalized_latency,
                    error_code=normalized_error,
                    next_retry_at=(
                        None if normalized_retry is None else normalized_retry.isoformat()
                    ),
                )
            )
        else:
            model = self._session.get(ProviderHealth, normalized_capability)
            if model is None:  # pragma: no cover - protected by writer lock/read
                raise RepositoryError("Provider health could not be reloaded")
            model.status = normalized_status
            model.checked_at = normalized_checked_at.isoformat()
            model.latency_ms = normalized_latency
            model.error_code = normalized_error
            model.next_retry_at = None if normalized_retry is None else normalized_retry.isoformat()
        self._session.flush()
        self._events.append(
            MonitorEventDraft(
                event_id=monitor_event_id(
                    MonitorEventType.SYSTEM_HEALTH_UPDATED,
                    incoming.capability,
                    incoming.checked_at.isoformat(),
                ),
                event_type=MonitorEventType.SYSTEM_HEALTH_UPDATED,
                aggregate_id=incoming.capability,
                payload=MonitorEventPayload(
                    entity_id=incoming.capability,
                    status=incoming.status.value,
                ),
                occurred_at=incoming.checked_at,
            )
        )
        return incoming

    def get_symbol(self, symbol: str) -> SymbolHealthRecord | None:
        model = self._session.get(SymbolHealth, _symbol(symbol))
        return None if model is None else _symbol_health_record(model)

    def upsert_symbol(
        self,
        *,
        symbol: str,
        status: str | SymbolHealthStatus,
        latest_bar_end: datetime | None,
        data_age_seconds: int,
        gaps: object,
        error_streak: int,
        expected_revision: int,
    ) -> SymbolHealthRecord:
        normalized_symbol = _symbol(symbol)
        normalized_status = _symbol_health_status(status)
        normalized_bar_end = (
            None
            if latest_bar_end is None
            else _canonical_market_datetime(latest_bar_end, "latest_bar_end")
        )
        normalized_age = _nonnegative_integer(data_age_seconds, "data_age_seconds")
        normalized_streak = _nonnegative_integer(error_streak, "error_streak")
        normalized_revision = _nonnegative_integer(expected_revision, "expected_revision")
        try:
            gap_json = _canonical_json(gaps)
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError("gaps must contain JSON-compatible values") from error
        if len(gap_json.encode("utf-8")) > self._MAX_GAP_JSON_BYTES:
            raise ValueError("gaps exceed the persisted health size limit")

        self._session.execute(
            update(SymbolHealth)
            .where(SymbolHealth.symbol == normalized_symbol)
            .values(revision=SymbolHealth.revision)
            .execution_options(synchronize_session=False)
        )
        current = self.get_symbol(normalized_symbol)
        if current is None and normalized_revision != 0:
            raise RevisionConflictError(0)
        statement = sqlite_insert(SymbolHealth).values(
            symbol=normalized_symbol,
            status=normalized_status,
            latest_bar_end=(None if normalized_bar_end is None else normalized_bar_end.isoformat()),
            data_age_seconds=normalized_age,
            gap_json=gap_json,
            error_streak=normalized_streak,
            revision=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[SymbolHealth.symbol],
            set_={
                "status": normalized_status,
                "latest_bar_end": (
                    None if normalized_bar_end is None else normalized_bar_end.isoformat()
                ),
                "data_age_seconds": normalized_age,
                "gap_json": gap_json,
                "error_streak": normalized_streak,
                "revision": SymbolHealth.revision + 1,
            },
            where=SymbolHealth.revision == normalized_revision,
        )
        result = self._session.execute(statement)
        if result.rowcount != 1:
            self._session.expire_all()
            current = self.get_symbol(normalized_symbol)
            raise RevisionConflictError(0 if current is None else current.revision)
        self._session.flush()
        self._session.expire_all()
        after = self.get_symbol(normalized_symbol)
        if after is None:  # pragma: no cover - protected by successful upsert
            raise RepositoryError("Symbol health could not be reloaded")
        self._events.append(
            MonitorEventDraft(
                event_id=monitor_event_id(
                    MonitorEventType.SYMBOL_HEALTH_UPDATED,
                    after.symbol,
                    str(after.revision),
                ),
                event_type=MonitorEventType.SYMBOL_HEALTH_UPDATED,
                aggregate_id=after.symbol,
                payload=MonitorEventPayload(
                    entity_id=after.symbol,
                    symbol=after.symbol,
                    revision=after.revision,
                    status=after.status.value,
                ),
                occurred_at=_aware_now(self._clock),
            )
        )
        return after


class MarketHistoryRepository:
    """Persist normalized bar history and one replaceable latest-quote projection."""

    _MAX_BATCH_ROWS = 1_000
    _MAX_READ_ROWS = 10_000

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_minutes(self, bars: Sequence[NormalizedMinuteBar]) -> None:
        """Persist validated minute rows without making arrival order observable."""

        normalized = _normalized_batch(
            bars,
            NormalizedMinuteBar,
            "bars",
            maximum=self._MAX_BATCH_ROWS,
        )
        for bar in normalized:
            persisted = self._upsert_minute(bar)
            self._upsert_latest_quote(persisted)

    def list_minutes(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[NormalizedMinuteBar, ...]:
        normalized_symbol = _symbol(symbol)
        normalized_start, normalized_end = _market_range(start, end)
        statement = (
            select(MinuteBarRow)
            .where(
                MinuteBarRow.symbol == normalized_symbol,
                MinuteBarRow.bar_end >= normalized_start.isoformat(),
                MinuteBarRow.bar_end <= normalized_end.isoformat(),
            )
            .order_by(MinuteBarRow.bar_end)
            .limit(self._MAX_READ_ROWS + 1)
        )
        rows = self._session.scalars(statement).all()
        _require_bounded_read(rows, self._MAX_READ_ROWS)
        return tuple(_minute_value(row) for row in rows)

    def get_latest_quote(self, symbol: str) -> LatestQuoteRecord | None:
        row = self._session.get(LatestQuote, _symbol(symbol))
        return None if row is None else _latest_quote_record(row)

    def upsert_five_minute(
        self,
        *,
        symbol: str,
        bar_end: datetime,
        formula_version: str,
        open_fen: int,
        high_fen: int,
        low_fen: int,
        close_fen: int,
        volume_shares: int,
        amount_yuan: Decimal,
    ) -> FiveMinuteBarRecord:
        normalized_symbol = _symbol(symbol)
        normalized_end = _canonical_market_datetime(bar_end, "bar_end")
        expected_five_minute_ends(normalized_end)
        normalized_formula = _token(formula_version, "formula_version", maximum=32)
        normalized_ohlc = _ohlc_fen(
            open_fen=open_fen,
            high_fen=high_fen,
            low_fen=low_fen,
            close_fen=close_fen,
        )
        normalized_volume = _nonnegative_integer(volume_shares, "volume_shares")
        normalized_amount = _nonnegative_decimal(amount_yuan, "amount_yuan")
        incoming = FiveMinuteBarRecord(
            symbol=normalized_symbol,
            bar_end=normalized_end,
            formula_version=normalized_formula,
            open_fen=normalized_ohlc[0],
            high_fen=normalized_ohlc[1],
            low_fen=normalized_ohlc[2],
            close_fen=normalized_ohlc[3],
            volume_shares=normalized_volume,
            amount_yuan=normalized_amount,
        )
        identity = (
            normalized_symbol,
            normalized_end.isoformat(),
            normalized_formula,
        )
        statement = sqlite_insert(FiveMinuteBarRow).values(
            symbol=identity[0],
            bar_end=identity[1],
            formula_version=identity[2],
            open_fen=incoming.open_fen,
            high_fen=incoming.high_fen,
            low_fen=incoming.low_fen,
            close_fen=incoming.close_fen,
            volume_shares=incoming.volume_shares,
            amount_yuan=str(incoming.amount_yuan),
        )
        self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=[
                    FiveMinuteBarRow.symbol,
                    FiveMinuteBarRow.bar_end,
                    FiveMinuteBarRow.formula_version,
                ]
            )
        )
        self._session.flush()
        self._session.expire_all()
        row = self._session.get(FiveMinuteBarRow, identity)
        if row is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Five-minute bar could not be reloaded")
        persisted = _five_minute_record(row)
        if persisted != incoming:
            raise MarketDataIdentityConflictError(
                "Five-minute identity already has conflicting facts"
            )
        return persisted

    def list_five_minute(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        formula_version: str | None = None,
    ) -> tuple[FiveMinuteBarRecord, ...]:
        normalized_start, normalized_end = _market_range(start, end)
        statement = select(FiveMinuteBarRow).where(
            FiveMinuteBarRow.symbol == _symbol(symbol),
            FiveMinuteBarRow.bar_end >= normalized_start.isoformat(),
            FiveMinuteBarRow.bar_end <= normalized_end.isoformat(),
        )
        if formula_version is not None:
            statement = statement.where(
                FiveMinuteBarRow.formula_version
                == _token(formula_version, "formula_version", maximum=32)
            )
        rows = self._session.scalars(
            statement.order_by(
                FiveMinuteBarRow.bar_end,
                FiveMinuteBarRow.formula_version,
            ).limit(self._MAX_READ_ROWS + 1)
        ).all()
        _require_bounded_read(rows, self._MAX_READ_ROWS)
        return tuple(_five_minute_record(row) for row in rows)

    def upsert_daily_bars(self, bars: Sequence[NormalizedDailyBar]) -> None:
        normalized = _normalized_batch(
            bars,
            NormalizedDailyBar,
            "bars",
            maximum=self._MAX_BATCH_ROWS,
        )
        for bar in normalized:
            self._upsert_daily_bar(bar)

    def list_daily_bars(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
    ) -> tuple[NormalizedDailyBar, ...]:
        normalized_start, normalized_end = _date_range(start, end)
        rows = self._session.scalars(
            select(DailyBarRow)
            .where(
                DailyBarRow.symbol == _symbol(symbol),
                DailyBarRow.trade_date >= normalized_start,
                DailyBarRow.trade_date <= normalized_end,
            )
            .order_by(DailyBarRow.trade_date, DailyBarRow.is_official)
            .limit(self._MAX_READ_ROWS + 1)
        ).all()
        _require_bounded_read(rows, self._MAX_READ_ROWS)
        return tuple(_daily_bar_value(row) for row in rows)

    def _upsert_minute(self, bar: NormalizedMinuteBar) -> NormalizedMinuteBar:
        values = _minute_values(bar)
        statement = sqlite_insert(MinuteBarRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[MinuteBarRow.symbol, MinuteBarRow.bar_end],
            set_={
                "open_fen": values["open_fen"],
                "high_fen": values["high_fen"],
                "low_fen": values["low_fen"],
                "close_fen": values["close_fen"],
                "volume_shares": values["volume_shares"],
                "amount_yuan": values["amount_yuan"],
                "received_at": values["received_at"],
            },
            where=MinuteBarRow.received_at < values["received_at"],
        )
        self._session.execute(statement)
        self._session.flush()
        self._session.expire_all()
        row = self._session.get(MinuteBarRow, (bar.symbol, bar.bar_end.isoformat()))
        if row is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Minute bar could not be reloaded")
        persisted = _minute_value(row)
        if persisted.received_at == bar.received_at and persisted != bar:
            raise MarketDataIdentityConflictError(
                "Minute identity and receipt time have conflicting facts"
            )
        return persisted

    def _upsert_latest_quote(self, bar: NormalizedMinuteBar) -> None:
        values = {
            "symbol": bar.symbol,
            "price_fen": bar.close_fen,
            "bar_end": bar.bar_end.isoformat(),
            "received_at": bar.received_at.isoformat(),
        }
        statement = sqlite_insert(LatestQuote).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[LatestQuote.symbol],
            set_={
                "price_fen": values["price_fen"],
                "bar_end": values["bar_end"],
                "received_at": values["received_at"],
            },
            where=or_(
                LatestQuote.bar_end < values["bar_end"],
                and_(
                    LatestQuote.bar_end == values["bar_end"],
                    LatestQuote.received_at < values["received_at"],
                ),
            ),
        )
        self._session.execute(statement)
        self._session.flush()
        self._session.expire_all()
        row = self._session.get(LatestQuote, bar.symbol)
        if row is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Latest quote could not be reloaded")
        persisted = _latest_quote_record(row)
        if (
            persisted.bar_end == bar.bar_end
            and persisted.received_at == bar.received_at
            and persisted.price_fen != bar.close_fen
        ):
            raise MarketDataIdentityConflictError("Latest quote identity has conflicting facts")

    def _upsert_daily_bar(self, bar: NormalizedDailyBar) -> NormalizedDailyBar:
        values = _daily_bar_values(bar)
        statement = sqlite_insert(DailyBarRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                DailyBarRow.symbol,
                DailyBarRow.trade_date,
                DailyBarRow.is_official,
            ],
            set_={
                "open_fen": values["open_fen"],
                "high_fen": values["high_fen"],
                "low_fen": values["low_fen"],
                "close_fen": values["close_fen"],
                "volume_shares": values["volume_shares"],
                "amount_yuan": values["amount_yuan"],
                "received_at": values["received_at"],
            },
            where=DailyBarRow.received_at < values["received_at"],
        )
        self._session.execute(statement)
        self._session.flush()
        self._session.expire_all()
        identity = (bar.symbol, bar.trade_date, bar.is_official)
        row = self._session.get(DailyBarRow, identity)
        if row is None:  # pragma: no cover - protected by insert/primary key
            raise RepositoryError("Daily bar could not be reloaded")
        persisted = _daily_bar_value(row)
        if persisted.received_at == bar.received_at and persisted != bar:
            raise MarketDataIdentityConflictError(
                "Daily-bar identity and receipt time have conflicting facts"
            )
        return persisted


class MarketReferenceRepository:
    """Persist normalized calendar and daily-limit reference facts."""

    _MAX_BATCH_ROWS = 1_000
    _MAX_READ_ROWS = 10_000

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_trading_days(self, days: Sequence[NormalizedTradingDay]) -> None:
        normalized = _normalized_batch(
            days,
            NormalizedTradingDay,
            "days",
            maximum=self._MAX_BATCH_ROWS,
        )
        for day in normalized:
            values = {
                "exchange": day.exchange,
                "cal_date": day.cal_date,
                "is_open": day.is_open,
                "previous_trade_date": day.previous_trade_date,
            }
            statement = sqlite_insert(TradingCalendar).values(**values)
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[TradingCalendar.exchange, TradingCalendar.cal_date],
                    set_={
                        "is_open": values["is_open"],
                        "previous_trade_date": values["previous_trade_date"],
                    },
                )
            )
            self._session.flush()
            self._session.expire_all()
            row = self._session.get(TradingCalendar, (day.exchange, day.cal_date))
            if row is None:  # pragma: no cover - protected by insert/primary key
                raise RepositoryError("Trading day could not be reloaded")
            if _trading_day_value(row) != day:  # pragma: no cover - protected by upsert
                raise RepositoryError("Trading day could not be updated")

    def list_trading_days(
        self,
        exchange: str,
        start: date,
        end: date,
    ) -> tuple[NormalizedTradingDay, ...]:
        normalized_exchange = _exchange(exchange)
        normalized_start, normalized_end = _date_range(start, end)
        rows = self._session.scalars(
            select(TradingCalendar)
            .where(
                TradingCalendar.exchange == normalized_exchange,
                TradingCalendar.cal_date >= normalized_start,
                TradingCalendar.cal_date <= normalized_end,
            )
            .order_by(TradingCalendar.cal_date)
            .limit(self._MAX_READ_ROWS + 1)
        ).all()
        _require_bounded_read(rows, self._MAX_READ_ROWS)
        return tuple(_trading_day_value(row) for row in rows)

    def upsert_daily_limits(self, limits: Sequence[NormalizedDailyLimit]) -> None:
        normalized = _normalized_batch(
            limits,
            NormalizedDailyLimit,
            "limits",
            maximum=self._MAX_BATCH_ROWS,
        )
        for limit in normalized:
            values = {
                "symbol": limit.symbol,
                "trade_date": limit.trade_date,
                "up_limit_fen": limit.up_limit_fen,
                "down_limit_fen": limit.down_limit_fen,
                "received_at": limit.received_at.isoformat(),
            }
            statement = sqlite_insert(DailyPriceLimit).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[DailyPriceLimit.symbol, DailyPriceLimit.trade_date],
                set_={
                    "up_limit_fen": values["up_limit_fen"],
                    "down_limit_fen": values["down_limit_fen"],
                    "received_at": values["received_at"],
                },
                where=DailyPriceLimit.received_at < values["received_at"],
            )
            self._session.execute(statement)
            self._session.flush()
            self._session.expire_all()
            row = self._session.get(
                DailyPriceLimit,
                (limit.symbol, limit.trade_date),
            )
            if row is None:  # pragma: no cover - protected by insert/primary key
                raise RepositoryError("Daily limit could not be reloaded")
            persisted = _daily_limit_value(row)
            if persisted.received_at == limit.received_at and persisted != limit:
                raise MarketDataIdentityConflictError(
                    "Daily-limit identity and receipt time have conflicting facts"
                )

    def list_daily_limits(self, trade_date: date) -> tuple[NormalizedDailyLimit, ...]:
        normalized_date = _calendar_date(trade_date, "trade_date")
        rows = self._session.scalars(
            select(DailyPriceLimit)
            .where(DailyPriceLimit.trade_date == normalized_date)
            .order_by(DailyPriceLimit.symbol)
            .limit(self._MAX_READ_ROWS + 1)
        ).all()
        _require_bounded_read(rows, self._MAX_READ_ROWS)
        return tuple(_daily_limit_value(row) for row in rows)


class IdempotencyRepository:
    """Atomically claim request identities and retain bounded replay responses."""

    _MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(self, session: Session, *, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    def claim(self, idempotency_key: str, request_hash: str) -> IdempotencyRecord:
        key = _idempotency_key(idempotency_key)
        digest = _request_hash(request_hash)
        now = _aware_now(self._clock).isoformat()
        statement = sqlite_insert(RequestIdempotency).values(
            idempotency_key=key,
            request_hash=digest,
            status=IdempotencyStatus.PENDING,
            response_code=None,
            response_json=None,
            created_at=now,
            updated_at=now,
        )
        result = self._session.execute(
            statement.on_conflict_do_nothing(index_elements=[RequestIdempotency.idempotency_key])
        )
        self._session.flush()
        self._session.expire_all()
        record = self._get(key)
        if record is None:  # pragma: no cover - protected by insert/unique key
            raise RepositoryError("Idempotency claim could not be reloaded")
        if result.rowcount == 1:
            return record
        if record.request_hash != digest:
            raise IdempotencyKeyReuseError("Idempotency key is already in use")
        if record.status == IdempotencyStatus.PENDING:
            raise IdempotencyInProgressError("Request is already in progress")
        return record

    def complete(
        self,
        idempotency_key: str,
        request_hash: str,
        *,
        response_code: int,
        response: Mapping[str, object],
    ) -> IdempotencyRecord:
        key = _idempotency_key(idempotency_key)
        digest = _request_hash(request_hash)
        if type(response_code) is not int or not 100 <= response_code <= 599:
            raise ValueError("response_code must be an integer between 100 and 599")
        if not isinstance(response, Mapping):
            raise TypeError("response must be a mapping")
        try:
            response_json = _canonical_json(dict(response))
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError("response must contain JSON-compatible values") from error
        if len(response_json.encode("utf-8")) > self._MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds the idempotency replay size limit")

        result = self._session.execute(
            update(RequestIdempotency)
            .where(
                RequestIdempotency.idempotency_key == key,
                RequestIdempotency.request_hash == digest,
                RequestIdempotency.status == IdempotencyStatus.PENDING,
            )
            .values(
                status=IdempotencyStatus.COMPLETED,
                response_code=response_code,
                response_json=response_json,
                updated_at=_aware_now(self._clock).isoformat(),
            )
        )
        self._session.flush()
        self._session.expire_all()
        record = self._get(key)
        if result.rowcount == 1 and record is not None:
            return record
        if record is None:
            raise IdempotencyClaimNotFoundError("Idempotency claim was not found")
        if record.request_hash != digest:
            raise IdempotencyKeyReuseError("Idempotency key is already in use")
        if record.status == IdempotencyStatus.COMPLETED:
            return record
        raise RepositoryError("Idempotency claim could not be completed")

    def _get(self, idempotency_key: str) -> IdempotencyRecord | None:
        model = self._session.get(RequestIdempotency, idempotency_key)
        return None if model is None else _idempotency_record(model)


def _aware_now(clock: Clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return an aware datetime")
    return value


def _plan_version_record(model: PlanVersion) -> PlanVersionRecord:
    return PlanVersionRecord(
        id=model.id,
        plan_id=model.plan_id,
        version=model.version,
        symbol=model.symbol,
        plan_hash=model.plan_hash,
        status=model.status,
        payload_json=model.payload_json,
        source_id=model.source_id,
        revision=model.revision,
        created_at=datetime.fromisoformat(model.created_at),
    )


def _plan_extraction_review_record(
    model: StoredPlanExtractionReview,
) -> PlanExtractionReviewRecord:
    record: PlanExtractionReviewRecord | None = None
    try:
        review = PlanExtractionReview(
            extraction_id=UUID(model.id),
            provider_id=UUID(model.provider_id),
            model=model.model,
            prompt_version=model.prompt_version,
            source_text_sha256=model.source_hash,
            draft_sha256=model.draft_hash,
            review_issues=_load_plan_review_issues(model.review_issues_json),
        )
        completed_at = datetime.fromisoformat(model.completed_at)
        if completed_at.tzinfo is not None and completed_at.utcoffset() is not None:
            record = PlanExtractionReviewRecord(
                extraction_id=str(review.extraction_id),
                provider_id=str(review.provider_id),
                model=review.model,
                prompt_version=review.prompt_version,
                source_hash=review.source_text_sha256,
                draft_hash=review.draft_sha256,
                review_issues=review.review_issues,
                completed_at=completed_at,
            )
    except TypeError, ValueError, RecursionError, UnicodeError:
        pass
    if record is None:
        raise RepositoryError("Stored extraction review is invalid")
    return record


def _plan_version_details_record(
    version: PlanVersion,
    source: PlanSource,
    review: PlanVersionReview,
    provenance: PlanReviewProvenance,
    extraction: StoredPlanExtractionReview | None,
) -> PlanVersionDetailsRecord:
    record: PlanVersionDetailsRecord | None = None
    try:
        plan = load_plan_json(version.payload_json)
        review_issues = _load_plan_review_issues(review.review_issues_json)
        created_at = datetime.fromisoformat(version.created_at)
        origin = PlanReviewOrigin(provenance.origin)
        confirmed_at = (
            None
            if provenance.confirmed_at is None
            else datetime.fromisoformat(provenance.confirmed_at)
        )
        extraction_record = (
            None if extraction is None else _plan_extraction_review_record(extraction)
        )
        extraction_valid = (
            origin in {PlanReviewOrigin.LEGACY_PENDING, PlanReviewOrigin.MANUAL}
            and provenance.extraction_id is None
            and extraction_record is None
        ) or (
            origin in {PlanReviewOrigin.AI_EXTRACTION, PlanReviewOrigin.AI_REIMPORT}
            and extraction_record is not None
            and provenance.extraction_id == extraction_record.extraction_id
            and provenance.draft_hash == extraction_record.draft_hash
            and (
                origin is PlanReviewOrigin.AI_REIMPORT
                or provenance.source_hash == extraction_record.source_hash
            )
            and _review_issues_match_required(
                review_issues,
                extraction_record.review_issues,
            )
        )
        confirmation_valid = (
            origin is PlanReviewOrigin.MANUAL
            or (origin is PlanReviewOrigin.LEGACY_PENDING and confirmed_at is None)
            or (
                origin is PlanReviewOrigin.AI_EXTRACTION
                and (confirmed_at is not None) == all(issue.resolved for issue in review_issues)
            )
            or (
                origin is PlanReviewOrigin.AI_REIMPORT
                and confirmed_at is None
                and all(not issue.resolved for issue in review_issues)
            )
        )
        valid = (
            version.id == review.plan_version_id
            and version.id == provenance.plan_version_id
            and version.source_id == source.id
            and source.source_hash == sha256(source.source_text.encode("utf-8")).hexdigest()
            and provenance.source_hash == source.source_hash
            and provenance.draft_hash == version.plan_hash
            and dump_plan_json(plan) == version.payload_json
            and plan.plan_id == version.plan_id
            and plan.version == version.version
            and plan.symbol == version.symbol
            and plan_sha256(plan) == version.plan_hash
            and PlanVersionStatus(version.status).value == version.status
            and version.revision >= 0
            and created_at.tzinfo is not None
            and created_at.utcoffset() is not None
            and (confirmed_at is None or confirmed_at.tzinfo is not None)
            and (confirmed_at is None or confirmed_at.utcoffset() is not None)
            and extraction_valid
            and confirmation_valid
        )
        if valid:
            record = PlanVersionDetailsRecord(
                **_plan_version_record(version).model_dump(mode="python"),
                source_text=source.source_text,
                review_issues=review_issues,
                review_origin=origin,
                extraction_id=provenance.extraction_id,
                review_confirmed_at=confirmed_at,
            )
    except TypeError, ValueError, RecursionError, UnicodeError:
        pass
    if record is None:
        raise RepositoryError("Stored plan version details are invalid")
    return record


def _review_issues_match_required(
    actual: Sequence[DraftReviewIssue],
    required: Sequence[DraftReviewIssue],
) -> bool:
    return len(actual) == len(required) and all(
        (item.kind, item.path, item.material) == (expected.kind, expected.path, expected.material)
        for item, expected in zip(actual, required, strict=True)
    )


def _same_extraction_review(
    left: PlanExtractionReviewRecord,
    right: PlanExtractionReviewRecord,
) -> bool:
    """Treat retried writes as idempotent while preserving the first completion time."""

    return (
        left.extraction_id == right.extraction_id
        and left.provider_id == right.provider_id
        and left.model == right.model
        and left.prompt_version == right.prompt_version
        and left.source_hash == right.source_hash
        and left.draft_hash == right.draft_hash
        and left.review_issues == right.review_issues
    )


def _plan_review_issues(
    review_issues: Sequence[DraftReviewIssue],
) -> tuple[DraftReviewIssue, ...]:
    if isinstance(review_issues, (str, bytes)) or not isinstance(review_issues, Sequence):
        raise TypeError("review_issues must be a sequence of DraftReviewIssue values")
    normalized = tuple(review_issues)
    if len(normalized) > 512:
        raise ValueError("review_issues exceeds the supported limit")
    if any(not isinstance(issue, DraftReviewIssue) for issue in normalized):
        raise TypeError("review_issues must contain only DraftReviewIssue values")
    return normalized


def _plan_review_issues_json(review_issues: Sequence[DraftReviewIssue]) -> str:
    normalized = _plan_review_issues(review_issues)
    return _canonical_json([issue.model_dump(mode="json", by_alias=True) for issue in normalized])


def _load_plan_review_issues(value: str) -> tuple[DraftReviewIssue, ...]:
    result: tuple[DraftReviewIssue, ...] | None = None
    try:
        payload = json.loads(value)
        if isinstance(payload, list):
            issues = tuple(DraftReviewIssue.model_validate(item) for item in payload)
            if len(issues) <= 512 and _plan_review_issues_json(issues) == value:
                result = issues
    except TypeError, ValueError, RecursionError:
        pass
    if result is None:
        raise RepositoryError("Stored plan review state is invalid")
    return result


def _plan_activation_state_record(model: PlanActivationState) -> PlanActivationStateRecord:
    record: PlanActivationStateRecord | None = None
    try:
        changed_at = datetime.fromisoformat(model.changed_at)
        valid = (
            _symbol(model.symbol) == model.symbol
            and (
                model.plan_version_id is None
                or _uuid_identifier(
                    model.plan_version_id,
                    "plan_version_id",
                )
                == model.plan_version_id
            )
            and model.revision >= 0
            and changed_at.tzinfo is not None
            and changed_at.utcoffset() is not None
        )
        if valid:
            record = PlanActivationStateRecord(
                symbol=model.symbol,
                plan_version_id=model.plan_version_id,
                revision=model.revision,
                changed_at=changed_at,
            )
    except TypeError, ValueError:
        pass
    if record is None:
        raise RepositoryError("Stored plan activation state is invalid")
    return record


def _active_plan_record(model: ActivePlan) -> ActivePlanRecord:
    record: ActivePlanRecord | None = None
    try:
        activated_at = datetime.fromisoformat(model.activated_at)
        valid = (
            _symbol(model.symbol) == model.symbol
            and _uuid_identifier(model.plan_version_id, "plan_version_id") == model.plan_version_id
            and type(model.revision) is int
            and model.revision >= 0
            and activated_at.tzinfo is not None
            and activated_at.utcoffset() is not None
        )
        if valid:
            record = ActivePlanRecord(
                symbol=model.symbol,
                plan_version_id=model.plan_version_id,
                activated_at=activated_at,
                revision=model.revision,
            )
    except TypeError, ValueError:
        pass
    if record is None:
        raise RepositoryError("Stored active plan pointer is invalid")
    return record


def _active_plan_hash(record: ActivePlanRecord) -> str:
    snapshot = {
        "activatedAt": record.activated_at.isoformat(),
        "planVersionId": record.plan_version_id,
        "revision": record.revision,
        "symbol": record.symbol,
    }
    return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _plan_activation_state_hash(record: PlanActivationStateRecord) -> str:
    snapshot = {
        "changedAt": record.changed_at.isoformat(),
        "planVersionId": record.plan_version_id,
        "revision": record.revision,
        "symbol": record.symbol,
    }
    return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _position_lot_record(model: PositionLot) -> PositionLotRecord:
    return PositionLotRecord(
        id=model.id,
        symbol=model.symbol,
        bucket=PositionBucket(model.bucket),
        quantity=model.quantity,
        remaining_qty=model.remaining_qty,
        acquired_trade_date=model.acquired_trade_date,
        cost_fen=model.cost_fen,
        related_alert_id=model.related_alert_id,
        closed_at=None if model.closed_at is None else datetime.fromisoformat(model.closed_at),
    )


def _position_lot_hash(record: PositionLotRecord) -> str:
    snapshot = {
        "acquiredTradeDate": record.acquired_trade_date.isoformat(),
        "bucket": record.bucket,
        "closedAt": None if record.closed_at is None else record.closed_at.isoformat(),
        "costFen": record.cost_fen,
        "id": record.id,
        "quantity": record.quantity,
        "relatedAlertId": record.related_alert_id,
        "remainingQty": record.remaining_qty,
        "symbol": record.symbol,
    }
    return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _episode_record(model: ZoneEpisode) -> EpisodeRecord:
    return EpisodeRecord(
        id=model.id,
        plan_hash=model.plan_hash,
        symbol=model.symbol,
        zone=model.zone,
        started_at=datetime.fromisoformat(model.started_at),
        episode_low_fen=model.episode_low_fen,
        bars_since_low=model.bars_since_low,
        status=model.status,
        alerted_signal=model.alerted_signal,
        last_processed_bucket_end=_episode_cursor(
            datetime.fromisoformat(model.last_processed_bucket_end)
        ),
    )


def _episode_hash(record: EpisodeRecord) -> str:
    snapshot = {
        "alertedSignal": record.alerted_signal,
        "barsSinceLow": record.bars_since_low,
        "episodeLowFen": record.episode_low_fen,
        "id": record.id,
        "lastProcessedBucketEnd": record.last_processed_bucket_end.isoformat(),
        "planHash": record.plan_hash,
        "startedAt": record.started_at.isoformat(),
        "status": record.status,
        "symbol": record.symbol,
        "zone": record.zone,
    }
    return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _risk_state_record(model: RiskState) -> RiskStateRecord:
    return RiskStateRecord(
        symbol=model.symbol,
        plan_hash=model.plan_hash,
        status=model.status,
        breach_trade_date=model.breach_trade_date,
        prior_close_fen=model.prior_close_fen,
        revision=model.revision,
        updated_at=datetime.fromisoformat(model.updated_at),
    )


def _risk_state_hash(record: RiskStateRecord) -> str:
    snapshot = {
        "breachTradeDate": (
            None if record.breach_trade_date is None else record.breach_trade_date.isoformat()
        ),
        "planHash": record.plan_hash,
        "priorCloseFen": record.prior_close_fen,
        "revision": record.revision,
        "status": record.status,
        "symbol": record.symbol,
        "updatedAt": record.updated_at.isoformat(),
    }
    return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()


def _evaluation_record(model: EvaluationLedger) -> EvaluationRecord:
    try:
        evaluation_kind = EvaluationKind(model.evaluation_kind)
        bucket_end = (
            datetime.fromisoformat(model.target_value)
            if evaluation_kind is EvaluationKind.INTRADAY
            else None
        )
        official_trade_date = (
            date.fromisoformat(model.target_value)
            if evaluation_kind is EvaluationKind.OFFICIAL_CLOSE
            else None
        )
    except TypeError, ValueError:
        raise RepositoryError("Stored evaluation identity is invalid") from None
    return EvaluationRecord(
        plan_hash=model.plan_hash,
        symbol=model.symbol,
        evaluation_kind=evaluation_kind,
        bucket_end=bucket_end,
        official_trade_date=official_trade_date,
        formula_version=model.formula_version,
        result_hash=model.result_hash,
        evaluated_at=datetime.fromisoformat(model.evaluated_at),
    )


def _provider_health_record(model: ProviderHealth) -> ProviderHealthRecord:
    return ProviderHealthRecord(
        capability=model.capability,
        status=ProviderCapabilityStatus(model.status),
        checked_at=datetime.fromisoformat(model.checked_at),
        latency_ms=model.latency_ms,
        error_code=model.error_code,
        next_retry_at=(
            None if model.next_retry_at is None else datetime.fromisoformat(model.next_retry_at)
        ),
    )


def _symbol_health_record(model: SymbolHealth) -> SymbolHealthRecord:
    return SymbolHealthRecord(
        symbol=model.symbol,
        status=SymbolHealthStatus(model.status),
        latest_bar_end=(
            None if model.latest_bar_end is None else datetime.fromisoformat(model.latest_bar_end)
        ),
        data_age_seconds=model.data_age_seconds,
        gap_json=model.gap_json,
        error_streak=model.error_streak,
        revision=model.revision,
    )


def _minute_values(bar: NormalizedMinuteBar) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "bar_end": bar.bar_end.isoformat(),
        "open_fen": bar.open_fen,
        "high_fen": bar.high_fen,
        "low_fen": bar.low_fen,
        "close_fen": bar.close_fen,
        "volume_shares": bar.volume_shares,
        "amount_yuan": str(bar.amount_yuan),
        "received_at": bar.received_at.isoformat(),
    }


def _minute_value(model: MinuteBarRow) -> NormalizedMinuteBar:
    return NormalizedMinuteBar(
        symbol=model.symbol,
        bar_end=datetime.fromisoformat(model.bar_end),
        open_fen=model.open_fen,
        high_fen=model.high_fen,
        low_fen=model.low_fen,
        close_fen=model.close_fen,
        volume_shares=model.volume_shares,
        amount_yuan=Decimal(model.amount_yuan),
        received_at=datetime.fromisoformat(model.received_at),
    )


def _five_minute_record(model: FiveMinuteBarRow) -> FiveMinuteBarRecord:
    return FiveMinuteBarRecord(
        symbol=model.symbol,
        bar_end=_canonical_market_datetime(
            datetime.fromisoformat(model.bar_end),
            "bar_end",
        ),
        formula_version=model.formula_version,
        open_fen=model.open_fen,
        high_fen=model.high_fen,
        low_fen=model.low_fen,
        close_fen=model.close_fen,
        volume_shares=model.volume_shares,
        amount_yuan=Decimal(model.amount_yuan),
    )


def _daily_bar_values(bar: NormalizedDailyBar) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "trade_date": bar.trade_date,
        "is_official": bar.is_official,
        "open_fen": bar.open_fen,
        "high_fen": bar.high_fen,
        "low_fen": bar.low_fen,
        "close_fen": bar.close_fen,
        "volume_shares": bar.volume_shares,
        "amount_yuan": str(bar.amount_yuan),
        "received_at": bar.received_at.isoformat(),
    }


def _daily_bar_value(model: DailyBarRow) -> NormalizedDailyBar:
    return NormalizedDailyBar(
        symbol=model.symbol,
        trade_date=model.trade_date,
        is_official=model.is_official,
        open_fen=model.open_fen,
        high_fen=model.high_fen,
        low_fen=model.low_fen,
        close_fen=model.close_fen,
        volume_shares=model.volume_shares,
        amount_yuan=Decimal(model.amount_yuan),
        received_at=datetime.fromisoformat(model.received_at),
    )


def _trading_day_value(model: TradingCalendar) -> NormalizedTradingDay:
    return NormalizedTradingDay(
        exchange=model.exchange,
        cal_date=model.cal_date,
        is_open=model.is_open,
        previous_trade_date=model.previous_trade_date,
    )


def _daily_limit_value(model: DailyPriceLimit) -> NormalizedDailyLimit:
    return NormalizedDailyLimit(
        symbol=model.symbol,
        trade_date=model.trade_date,
        up_limit_fen=model.up_limit_fen,
        down_limit_fen=model.down_limit_fen,
        received_at=datetime.fromisoformat(model.received_at),
    )


def _latest_quote_record(model: LatestQuote) -> LatestQuoteRecord:
    return LatestQuoteRecord(
        symbol=model.symbol,
        price_fen=model.price_fen,
        bar_end=_canonical_market_datetime(
            datetime.fromisoformat(model.bar_end),
            "bar_end",
        ),
        received_at=_canonical_market_datetime(
            datetime.fromisoformat(model.received_at),
            "received_at",
        ),
    )


def _normalized_batch[MarketValueT](
    values: Sequence[MarketValueT],
    expected_type: type[MarketValueT],
    name: str,
    *,
    maximum: int,
) -> tuple[MarketValueT, ...]:
    if type(values) not in (list, tuple):
        raise TypeError(f"{name} must be a list or tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} must not exceed {maximum} rows")
    if any(not isinstance(value, expected_type) for value in values):
        raise TypeError(f"{name} must contain only {expected_type.__name__} values")
    return tuple(values)


def _market_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _canonical_market_datetime(start, "start")
    normalized_end = _canonical_market_datetime(end, "end")
    if normalized_start > normalized_end:
        raise ValueError("start cannot follow end")
    return normalized_start, normalized_end


def _date_range(start: date, end: date) -> tuple[date, date]:
    normalized_start = _calendar_date(start, "start")
    normalized_end = _calendar_date(end, "end")
    if normalized_start > normalized_end:
        raise ValueError("start cannot follow end")
    return normalized_start, normalized_end


def _require_bounded_read(values: Sequence[object], maximum: int) -> None:
    if len(values) > maximum:
        raise RepositoryError(f"Market history read limit exceeded ({maximum})")


def _exchange(value: str) -> str:
    if value not in {"SSE", "SZSE", "BSE"}:
        raise ValueError("exchange must be SSE, SZSE, or BSE")
    return value


def _ohlc_fen(
    *,
    open_fen: int,
    high_fen: int,
    low_fen: int,
    close_fen: int,
) -> tuple[int, int, int, int]:
    normalized = (
        _positive_integer(open_fen, "open_fen"),
        _positive_integer(high_fen, "high_fen"),
        _positive_integer(low_fen, "low_fen"),
        _positive_integer(close_fen, "close_fen"),
    )
    if normalized[2] > normalized[1]:
        raise ValueError("low_fen cannot exceed high_fen")
    if not normalized[2] <= normalized[0] <= normalized[1]:
        raise ValueError("open_fen must be between low_fen and high_fen")
    if not normalized[2] <= normalized[3] <= normalized[1]:
        raise ValueError("close_fen must be between low_fen and high_fen")
    return normalized


def _nonnegative_decimal(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative Decimal")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _idempotency_key(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("idempotency_key must be a string")
    if not value or value != value.strip() or len(value) > 128:
        raise ValueError("idempotency_key must contain 1 to 128 non-padding characters")
    return value


def _uuid_identifier(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    parsed: UUID | None = None
    try:
        parsed = UUID(value)
    except ValueError:
        pass
    if parsed is None or str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID")
    return value


def _symbol(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("symbol must be a string")
    if re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", value) is None:
        raise ValueError("symbol must be a canonical A-share symbol")
    return value


def _plan_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("plan_id must be a string")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) is None:
        raise ValueError("plan_id must be a canonical plan identity")
    return value


def _position_bucket(value: str | PositionBucket) -> PositionBucket:
    try:
        return PositionBucket(value)
    except TypeError, ValueError:
        raise ValueError("bucket must be CORE or TACTICAL") from None


def _positive_integer(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _calendar_date(value: date, name: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{name} must be a date")
    return value


def _bounded_text(value: str, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1 to {maximum} non-padding characters")
    return value


def _identifier(value: str, name: str, *, maximum: int) -> str:
    normalized = _bounded_text(value, name, maximum=maximum)
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", normalized) is None:
        raise ValueError(f"{name} must be an uppercase identifier")
    return normalized


def _token(value: str, name: str, *, maximum: int) -> str:
    normalized = _bounded_text(value, name, maximum=maximum)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", normalized) is None:
        raise ValueError(f"{name} must be a safe identifier token")
    return normalized


def _sha256_hash(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _aware_datetime(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _canonical_market_datetime(value: datetime, name: str) -> datetime:
    return _aware_datetime(value, name).astimezone(ZoneInfo("Asia/Shanghai"))


def _evaluation_target(
    *,
    evaluation_kind: str | EvaluationKind,
    bucket_end: datetime | None,
    official_trade_date: date | None,
) -> tuple[EvaluationKind, str]:
    try:
        normalized_kind = EvaluationKind(evaluation_kind)
    except TypeError, ValueError:
        raise ValueError("evaluation_kind must be INTRADAY or OFFICIAL_CLOSE") from None

    if normalized_kind is EvaluationKind.INTRADAY:
        if bucket_end is None or official_trade_date is not None:
            raise ValueError("INTRADAY requires only bucket_end")
        normalized_bucket_end = _canonical_market_datetime(bucket_end, "bucket_end")
        expected_five_minute_ends(normalized_bucket_end)
        return normalized_kind, normalized_bucket_end.isoformat()

    if bucket_end is not None or official_trade_date is None:
        raise ValueError("OFFICIAL_CLOSE requires only official_trade_date")
    normalized_trade_date = _calendar_date(official_trade_date, "official_trade_date")
    return normalized_kind, normalized_trade_date.isoformat()


def _episode_cursor(value: datetime) -> datetime:
    expected_five_minute_ends(value)
    return value.replace(tzinfo=ZoneInfo("Asia/Shanghai"))


def _validate_episode_lifecycle_transition(
    *,
    before: EpisodeRecord,
    status: str,
    alerted_signal: str | None,
) -> None:
    valid_statuses = frozenset({"ACTIVE", "ALERTED", "CLOSED"})
    valid_signals = frozenset({"BUY_CORE_READY", "BUY_TACTICAL_READY"})
    if before.status not in valid_statuses or status not in valid_statuses:
        raise EpisodeTransitionError("Episode status is not supported")
    if status == "ACTIVE" and alerted_signal is not None:
        raise EpisodeTransitionError("Active episode cannot retain an alerted signal")
    if status == "ALERTED" and alerted_signal not in valid_signals:
        raise EpisodeTransitionError("Alerted episode requires a supported buy signal")
    if status == "CLOSED" and alerted_signal not in {None, *valid_signals}:
        raise EpisodeTransitionError("Closed episode has an unsupported alerted signal")

    allowed_statuses = {
        "ACTIVE": frozenset({"ACTIVE", "ALERTED", "CLOSED"}),
        "ALERTED": frozenset({"ALERTED", "CLOSED"}),
        "CLOSED": frozenset(),
    }
    if status not in allowed_statuses[before.status]:
        raise EpisodeTransitionError("Episode lifecycle cannot move backwards or reopen")
    if before.alerted_signal is not None and alerted_signal != before.alerted_signal:
        raise EpisodeTransitionError("Episode alerted signal cannot change or be cleared")
    if before.alerted_signal is None and alerted_signal is not None:
        if before.status != "ACTIVE" or status != "ALERTED":
            raise EpisodeTransitionError("Episode signal can be set only when alerting")


def _provider_status(
    value: str | ProviderCapabilityStatus,
) -> ProviderCapabilityStatus:
    try:
        return ProviderCapabilityStatus(value)
    except TypeError, ValueError:
        raise ValueError("status is not a supported provider capability state") from None


def _symbol_health_status(value: str | SymbolHealthStatus) -> SymbolHealthStatus:
    try:
        return SymbolHealthStatus(value)
    except TypeError, ValueError:
        raise ValueError("status is not a supported per-symbol health state") from None


def _request_hash(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("request_hash must be a lowercase SHA-256 hex digest")
    return value


def _idempotency_record(model: RequestIdempotency) -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key=model.idempotency_key,
        request_hash=model.request_hash,
        status=model.status,
        response_code=model.response_code,
        response_json=model.response_json,
        created_at=datetime.fromisoformat(model.created_at),
        updated_at=datetime.fromisoformat(model.updated_at),
    )


__all__ = [
    "ActivePlanRecord",
    "BoardLotViolationError",
    "DuplicatePlanVersionError",
    "EpisodeIdentityConflictError",
    "EpisodeNotFoundError",
    "EpisodeRecord",
    "EpisodeRepository",
    "EpisodeTransitionError",
    "EvaluationClaimRecord",
    "EvaluationIdentityConflictError",
    "EvaluationKind",
    "EvaluationRecord",
    "EvaluationRepository",
    "HealthRepository",
    "IdempotencyClaimNotFoundError",
    "IdempotencyInProgressError",
    "IdempotencyKeyReuseError",
    "IdempotencyRecord",
    "IdempotencyRepository",
    "FiveMinuteBarRecord",
    "LatestQuoteRecord",
    "MaxPositionExceededError",
    "MarketDataIdentityConflictError",
    "MarketHistoryRepository",
    "MarketReferenceRepository",
    "PlanActivationBlockedError",
    "PlanActivationStateRecord",
    "PlanExtractionReviewRecord",
    "PlanRepository",
    "PlanSaveBlockedError",
    "PlanVersionNotFoundError",
    "PlanVersionDetailsRecord",
    "PlanVersionRecord",
    "PositionLotNotFoundError",
    "PositionLotRecord",
    "PositionReductionError",
    "PositionRepository",
    "PositionT1LockedError",
    "ProviderHealthConflictError",
    "ProviderHealthRecord",
    "RepositoryError",
    "RevisionConflictError",
    "RiskRepository",
    "RiskStateRecord",
    "SymbolHealthRecord",
]
