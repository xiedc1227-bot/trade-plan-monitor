"""Persistent monitor read service assembled from committed projection heads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from inspect import isawaitable
from typing import cast
from uuid import UUID

from anyio import to_thread
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DataHealthStatus,
    EvaluationResult,
    IndexConditionEvidence,
    IntradayEvaluationIdentity,
    RuleEvidence,
)
from trade_plan_monitor.domain.plan_codec import PlanDocumentError, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    MarketIndexCode,
    identity_for_index_code,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexHealth,
    MarketIndexIndicatorFact,
    MarketIndexSnapshot,
    ReturnFactRequest,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.turnover import (
    MARKET_TURNOVER_INDEX_CODES,
    build_market_turnover_summary,
)
from trade_plan_monitor.runtime.health import live_runtime_identity
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    DASHBOARD_INDEX_CODES,
)
from trade_plan_monitor.state.events import MonitorEventError
from trade_plan_monitor.state.projections import ProjectionError
from trade_plan_monitor.state.repositories import PlanVersionDetailsRecord, RepositoryError
from trade_plan_monitor.state.unit_of_work import UnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import (
    AuthoritativeDecisionView,
    ConnectionStatus,
    DashboardCounts,
    DashboardProjectionResponse,
    DashboardProjectionUnavailableResponse,
    DashboardResponse,
    DataHealthView,
    DecisionEvidenceView,
    EvidenceFactView,
    EvidenceKind,
    IndexConditionEvidenceView,
    IndexConditionProgressView,
    MarketIndexIndicatorFactView,
    MarketIndexSnapshotView,
    MarketTurnoverSummaryView,
    NextStepView,
    PositionSummaryView,
    ProjectionUnavailableReason,
    ReturnIndicatorFactView,
    SmaIndicatorFactView,
    SmaLookbackIndicatorFactView,
    SymbolReferenceMarketView,
    SymbolSummaryView,
    validate_read_response,
)
from trade_plan_monitor.web.routers.health import RuntimeHealthResponse, SymbolHealthResponse
from trade_plan_monitor.web.routers.symbols import (
    BarInterval,
    BarPage,
    BarView,
    PositionLotView,
    SymbolCollectionResponse,
    SymbolCollectionUnavailableResponse,
    SymbolDetailProjectionResponse,
    SymbolDetailResponse,
    SymbolDetailUnavailableResponse,
    SymbolEventPage,
    SymbolEventType,
    SymbolEventView,
    SymbolPage,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
HealthProvider = Callable[[], object]
Clock = Callable[[], datetime]

_MAX_PLAN_ROWS = 10_000
_PLAN_PAGE_SIZE = 100
_MAX_EVENT_ROWS = 10_000
_EVENT_REPLAY_PAGE = 500


class PersistentMonitorReadService:
    """Build public reads only from state committed before this Unit of Work."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        health_provider: HealthProvider,
        *,
        clock: Clock,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        if not callable(health_provider):
            raise TypeError("health_provider must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._unit_of_work_factory = unit_of_work_factory
        self._health_provider = health_provider
        self._clock = clock

    async def get_dashboard(self) -> DashboardProjectionResponse:
        return await to_thread.run_sync(
            lambda: self._read_projection(self._get_dashboard)
        )

    def _get_dashboard(self) -> DashboardProjectionResponse:
        observed_at = _observed_at(self._clock())
        with self._unit_of_work_factory() as work:
            sequence = work.events.current_sequence()
            stored_snapshots = tuple(
                record.snapshot
                for record in work.projections.list_latest_market_index_snapshots(
                    mapping_version=MAPPING_VERSION,
                    index_codes=ALWAYS_ON_INDEX_CODES,
                )
            )
            stored_by_code = {
                snapshot.index_code: snapshot for snapshot in stored_snapshots
            }
            display_snapshots = tuple(
                stored_by_code[index_code]
                for index_code in DASHBOARD_INDEX_CODES
                if index_code in stored_by_code
            )
            recoveries = {
                code: (cutoff, attempts, due_at)
                for code, cutoff, first_failed_at, attempts, due_at in (
                    work.projections.list_market_index_recoveries()
                )
                if observed_at <= first_failed_at + timedelta(minutes=5)
            }
            turnover_summary = build_market_turnover_summary(
                tuple(
                    stored_by_code[index_code]
                    for index_code in MARKET_TURNOVER_INDEX_CODES
                    if index_code in stored_by_code
                )
            )
            market_turnover = (
                None
                if turnover_summary is None
                else MarketTurnoverSummaryView.model_validate(
                    {
                        **turnover_summary.model_dump(mode="python", round_trip=True),
                        "benchmark_codes": MARKET_TURNOVER_INDEX_CODES,
                    }
                )
            )
            details = _list_plan_details(work)
            if not details:
                if display_snapshots:
                    return self._index_only_dashboard(
                        display_snapshots,
                        recoveries=recoveries,
                        observed_at=observed_at,
                        sequence=sequence,
                        market_turnover=market_turnover,
                    )
                return _dashboard_unavailable(
                    ProjectionUnavailableReason.EMPTY_DATABASE,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            active = _active_plan_details(work, details)
            if not active:
                if display_snapshots:
                    return self._index_only_dashboard(
                        display_snapshots,
                        recoveries=recoveries,
                        observed_at=observed_at,
                        sequence=sequence,
                        market_turnover=market_turnover,
                    )
                return _dashboard_unavailable(
                    ProjectionUnavailableReason.NO_ACTIVE_PLANS,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            runtime_identity = self._runtime_identity(observed_at=observed_at)
            projections = _complete_active_projections(
                work,
                active,
                observed_at=observed_at,
                runtime_identity=runtime_identity,
            )
            if projections is None:
                if display_snapshots:
                    return self._index_only_dashboard(
                        display_snapshots,
                        recoveries=recoveries,
                        observed_at=observed_at,
                        sequence=sequence,
                        runtime_identity=runtime_identity,
                        market_turnover=market_turnover,
                    )
                return _dashboard_unavailable(
                    ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            summaries = tuple(item.summary for item in projections)
            market_indexes = _dashboard_market_indexes(
                projections,
                display_snapshots=display_snapshots,
                recoveries=recoveries,
            )
            return DashboardResponse(
                sequence=sequence,
                observed_at=observed_at,
                runtime_generation=(
                    None if runtime_identity is None else runtime_identity[1]
                ),
                connection_status=_connection_status(summaries),
                counts=_dashboard_counts(summaries),
                symbols=summaries,
                market_indexes=market_indexes,
                market_turnover=market_turnover,
            )

    def _index_only_dashboard(
        self,
        display_snapshots: tuple[MarketIndexSnapshot, ...],
        *,
        recoveries: Mapping[MarketIndexCode, tuple[datetime, int, datetime]],
        observed_at: datetime,
        sequence: int,
        runtime_identity: tuple[datetime, UUID] | None = None,
        market_turnover: MarketTurnoverSummaryView | None = None,
    ) -> DashboardResponse:
        if runtime_identity is None:
            runtime_identity = self._runtime_identity(observed_at=observed_at)
        return DashboardResponse(
            sequence=sequence,
            observed_at=observed_at,
            runtime_generation=(None if runtime_identity is None else runtime_identity[1]),
            connection_status=(
                ConnectionStatus.UNKNOWN
                if runtime_identity is None
                else ConnectionStatus.CONNECTED
            ),
            counts=_dashboard_counts(()),
            symbols=(),
            market_indexes=_dashboard_market_indexes(
                (),
                display_snapshots=display_snapshots,
                recoveries=recoveries,
            ),
            market_turnover=market_turnover,
        )

    async def list_symbols(
        self,
        *,
        offset: int,
        limit: int,
    ) -> SymbolCollectionResponse:
        return await to_thread.run_sync(
            lambda: self._read_projection(
                lambda: self._list_symbols(offset=offset, limit=limit)
            )
        )

    def _list_symbols(
        self,
        *,
        offset: int,
        limit: int,
    ) -> SymbolCollectionResponse:
        _pagination(offset, limit)
        observed_at = _observed_at(self._clock())
        with self._unit_of_work_factory() as work:
            sequence = work.events.current_sequence()
            details = _list_plan_details(work)
            if not details:
                return _collection_unavailable(
                    ProjectionUnavailableReason.EMPTY_DATABASE,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            active = _active_plan_details(work, details)
            if not active:
                return _collection_unavailable(
                    ProjectionUnavailableReason.NO_ACTIVE_PLANS,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            runtime_identity = self._runtime_identity(observed_at=observed_at)
            projections = _complete_active_projections(
                work,
                active,
                observed_at=observed_at,
                runtime_identity=runtime_identity,
            )
            if projections is None:
                return _collection_unavailable(
                    ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
                    observed_at=observed_at,
                    sequence=sequence,
                )
            summaries = tuple(item.summary for item in projections)
            return SymbolPage(
                items=summaries[offset : offset + limit],
                offset=offset,
                limit=limit,
                total=len(summaries),
            )

    async def get_symbol(
        self,
        *,
        symbol: str,
    ) -> SymbolDetailProjectionResponse | None:
        return await to_thread.run_sync(
            lambda: self._read_projection(lambda: self._get_symbol(symbol=symbol))
        )

    def _get_symbol(
        self,
        *,
        symbol: str,
    ) -> SymbolDetailProjectionResponse | None:
        observed_at = _observed_at(self._clock())
        with self._unit_of_work_factory() as work:
            sequence = work.events.current_sequence()
            activation = work.plans.get_activation_state(symbol)
            if activation is None:
                return None
            active = work.plans.get_active(symbol)
            if active is None:
                return _detail_unavailable(
                    ProjectionUnavailableReason.NO_ACTIVE_PLAN,
                    observed_at=observed_at,
                    sequence=sequence,
                    symbol=symbol,
                )
            details = work.plans.get_version_details(active.plan_version_id)
            if details is None:
                raise ProjectionError("Active plan has no immutable version details")
            runtime_identity = self._runtime_identity(observed_at=observed_at)
            projection = _complete_symbol_projection(
                work,
                details,
                observed_at=observed_at,
                runtime_identity=runtime_identity,
            )
            if projection is None:
                return _detail_unavailable(
                    ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION,
                    observed_at=observed_at,
                    sequence=sequence,
                    symbol=symbol,
                )
            return projection.detail

    @staticmethod
    def _read_projection[Result](operation: Callable[[], Result]) -> Result:
        try:
            return operation()
        except (
            MonitorEventError,
            PlanDocumentError,
            RepositoryError,
            SQLAlchemyError,
            ValidationError,
        ):
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None

    async def list_symbol_bars(
        self,
        *,
        symbol: str,
        interval: BarInterval,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> BarPage | None:
        return await to_thread.run_sync(
            lambda: self._read_projection(
                lambda: self._list_symbol_bars(
                    symbol=symbol,
                    interval=interval,
                    start_at=start_at,
                    end_at=end_at,
                    offset=offset,
                    limit=limit,
                )
            )
        )

    def _list_symbol_bars(
        self,
        *,
        symbol: str,
        interval: BarInterval,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> BarPage | None:
        _pagination(offset, limit)
        with self._unit_of_work_factory() as work:
            if work.plans.get_activation_state(symbol) is None:
                return None
            if interval is BarInterval.ONE_MINUTE:
                rows = work.history.list_minutes(symbol, start=start_at, end=end_at)
                items = tuple(
                    BarView(
                        symbol=row.symbol,
                        interval=interval,
                        bar_end=row.bar_end,
                        open_fen=row.open_fen,
                        high_fen=row.high_fen,
                        low_fen=row.low_fen,
                        close_fen=row.close_fen,
                        volume_shares=row.volume_shares,
                        amount_yuan=row.amount_yuan,
                        received_at=row.received_at,
                        formula_version=None,
                    )
                    for row in rows
                )
            elif interval is BarInterval.FIVE_MINUTES:
                rows = work.history.list_five_minute(symbol, start=start_at, end=end_at)
                items = tuple(
                    BarView(
                        symbol=row.symbol,
                        interval=interval,
                        bar_end=row.bar_end,
                        open_fen=row.open_fen,
                        high_fen=row.high_fen,
                        low_fen=row.low_fen,
                        close_fen=row.close_fen,
                        volume_shares=row.volume_shares,
                        amount_yuan=row.amount_yuan,
                        received_at=row.bar_end,
                        formula_version=row.formula_version,
                    )
                    for row in rows
                )
            else:
                raise ValueError("interval is not supported")
            return BarPage(
                items=items[offset : offset + limit],
                offset=offset,
                limit=limit,
                total=len(items),
                start_at=start_at,
                end_at=end_at,
            )

    async def list_symbol_events(
        self,
        *,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> SymbolEventPage | None:
        return await to_thread.run_sync(
            lambda: self._read_projection(
                lambda: self._list_symbol_events(
                    symbol=symbol,
                    start_at=start_at,
                    end_at=end_at,
                    offset=offset,
                    limit=limit,
                )
            )
        )

    def _list_symbol_events(
        self,
        *,
        symbol: str,
        start_at: datetime,
        end_at: datetime,
        offset: int,
        limit: int,
    ) -> SymbolEventPage | None:
        _pagination(offset, limit)
        with self._unit_of_work_factory() as work:
            if work.plans.get_activation_state(symbol) is None:
                return None
            events = _retained_symbol_events(
                work,
                symbol=symbol,
                start_at=start_at,
                end_at=end_at,
            )
            return SymbolEventPage(
                items=events[offset : offset + limit],
                offset=offset,
                limit=limit,
                total=len(events),
                start_at=start_at,
                end_at=end_at,
            )

    async def get_health(self) -> RuntimeHealthResponse:
        try:
            value = self._health_provider()
            if isawaitable(value):
                value = await value
            return validate_read_response(value, RuntimeHealthResponse)
        except Exception:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None

    async def get_symbol_health(self, *, symbol: str) -> SymbolHealthResponse | None:
        return await to_thread.run_sync(
            lambda: self._read_projection(
                lambda: self._get_symbol_health(symbol=symbol)
            )
        )

    def _get_symbol_health(self, *, symbol: str) -> SymbolHealthResponse | None:
        with self._unit_of_work_factory() as work:
            active = work.plans.get_active(symbol)
            if active is None:
                return None
            record = work.projections.get_symbol_health(symbol)
            if record is None or record.activation_revision != active.revision:
                return None
            response = validate_read_response(record.projection, SymbolHealthResponse)
            observed_at = _observed_at(self._clock())
            runtime_identity = self._runtime_identity(
                observed_at=observed_at
            )
            if runtime_identity is None:
                return None
            runtime_started_at, runtime_generation = runtime_identity
            if (
                record.runtime_generation != runtime_generation
                or response.observed_at > observed_at
                or response.observed_at < max(active.activated_at, runtime_started_at)
            ):
                return None
            return response

    def _runtime_identity(
        self,
        *,
        observed_at: datetime,
    ) -> tuple[datetime, UUID] | None:
        try:
            value = self._health_provider()
            if isawaitable(value):
                close = getattr(value, "close", None)
                if callable(close):
                    close()
                raise ProjectionError(
                    "Runtime health cannot be awaited during projection assembly"
                )
            return live_runtime_identity(value, observed_at=observed_at)
        except Exception:
            raise ProjectionError("Runtime health provider is unavailable") from None


class _SymbolProjection:
    def __init__(
        self,
        *,
        summary: SymbolSummaryView,
        detail: SymbolDetailResponse,
        market_index: MarketIndexSnapshot | None,
    ) -> None:
        self.summary = summary
        self.detail = detail
        self.market_index = market_index


def _complete_active_projections(
    work: UnitOfWork,
    active: tuple[PlanVersionDetailsRecord, ...],
    *,
    observed_at: datetime,
    runtime_identity: tuple[datetime, UUID] | None,
) -> tuple[_SymbolProjection, ...] | None:
    projections: list[_SymbolProjection] = []
    for details in active:
        projection = _complete_symbol_projection(
            work,
            details,
            observed_at=observed_at,
            runtime_identity=runtime_identity,
        )
        if projection is None:
            return None
        projections.append(projection)
    return tuple(sorted(projections, key=lambda item: item.summary.symbol))


def _complete_symbol_projection(
    work: UnitOfWork,
    details: PlanVersionDetailsRecord,
    *,
    observed_at: datetime,
    runtime_identity: tuple[datetime, UUID] | None,
) -> _SymbolProjection | None:
    plan = load_plan_json(details.payload_json)
    active = work.plans.get_active(plan.symbol)
    if active is None:
        return None
    if active.plan_version_id != details.id:
        raise ProjectionError("Active plan changed during projection assembly")
    head = work.projections.get_decision_head(plan.symbol)
    if (
        head is None
        or head.activation_revision != active.revision
        or head.result.snapshot.plan_hash != plan_sha256(plan)
    ):
        return None
    result = head.result
    if result.snapshot.evaluated_at > observed_at:
        raise ProjectionError("Decision head is newer than the read observation")
    decision = _decision_view(result)
    reference, index_evidence, market_index = _reference_market(work, result)
    satisfied = sum(
        evidence.outcome is ConditionOutcome.SATISFIED
        for evidence in result.snapshot.condition_evidence
    )
    total = len(result.snapshot.condition_evidence)
    current_health_record = work.projections.get_symbol_health(plan.symbol)
    current_health = (
        None
        if current_health_record is None
        or current_health_record.activation_revision != active.revision
        or runtime_identity is None
        or current_health_record.runtime_generation != runtime_identity[1]
        else validate_read_response(current_health_record.projection, SymbolHealthResponse)
    )
    if current_health is not None and current_health.observed_at > observed_at:
        raise ProjectionError("Symbol health is newer than the read observation")
    freshness_boundary = (
        active.activated_at
        if runtime_identity is None
        else max(active.activated_at, runtime_identity[0])
    )
    summary = SymbolSummaryView(
        symbol=plan.symbol,
        name=plan.name,
        observed_at=observed_at,
        connected=(
            runtime_identity is not None
            and current_health is not None
            and current_health.actionable
            and current_health.observed_at >= freshness_boundary
        ),
        risk_distance_fen=(
            None
            if result.snapshot.price_fen is None
            else result.snapshot.price_fen - plan.levels.risk_line_fen
        ),
        satisfied_condition_count=satisfied,
        total_condition_count=total,
        decision=decision,
        reference_market=reference,
    )
    identity = result.evaluation_identity
    evaluation_trade_date = (
        identity.bucket_end.date()
        if isinstance(identity, IntradayEvaluationIdentity)
        else identity.official_trade_date
    )
    lots = tuple(
        PositionLotView(
            lot_id=lot.id,
            bucket=lot.bucket,
            quantity=lot.quantity,
            remaining_quantity=lot.remaining_qty,
            sellable_quantity=(
                lot.remaining_qty
                if lot.acquired_trade_date < evaluation_trade_date
                else 0
            ),
            acquired_trade_date=lot.acquired_trade_date,
            cost_fen=lot.cost_fen,
        )
        for lot in head.position_lots
    )
    detail = SymbolDetailResponse(
        summary=summary,
        position_lots=lots,
        reference_market=reference,
        index_condition_evidence=index_evidence,
    )
    return _SymbolProjection(
        summary=summary,
        detail=detail,
        market_index=market_index,
    )


def _decision_view(result: EvaluationResult) -> AuthoritativeDecisionView:
    snapshot = result.snapshot
    return AuthoritativeDecisionView(
        symbol=snapshot.symbol,
        result_hash=result.result_hash,
        plan_id=snapshot.plan_id,
        plan_version=snapshot.plan_version,
        plan_hash=snapshot.plan_hash,
        evaluated_at=snapshot.evaluated_at,
        market_data_at=snapshot.market_data_at,
        data_age_seconds=(
            None
            if snapshot.market_data_at is None
            else int((snapshot.evaluated_at - snapshot.market_data_at).total_seconds())
        ),
        price_fen=snapshot.price_fen,
        zone=snapshot.zone,
        signal_type=snapshot.signal_type,
        position=PositionSummaryView.model_validate(
            snapshot.position.model_dump(mode="python", round_trip=True)
        ),
        episode_status=None if snapshot.episode is None else snapshot.episode.status,
        episode_low_fen=(
            None if snapshot.episode is None else snapshot.episode.episode_low_fen
        ),
        risk_status=snapshot.risk.status,
        risk_breach_trade_date=snapshot.risk.breach_trade_date,
        data_health=DataHealthView.model_validate(
            snapshot.data_health.model_dump(
                mode="python",
                round_trip=True,
                exclude={"symbol"},
            )
        ),
        evidence=tuple(_evidence_view(item) for item in snapshot.condition_evidence),
        next_step=NextStepView.model_validate(
            snapshot.next_step.model_dump(mode="python", round_trip=True)
        ),
    )


def _evidence_view(value: ConditionEvidence | RuleEvidence) -> DecisionEvidenceView:
    if isinstance(value, ConditionEvidence):
        kind = EvidenceKind.CONDITION
        code = value.condition.type
        children = tuple(_evidence_view(child) for child in value.children)
    elif isinstance(value, RuleEvidence):
        kind = EvidenceKind.RULE
        code = value.code.value
        children = ()
    else:  # pragma: no cover - closed EvaluationEvidence union
        raise TypeError("unsupported decision evidence")
    return DecisionEvidenceView(
        kind=kind,
        code=code,
        outcome=value.outcome,
        facts=tuple(
            EvidenceFactView(key=fact.key, value=fact.value, unit=fact.unit)
            for fact in value.facts
        ),
        missing_inputs=value.missing_inputs,
        children=children,
    )


def _reference_market(
    work: UnitOfWork,
    result: EvaluationResult,
) -> tuple[
    SymbolReferenceMarketView | None,
    tuple[IndexConditionEvidenceView, ...],
    MarketIndexSnapshot | None,
]:
    source = result.snapshot.reference_market
    evidence = tuple(
        sorted(
            _index_evidence(result.snapshot.condition_evidence),
            key=lambda item: item.plan_path,
        )
    )
    if source is None:
        if evidence:
            raise ProjectionError("Index evidence has no reference-market identity")
        return None, (), None
    stored = work.projections.get_market_index_snapshot(source.snapshot_hash)
    if stored is None:
        raise ProjectionError("Decision reference market has no immutable snapshot")
    snapshot = stored.snapshot
    if (
        snapshot.index_code is not source.index_code
        or snapshot.completed_bucket_at != source.data_at
        or snapshot.health is not source.health
    ):
        raise ProjectionError("Decision reference market crosses snapshot identity")
    satisfied = sum(item.outcome is ConditionOutcome.SATISFIED for item in evidence)
    unsatisfied = sum(item.outcome is ConditionOutcome.UNSATISFIED for item in evidence)
    missing = sum(item.outcome is ConditionOutcome.MISSING_INPUT for item in evidence)
    board, display_name = identity_for_index_code(source.index_code)
    reference = SymbolReferenceMarketView(
        index_code=source.index_code,
        display_name=display_name,
        board=board,
        mapping_version=MAPPING_VERSION,
        snapshot_hash=source.snapshot_hash,
        data_at=source.data_at,
        health=source.health,
        issues=snapshot.issues,
        condition_progress=IndexConditionProgressView(
            satisfied=satisfied,
            unsatisfied=unsatisfied,
            missing=missing,
            total=len(evidence),
        ),
    )
    return reference, evidence, snapshot


def _index_evidence(
    values: tuple[ConditionEvidence | RuleEvidence, ...],
) -> tuple[IndexConditionEvidenceView, ...]:
    result: list[IndexConditionEvidenceView] = []
    for value in values:
        if not isinstance(value, ConditionEvidence):
            continue
        if value.index_evidence is not None:
            result.append(_index_evidence_view(value.index_evidence))
        children = cast(tuple[ConditionEvidence | RuleEvidence, ...], value.children)
        result.extend(_index_evidence(children))
    return tuple(result)


def _index_evidence_view(value: IndexConditionEvidence) -> IndexConditionEvidenceView:
    return IndexConditionEvidenceView(
        plan_path=value.plan_path,
        condition_type=value.condition_type,
        index_code=value.index_code,
        mapping_version=value.mapping_version,
        snapshot_hash=value.snapshot_hash,
        decision_cutoff=value.decision_cutoff,
        data_cutoff=value.data_cutoff,
        formula_id=value.formula_id,
        formula_definition_hash=value.formula_definition_hash,
        parameters=tuple(
            EvidenceFactView(key=fact.key, value=fact.value, unit=fact.unit)
            for fact in value.parameters
        ),
        actual_value=value.actual_value,
        comparison_value=value.comparison_value,
        unit=value.unit,
        outcome=value.outcome,
        missing_inputs=value.missing_inputs,
    )


def _dashboard_market_indexes(
    projections: tuple[_SymbolProjection, ...],
    *,
    display_snapshots: tuple[MarketIndexSnapshot, ...] = (),
    recoveries: Mapping[MarketIndexCode, tuple[datetime, int, datetime]] | None = None,
) -> tuple[MarketIndexSnapshotView, ...]:
    snapshots = {snapshot.index_code.value: snapshot for snapshot in display_snapshots}
    mapped_counts: dict[str, int] = {}
    for item in projections:
        snapshot = item.market_index
        if snapshot is None:
            continue
        index_code = snapshot.index_code.value
        mapped_counts[index_code] = mapped_counts.get(index_code, 0) + 1
        current = snapshots.get(index_code)
        if current is None or (
            snapshot.decision_cutoff,
            snapshot.revision,
            snapshot.observed_at,
            snapshot.snapshot_hash,
        ) > (
            current.decision_cutoff,
            current.revision,
            current.observed_at,
            current.snapshot_hash,
        ):
            snapshots[index_code] = snapshot
    return tuple(
        sorted(
            (
                _market_index_view(
                    snapshot,
                    mapped_symbol_count=mapped_counts.get(index_code, 0),
                    recovery=(None if recoveries is None else recoveries.get(snapshot.index_code)),
                )
                for index_code, snapshot in snapshots.items()
            ),
            key=lambda item: str(item.index_code),
        )
    )


def _market_index_view(
    snapshot: MarketIndexSnapshot,
    *,
    mapped_symbol_count: int,
    recovery: tuple[datetime, int, datetime] | None = None,
) -> MarketIndexSnapshotView:
    latest = snapshot.latest_completed_five_minute
    close = None if latest is None else latest.close_points
    prior = snapshot.prior_official_close_points
    change = None if close is None or prior is None else (close - prior) / prior
    pending_recovery = (
        recovery
        if recovery is not None
        and recovery[0] == snapshot.decision_cutoff
        and snapshot.health is MarketIndexHealth.BLOCKED
        else None
    )
    return MarketIndexSnapshotView(
        index_code=snapshot.index_code,
        display_name=snapshot.display_name,
        board=snapshot.board,
        close_points=close,
        prior_close_points=prior,
        session_change_ratio=change,
        completed_bucket_at=snapshot.completed_bucket_at,
        observed_at=snapshot.observed_at,
        health=snapshot.health,
        issues=snapshot.issues,
        indicator_facts=tuple(_indicator_fact_view(item) for item in snapshot.indicator_facts),
        mapped_symbol_count=mapped_symbol_count,
        mapping_version=snapshot.mapping_version,
        revision=snapshot.revision,
        snapshot_hash=snapshot.snapshot_hash,
        recovery_attempts=None if pending_recovery is None else pending_recovery[1],
        next_retry_at=None if pending_recovery is None else pending_recovery[2],
    )


def _indicator_fact_view(value: MarketIndexIndicatorFact) -> MarketIndexIndicatorFactView:
    common = {
        "value": value.value,
        "unit": value.unit,
        "source_bar_hash": value.source_bar_hash,
        "formula_definition_hash": value.formula_definition_hash,
    }
    request = value.request
    if isinstance(request, SmaFactRequest):
        return SmaIndicatorFactView(
            formula_id="SMA",
            period=request.period,
            **common,
        )
    if isinstance(request, SmaLookbackFactRequest):
        if value.comparison_value is None:  # pragma: no cover - domain model protects this
            raise ProjectionError("SMA lookback fact has no comparison value")
        return SmaLookbackIndicatorFactView(
            formula_id="SMA_LOOKBACK",
            period=request.period,
            lookback=request.lookback,
            comparison_value=value.comparison_value,
            **common,
        )
    if isinstance(request, ReturnFactRequest):
        return ReturnIndicatorFactView(
            formula_id="RETURN",
            window=request.window,
            window_size=request.window_size,
            **common,
        )
    raise TypeError("unsupported market-index fact request")  # pragma: no cover


def _retained_symbol_events(
    work: UnitOfWork,
    *,
    symbol: str,
    start_at: datetime,
    end_at: datetime,
) -> tuple[SymbolEventView, ...]:
    cursor = 0
    selected: list[SymbolEventView] = []
    while True:
        page = work.events.replay_page_after(cursor, limit=_EVENT_REPLAY_PAGE)
        if page.requires_snapshot:
            raise ProjectionError("Requested symbol events are outside retained replay history")
        for event in page.events:
            if event.payload.symbol != symbol or not start_at <= event.occurred_at <= end_at:
                continue
            event_type = _symbol_event_type(event.event_type.value)
            if event_type is None:
                continue
            selected.append(
                SymbolEventView(
                    symbol=symbol,
                    sequence=event.sequence,
                    event_id=str(event.event_id),
                    event_type=event_type,
                    occurred_at=event.occurred_at,
                    signal_type=None,
                    result_hash=event.payload.result_hash,
                    message_text=None,
                )
            )
            if len(selected) > _MAX_EVENT_ROWS:
                raise ProjectionError("Symbol event collection exceeds its read limit")
        if not page.events:
            break
        cursor = page.events[-1].sequence
        if cursor >= page.high_water_sequence:
            break
    return tuple(selected)


def _symbol_event_type(event_type: str) -> SymbolEventType | None:
    if event_type == "symbol.snapshot.updated":
        return SymbolEventType.DECISION
    if event_type == "symbol.health.updated":
        return SymbolEventType.HEALTH
    if event_type in {"alert.created", "alert.acknowledged"}:
        return SymbolEventType.ALERT
    return None


def _list_plan_details(work: UnitOfWork) -> tuple[PlanVersionDetailsRecord, ...]:
    first, total = work.plans.list_version_details(offset=0, limit=_PLAN_PAGE_SIZE)
    if total > _MAX_PLAN_ROWS:
        raise ProjectionError("Plan library exceeds the persistent read limit")
    rows = list(first)
    for offset in range(_PLAN_PAGE_SIZE, total, _PLAN_PAGE_SIZE):
        page, confirmed_total = work.plans.list_version_details(
            offset=offset,
            limit=_PLAN_PAGE_SIZE,
        )
        if confirmed_total != total:
            raise ProjectionError("Plan library changed inside one read transaction")
        rows.extend(page)
    return tuple(rows)


def _active_plan_details(
    work: UnitOfWork,
    details: tuple[PlanVersionDetailsRecord, ...],
) -> tuple[PlanVersionDetailsRecord, ...]:
    details_by_id = {item.id: item for item in details}
    active: list[PlanVersionDetailsRecord] = []
    for symbol in sorted({item.symbol for item in details}):
        pointer = work.plans.get_active(symbol)
        if pointer is None:
            continue
        item = details_by_id.get(pointer.plan_version_id)
        if item is None:
            raise ProjectionError("Active plan pointer is missing from immutable plan state")
        active.append(item)
    if len(active) > 10:
        raise ProjectionError("Active plan set exceeds the supported bound")
    return tuple(active)


def _dashboard_unavailable(
    reason: ProjectionUnavailableReason,
    *,
    observed_at: datetime,
    sequence: int,
) -> DashboardProjectionUnavailableResponse:
    return DashboardProjectionUnavailableResponse(
        availability="UNAVAILABLE",
        reason=reason,
        observed_at=observed_at,
        sequence=sequence,
    )


def _collection_unavailable(
    reason: ProjectionUnavailableReason,
    *,
    observed_at: datetime,
    sequence: int,
) -> SymbolCollectionUnavailableResponse:
    return SymbolCollectionUnavailableResponse(
        availability="UNAVAILABLE",
        reason=reason,
        observed_at=observed_at,
        sequence=sequence,
    )


def _detail_unavailable(
    reason: ProjectionUnavailableReason,
    *,
    observed_at: datetime,
    sequence: int,
    symbol: str,
) -> SymbolDetailUnavailableResponse:
    return SymbolDetailUnavailableResponse(
        availability="UNAVAILABLE",
        reason=reason,
        observed_at=observed_at,
        sequence=sequence,
        symbol=symbol,
    )


def _dashboard_counts(summaries: tuple[SymbolSummaryView, ...]) -> DashboardCounts:
    counts = {
        "actionable": 0,
        "low_zone_watch": 0,
        "blocked": 0,
        "risk": 0,
        "stale": 0,
        "normal": 0,
    }
    actionable_values = {item.value for item in ActionableSignalType}
    for summary in summaries:
        decision = summary.decision
        if not summary.connected:
            counts["stale"] += 1
        elif decision.signal_type.value in actionable_values:
            counts["actionable"] += 1
        elif decision.risk_status.value != "CLEAR":
            counts["risk"] += 1
        elif decision.data_health.status in {DataHealthStatus.BLOCKED, DataHealthStatus.GAPPED}:
            counts["blocked"] += 1
        elif decision.data_health.status is not DataHealthStatus.LIVE:
            counts["stale"] += 1
        elif decision.signal_type.value == "LOW_ZONE_WATCH":
            counts["low_zone_watch"] += 1
        else:
            counts["normal"] += 1
    return DashboardCounts(**counts)


def _connection_status(summaries: tuple[SymbolSummaryView, ...]) -> ConnectionStatus:
    connected = sum(item.connected for item in summaries)
    if connected == len(summaries):
        return ConnectionStatus.CONNECTED
    if connected == 0:
        return ConnectionStatus.DISCONNECTED
    return ConnectionStatus.UNKNOWN


def _pagination(offset: int, limit: int) -> None:
    if type(offset) is not int or not 0 <= offset <= _MAX_PLAN_ROWS:
        raise ValueError("offset must be a bounded non-negative integer")
    if type(limit) is not int or not 1 <= limit <= _PLAN_PAGE_SIZE:
        raise ValueError("limit must be between 1 and 100")


def _observed_at(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() != timedelta(hours=8):
        raise ProjectionError("Read clock is not an Asia/Shanghai datetime")
    return value


__all__ = ["PersistentMonitorReadService"]
