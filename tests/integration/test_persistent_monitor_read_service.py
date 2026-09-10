"""Persistent dashboard and symbol projection availability/read tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from trade_plan_monitor.decision.models import (
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EvaluationResult,
    IntradayEvaluationIdentity,
    NextStep,
    NextStepCode,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.health import (
    LEGACY_RUNTIME_GENERATION,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.repositories import EvaluationKind
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.persistent_monitor_read_service import PersistentMonitorReadService
from trade_plan_monitor.web.routers.dashboard import (
    DashboardProjectionUnavailableResponse,
    DashboardResponse,
    ProjectionUnavailableReason,
)
from trade_plan_monitor.web.routers.health import RuntimeHealthResponse
from trade_plan_monitor.web.routers.symbols import (
    SymbolCollectionUnavailableResponse,
    SymbolDetailResponse,
    SymbolDetailUnavailableResponse,
    SymbolPage,
)

_ZONE = ZoneInfo("Asia/Shanghai")
_BUCKET_END = datetime(2026, 9, 5, 10, 0, tzinfo=_ZONE)
_NOW = datetime(2026, 9, 5, 10, 0, 18, tzinfo=_ZONE)
_RESTARTED_RUNTIME_GENERATION = UUID("00000000-0000-4000-8000-000000000002")


def _plan_and_source():
    path = Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
    source = path.read_text(encoding="utf-8")
    return load_plan_yaml(source), source


def _result() -> EvaluationResult:
    plan, _source = _plan_and_source()
    plan_hash = plan_sha256(plan)
    next_step = NextStep(code=NextStepCode.WAIT_FOR_COMPLETE_BAR)
    return EvaluationResult.build(
        snapshot=SymbolDecisionSnapshot(
            symbol=plan.symbol,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            plan_hash=plan_hash,
            evaluated_at=_NOW,
            market_data_at=_BUCKET_END,
            price_fen=6420,
            zone=DecisionZone.OUTSIDE,
            signal_type=SignalType.WAIT,
            position=PositionSummary(
                core_quantity=0,
                tactical_quantity=0,
                total_quantity=0,
                sellable_core_quantity=0,
                sellable_tactical_quantity=0,
            ),
            episode=None,
            risk=RiskStateSnapshot(
                symbol=plan.symbol,
                plan_hash=plan_hash,
                status=RiskStatus.CLEAR,
                breach_trade_date=None,
                prior_close_fen=6080,
                revision=0,
                updated_at=_BUCKET_END,
            ),
            data_health=DataHealthSnapshot(
                symbol=plan.symbol,
                status=DataHealthStatus.LIVE,
                latest_bar_end=_BUCKET_END,
                data_age_seconds=18,
                required_data_complete=True,
                fresh=True,
            ),
            condition_evidence=(),
            next_step=next_step,
        ),
        transitions=(),
        signal_intent=None,
        satisfied_conditions=(),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=plan_hash,
            symbol=plan.symbol,
            bucket_end=_BUCKET_END,
        ),
    )


def _setup(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    session_factory = create_session_factory(engine)

    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            session_factory,
            clock=lambda: _BUCKET_END - timedelta(minutes=1),
        )

    health = RuntimeHealthResponse.model_validate_json(
        json.dumps(
            {
                "status": "RUNNING",
                "readOnly": False,
                "observedAt": _NOW.isoformat(),
                "startedAt": _BUCKET_END.isoformat(),
                "stoppedAt": None,
                "lastCompletedMinute": None,
                "lastCompletedMinuteAgeSeconds": None,
                "latestEvaluationAt": None,
                "latestEvaluationAgeSeconds": None,
                "gaps": [],
                "nextRetryAt": None,
                "cooldownUntil": None,
                "providers": [],
                "executor": {"activeCount": 0, "maxWorkers": 1, "waitingCount": 0},
                "database": {
                    "status": "READY",
                    "walStatus": "READY",
                    "lastCheckpointAt": None,
                    "lastBackupAt": None,
                    "errorCode": None,
                },
                "delivery": {
                    "status": "READY",
                    "pendingCount": 0,
                    "failedCount": 0,
                    "lastDeliveredAt": None,
                    "nextRetryAt": None,
                    "errorCode": None,
                },
                "nextPollAt": (_NOW + timedelta(minutes=1)).isoformat(),
            }
        )
    )
    service = PersistentMonitorReadService(
        unit_of_work_factory,
        lambda: health,
        clock=lambda: _NOW,
    )
    return engine, unit_of_work_factory, service, health


def _seed_plan(unit_of_work_factory, *, active: bool) -> None:
    plan, source = _plan_and_source()
    with unit_of_work_factory() as work:
        work.plans.save_draft(plan, source_text=source)
        if active:
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
        work.commit()


def _seed_claim(unit_of_work_factory, *, complete: bool) -> EvaluationResult:
    result = _result()
    identity = result.evaluation_identity
    with unit_of_work_factory() as work:
        work.evaluations.claim(
            plan_hash=identity.plan_hash,
            symbol=identity.symbol,
            evaluation_kind=EvaluationKind.INTRADAY,
            bucket_end=identity.bucket_end,
            official_trade_date=None,
            formula_version=identity.formula_version,
            result_hash=result.result_hash,
            evaluated_at=result.snapshot.evaluated_at,
        )
        if complete:
            work.projections.add_evaluation_result(result)
            work.health.upsert_symbol(
                symbol=identity.symbol,
                status="LIVE",
                latest_bar_end=_BUCKET_END,
                data_age_seconds=18,
                gaps=(),
                error_streak=0,
                expected_revision=0,
            )
            work.projections.put_symbol_health(
                symbol=identity.symbol,
                revision=1,
                projection={
                    "symbol": identity.symbol,
                    "observedAt": _NOW,
                    "targetEnd": _BUCKET_END,
                    "status": "LIVE",
                    "latestBarEnd": _BUCKET_END,
                    "dataAgeSeconds": 18,
                    "requiredDataComplete": True,
                    "fresh": True,
                    "gaps": [],
                    "consecutiveIncompleteBuckets": 0,
                    "lastRequiredBucketEnd": _BUCKET_END,
                    "errorCode": None,
                    "actionable": True,
                },
                observed_at=_NOW,
            )
            event = work.events.append(
                MonitorEventDraft(
                    event_id=monitor_event_id(
                        MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                        identity.symbol,
                        identity.model_dump_json(),
                        result.result_hash,
                    ),
                    event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                    aggregate_id=identity.symbol,
                    payload=MonitorEventPayload(
                        entity_id=identity.symbol,
                        symbol=identity.symbol,
                        result_hash=result.result_hash,
                    ),
                    occurred_at=result.snapshot.evaluated_at,
                )
            )
            work.projections.advance_decision_head(
                result=result,
                event_sequence=event.sequence,
            )
        work.commit()
    return result


def _seed_dashboard_index_snapshots(unit_of_work_factory) -> None:
    with unit_of_work_factory() as work:
        for index, index_code in enumerate(DASHBOARD_INDEX_CODES):
            snapshot = build_market_index_snapshot(
                index_code=index_code,
                decision_cutoff=_BUCKET_END,
                requests=(),
                five_minute_bars=(),
                official_daily_bars=(),
                content_revision=index + 1,
                observed_at=_NOW,
                observed_no_later_than=_NOW,
            )
            work.projections.put_market_index_snapshot(
                snapshot,
                provider_content_revision=snapshot.cache_key.provider_content_revision,
            )
            work.projections.advance_market_index_head(
                snapshot,
                provider_content_revision=snapshot.cache_key.provider_content_revision,
            )
        work.commit()


def _put_public_health(
    unit_of_work_factory,
    *,
    observed_at: datetime,
    revision: int,
    status: str = "LIVE",
) -> None:
    plan, _source = _plan_and_source()
    live = status == "LIVE"
    gapped = status == "GAPPED"
    latest_bar_end = _BUCKET_END - timedelta(minutes=1) if gapped else _BUCKET_END
    if not (live or gapped):
        latest_bar_end = None
    with unit_of_work_factory() as work:
        current = work.health.get_symbol(plan.symbol)
        persisted = work.health.upsert_symbol(
            symbol=plan.symbol,
            status=status,
            latest_bar_end=latest_bar_end,
            data_age_seconds=(
                0
                if latest_bar_end is None
                else int((observed_at - latest_bar_end).total_seconds())
            ),
            gaps=(_BUCKET_END.isoformat(),) if gapped else (),
            error_streak=0 if live else 1,
            expected_revision=0 if current is None else current.revision,
        )
        assert persisted.revision == revision
        work.projections.put_symbol_health(
            symbol=plan.symbol,
            revision=revision,
            projection={
                "symbol": plan.symbol,
                "observedAt": observed_at,
                "targetEnd": _BUCKET_END,
                "status": status,
                "latestBarEnd": latest_bar_end,
                "dataAgeSeconds": (
                    int((observed_at - latest_bar_end).total_seconds())
                    if latest_bar_end is not None
                    else None
                ),
                "requiredDataComplete": live,
                "fresh": live,
                "gaps": [_BUCKET_END] if gapped else [],
                "consecutiveIncompleteBuckets": 1 if gapped else 0,
                "lastRequiredBucketEnd": _BUCKET_END if live or gapped else None,
                "errorCode": (
                    None
                    if live
                    else "INCOMPLETE_BUCKET" if gapped else "PROVIDER_BLOCKED"
                ),
                "actionable": live,
            },
            observed_at=observed_at,
        )
        work.commit()


def test_empty_database_returns_typed_unavailable_and_delegates_runtime_health(
    tmp_path: Path,
) -> None:
    engine, _factory, service, health = _setup(tmp_path)
    try:
        dashboard = asyncio.run(service.get_dashboard())
        symbols = asyncio.run(service.list_symbols(offset=0, limit=20))

        assert dashboard == DashboardProjectionUnavailableResponse(
            availability="UNAVAILABLE",
            reason=ProjectionUnavailableReason.EMPTY_DATABASE,
            observed_at=_NOW,
            sequence=0,
        )
        assert symbols == SymbolCollectionUnavailableResponse(
            availability="UNAVAILABLE",
            reason=ProjectionUnavailableReason.EMPTY_DATABASE,
            observed_at=_NOW,
            sequence=0,
        )
        assert asyncio.run(service.get_symbol(symbol="003043.SZ")) is None
        assert asyncio.run(service.get_health()) == health
    finally:
        engine.dispose()


def test_dashboard_includes_fixed_display_indexes_without_plan_bindings(tmp_path: Path) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        _seed_dashboard_index_snapshots(factory)

        dashboard = asyncio.run(service.get_dashboard())

        assert isinstance(dashboard, DashboardResponse)
        assert tuple(item.index_code for item in dashboard.market_indexes) == tuple(
            sorted(DASHBOARD_INDEX_CODES, key=lambda item: item.value)
        )
        assert all(item.mapped_symbol_count == 0 for item in dashboard.market_indexes)
    finally:
        engine.dispose()


def test_known_inactive_and_active_legacy_symbols_have_exact_unavailable_reasons(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=False)

        dashboard = asyncio.run(service.get_dashboard())
        inactive_detail = asyncio.run(service.get_symbol(symbol=plan.symbol))
        assert isinstance(dashboard, DashboardProjectionUnavailableResponse)
        assert dashboard.reason is ProjectionUnavailableReason.NO_ACTIVE_PLANS
        assert isinstance(inactive_detail, SymbolDetailUnavailableResponse)
        assert inactive_detail.reason is ProjectionUnavailableReason.NO_ACTIVE_PLAN
        assert inactive_detail.symbol == plan.symbol
        assert asyncio.run(service.get_symbol(symbol="003044.SZ")) is None

        with factory() as work:
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()
        _seed_claim(factory, complete=False)

        awaiting = asyncio.run(service.get_symbol(symbol=plan.symbol))
        assert isinstance(awaiting, SymbolDetailUnavailableResponse)
        assert awaiting.reason is ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION
        assert awaiting.symbol == plan.symbol
    finally:
        engine.dispose()


def test_complete_head_builds_dashboard_collection_and_detail_from_one_durable_result(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        result = _seed_claim(factory, complete=True)

        dashboard = asyncio.run(service.get_dashboard())
        symbols = asyncio.run(service.list_symbols(offset=0, limit=20))
        detail = asyncio.run(service.get_symbol(symbol=plan.symbol))

        assert isinstance(dashboard, DashboardResponse)
        assert isinstance(symbols, SymbolPage)
        assert isinstance(detail, SymbolDetailResponse)
        assert dashboard.sequence >= 1
        assert dashboard.symbols == symbols.items == (detail.summary,)
        assert detail.position_lots == ()
        assert detail.summary.symbol == plan.symbol
        assert detail.summary.name == plan.name
        assert detail.summary.decision.result_hash == result.result_hash
        assert detail.summary.decision.plan_hash == plan_sha256(plan)
        assert detail.summary.decision.price_fen == 6420
    finally:
        engine.dispose()


def test_decision_detail_keeps_its_immutable_position_lots_after_a_later_buy(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        with factory() as work:
            work.positions.record_buy(
                symbol=plan.symbol,
                bucket="CORE",
                quantity=100,
                acquired_trade_date=_BUCKET_END.date(),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=1_000,
            )
            work.commit()

        detail = asyncio.run(service.get_symbol(symbol=plan.symbol))

        assert isinstance(detail, SymbolDetailResponse)
        assert detail.position_lots == ()
        assert detail.summary.decision.position.total_quantity == 0
    finally:
        engine.dispose()


def test_corrupt_immutable_position_lots_fail_closed_as_sanitized_503(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE evaluation_result SET position_lots_json = '{}'"),
            )

        with pytest.raises(ApiError) as captured:
            asyncio.run(service.get_symbol(symbol=plan.symbol))

        assert captured.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
        assert "position" not in str(captured.value).lower()
    finally:
        engine.dispose()


def test_connected_uses_current_health_and_the_current_runtime_generation(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        assert isinstance(asyncio.run(service.get_dashboard()), DashboardResponse)

        _put_public_health(
            factory,
            observed_at=_NOW,
            revision=2,
            status="BLOCKED",
        )
        blocked = asyncio.run(service.get_dashboard())
        assert isinstance(blocked, DashboardResponse)
        assert blocked.connection_status.value == "DISCONNECTED"
        assert blocked.symbols[0].connected is False

        _put_public_health(
            factory,
            observed_at=_NOW + timedelta(seconds=2),
            revision=3,
        )
        restarted_health = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            started_at=_NOW + timedelta(seconds=3),
            next_poll_at=_NOW + timedelta(minutes=1),
            runtime_generation=LEGACY_RUNTIME_GENERATION,
        )
        restarted = PersistentMonitorReadService(
            factory,
            lambda: restarted_health,
            clock=lambda: _NOW + timedelta(seconds=6),
        )
        before_fresh_batch = asyncio.run(restarted.get_dashboard())
        assert isinstance(before_fresh_batch, DashboardResponse)
        assert before_fresh_batch.connection_status.value == "DISCONNECTED"

        _put_public_health(
            factory,
            observed_at=_NOW + timedelta(seconds=5),
            revision=4,
        )
        after_fresh_batch = asyncio.run(restarted.get_dashboard())
        assert isinstance(after_fresh_batch, DashboardResponse)
        assert after_fresh_batch.connection_status.value == "CONNECTED"
        assert after_fresh_batch.symbols[0].connected is True
        assert after_fresh_batch.symbols[0].decision.data_health.status is DataHealthStatus.LIVE
    finally:
        engine.dispose()


def test_runtime_health_provider_failure_is_a_sanitized_503(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    sentinel = "sensitive-runtime-health-provider-detail"

    def broken_health() -> object:
        raise RuntimeError(sentinel)

    service = PersistentMonitorReadService(factory, broken_health, clock=lambda: _NOW)
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)

        with pytest.raises(ApiError) as captured:
            asyncio.run(service.get_dashboard())

        assert captured.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
        assert sentinel not in str(captured.value)
        assert captured.value.__cause__ is None
    finally:
        engine.dispose()


def test_overdue_runtime_progress_disconnects_http_reads(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    stalled_at = _NOW + timedelta(minutes=10)
    stalled_health = SimpleNamespace(
        status=RuntimeServiceStatus.RUNNING,
        read_only=False,
        observed_at=stalled_at,
        started_at=_BUCKET_END,
        next_poll_at=_NOW + timedelta(minutes=1),
        runtime_generation=LEGACY_RUNTIME_GENERATION,
    )
    service = PersistentMonitorReadService(
        factory,
        lambda: stalled_health,
        clock=lambda: stalled_at,
    )
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)

        dashboard = asyncio.run(service.get_dashboard())

        assert isinstance(dashboard, DashboardResponse)
        assert dashboard.connection_status.value == "DISCONNECTED"
        assert dashboard.symbols[0].connected is False
        assert asyncio.run(service.get_symbol_health(symbol=plan.symbol)) is None
    finally:
        engine.dispose()


def test_corrupt_monitor_sequence_is_a_sanitized_503(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    sentinel = "Monitor sequence state is invalid"
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM monitor_sequence"))

        with pytest.raises(ApiError) as captured:
            asyncio.run(service.get_dashboard())

        assert captured.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
        assert sentinel not in str(captured.value)
        assert captured.value.__cause__ is None
    finally:
        engine.dispose()


def test_reactivation_never_reuses_prior_generation_projections(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    runtime = RuntimeEvaluationService(
        fetch_minutes=lambda _symbol, _target: (),  # type: ignore[arg-type]
        unit_of_work_factory=factory,
        context_builder=lambda _plan, _facts: None,  # type: ignore[arg-type]
        committed_event_publisher=lambda _event: None,
    )
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        with factory() as work:
            work.plans.deactivate(plan.symbol, expected_revision=1)
            work.plans.activate(
                plan,
                expected_revision=2,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()

        rolled_back_runtime = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            observed_at=_NOW + timedelta(seconds=30),
            started_at=_NOW - timedelta(seconds=10),
            next_poll_at=_NOW + timedelta(minutes=1),
            runtime_generation=LEGACY_RUNTIME_GENERATION,
        )
        service = PersistentMonitorReadService(
            factory,
            lambda: rolled_back_runtime,
            clock=lambda: _NOW + timedelta(seconds=30),
        )

        dashboard = asyncio.run(service.get_dashboard())
        restored = runtime.load_persisted_symbol_health((plan.symbol,))

        assert isinstance(dashboard, DashboardProjectionUnavailableResponse)
        assert dashboard.reason is ProjectionUnavailableReason.AWAITING_FIRST_EVALUATION
        assert asyncio.run(service.get_symbol_health(symbol=plan.symbol)) is None
        assert restored[0].activation_revision == 3
        assert restored[0].snapshot is None
    finally:
        engine.dispose()


def test_direct_symbol_health_rejects_a_projection_from_the_callers_future(
    tmp_path: Path,
) -> None:
    engine, factory, _service, health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        _put_public_health(
            factory,
            observed_at=_NOW + timedelta(seconds=30),
            revision=2,
        )
        rolled_back = PersistentMonitorReadService(
            factory,
            lambda: health,
            clock=lambda: _NOW,
        )

        assert asyncio.run(rolled_back.get_symbol_health(symbol=plan.symbol)) is None
        with pytest.raises(ApiError) as captured:
            asyncio.run(rolled_back.get_dashboard())
        assert captured.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
    finally:
        engine.dispose()


def test_clock_rollback_cannot_resurrect_a_predecessor_runtime_health_row(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        replacement = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            started_at=_NOW - timedelta(seconds=8),
            next_poll_at=_NOW + timedelta(minutes=1),
            runtime_generation=_RESTARTED_RUNTIME_GENERATION,
        )
        service = PersistentMonitorReadService(
            factory,
            lambda: replacement,
            clock=lambda: _NOW + timedelta(seconds=2),
        )

        assert asyncio.run(service.get_symbol_health(symbol=plan.symbol)) is None
        dashboard = asyncio.run(service.get_dashboard())
        assert isinstance(dashboard, DashboardResponse)
        assert dashboard.connection_status.value == "DISCONNECTED"
        assert dashboard.symbols[0].connected is False
    finally:
        engine.dispose()


def test_same_generation_health_at_the_runtime_start_boundary_is_current(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        runtime = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            started_at=_NOW,
            next_poll_at=_NOW + timedelta(minutes=1),
            runtime_generation=LEGACY_RUNTIME_GENERATION,
        )
        service = PersistentMonitorReadService(
            factory,
            lambda: runtime,
            clock=lambda: _NOW + timedelta(seconds=10),
        )

        direct = asyncio.run(service.get_symbol_health(symbol=plan.symbol))
        dashboard = asyncio.run(service.get_dashboard())

        assert direct is not None
        assert direct.observed_at == _NOW
        assert isinstance(dashboard, DashboardResponse)
        assert dashboard.connection_status.value == "CONNECTED"
        assert dashboard.symbols[0].connected is True
    finally:
        engine.dispose()


def test_persisted_live_and_gapped_health_round_trip_through_strict_json(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()

    async def unused_fetch(_symbol: str, _target: datetime):
        raise AssertionError("health restoration must not fetch")

    runtime = RuntimeEvaluationService(
        fetch_minutes=unused_fetch,
        unit_of_work_factory=factory,
        context_builder=lambda _plan, _facts: None,  # type: ignore[arg-type]
        committed_event_publisher=lambda _event: None,
    )
    try:
        _seed_plan(factory, active=True)
        _put_public_health(factory, observed_at=_NOW, revision=1)
        live = runtime.load_persisted_symbol_health((plan.symbol,))
        assert live[0].snapshot is not None
        assert live[0].snapshot.data_health.status is DataHealthStatus.LIVE

        _put_public_health(
            factory,
            observed_at=_NOW + timedelta(minutes=5),
            revision=2,
            status="GAPPED",
        )
        gapped = runtime.load_persisted_symbol_health((plan.symbol,))
        assert gapped[0].snapshot is not None
        assert gapped[0].snapshot.data_health.status is DataHealthStatus.GAPPED
        assert gapped[0].snapshot.gaps == (_BUCKET_END,)
        assert gapped[0].snapshot.consecutive_incomplete_buckets == 1
    finally:
        engine.dispose()


def test_close_pending_restores_the_exact_public_health_json_after_restart(
    tmp_path: Path,
) -> None:
    engine, factory, service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    close_time = _BUCKET_END.replace(hour=15, minute=20)
    try:
        _seed_plan(factory, active=True)
        _put_public_health(factory, observed_at=_NOW, revision=1, status="GAPPED")
        with factory() as work:
            RuntimeEvaluationService._mark_close_pending(
                work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time,
                activation_revision=1,
            )
            work.commit()

        with factory() as restarted:
            RuntimeEvaluationService._clear_close_pending(
                restarted,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time + timedelta(minutes=1),
                activation_revision=1,
            )
            restarted.commit()

        restored = asyncio.run(service.get_symbol_health(symbol=plan.symbol))
        assert restored is not None
        assert restored.status is DataHealthStatus.GAPPED
        assert restored.observed_at == _NOW
        assert restored.gaps == (_BUCKET_END,)
        with factory() as work:
            assert (
                work.projections.get_pending_official_close(
                    symbol=plan.symbol,
                    trade_date=_BUCKET_END.date(),
                )
                is None
            )
    finally:
        engine.dispose()


def test_close_pending_without_public_projection_restores_exact_legacy_health(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    close_time = _BUCKET_END.replace(hour=15, minute=20)
    try:
        _seed_plan(factory, active=True)
        with factory() as work:
            before = work.health.upsert_symbol(
                symbol=plan.symbol,
                status="GAPPED",
                latest_bar_end=_BUCKET_END - timedelta(minutes=1),
                data_age_seconds=19,
                gaps=(_BUCKET_END.isoformat(),),
                error_streak=7,
                expected_revision=0,
            )
            RuntimeEvaluationService._mark_close_pending(
                work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time,
                activation_revision=1,
            )
            work.commit()

        with factory() as restarted:
            RuntimeEvaluationService._clear_close_pending(
                restarted,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time + timedelta(minutes=1),
                activation_revision=1,
            )
            restarted.commit()

        with factory() as work:
            restored = work.health.get_symbol(plan.symbol)
            projection = work.projections.get_symbol_health(plan.symbol)
        assert restored is not None
        assert restored.status is before.status
        assert restored.latest_bar_end == before.latest_bar_end
        assert restored.data_age_seconds == before.data_age_seconds
        assert restored.gap_json == before.gap_json
        assert restored.error_streak == before.error_streak
        assert projection is not None
        assert projection.projection["status"] == "GAPPED"
        assert projection.projection["gaps"] == [_BUCKET_END.isoformat()]
        assert projection.projection["consecutiveIncompleteBuckets"] == 7
    finally:
        engine.dispose()


def test_close_pending_restart_retains_the_predecessor_projection_generation(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    close_time = _BUCKET_END.replace(hour=15, minute=20)
    try:
        _seed_plan(factory, active=True)
        _seed_claim(factory, complete=True)
        with factory() as work:
            RuntimeEvaluationService._mark_close_pending(
                work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time,
                activation_revision=1,
                runtime_generation=LEGACY_RUNTIME_GENERATION,
            )
            work.commit()

        with factory() as restarted:
            RuntimeEvaluationService._clear_close_pending(
                restarted,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time + timedelta(minutes=1),
                activation_revision=1,
                runtime_generation=_RESTARTED_RUNTIME_GENERATION,
            )
            restarted.commit()
            restored = restarted.projections.get_symbol_health(plan.symbol)

        replacement = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            started_at=close_time - timedelta(seconds=30),
            next_poll_at=close_time + timedelta(minutes=2),
            runtime_generation=_RESTARTED_RUNTIME_GENERATION,
        )
        service = PersistentMonitorReadService(
            factory,
            lambda: replacement,
            clock=lambda: close_time + timedelta(minutes=1),
        )

        assert restored is not None
        assert restored.runtime_generation == LEGACY_RUNTIME_GENERATION
        assert asyncio.run(service.get_symbol_health(symbol=plan.symbol)) is None
        dashboard = asyncio.run(service.get_dashboard())
        assert isinstance(dashboard, DashboardResponse)
        assert dashboard.connection_status.value == "DISCONNECTED"
        assert dashboard.symbols[0].connected is False
    finally:
        engine.dispose()


def test_close_pending_restart_cannot_manufacture_live_from_legacy_only_health(
    tmp_path: Path,
) -> None:
    engine, factory, _service, _health = _setup(tmp_path)
    plan, _source = _plan_and_source()
    close_time = _BUCKET_END.replace(hour=15, minute=20)
    try:
        _seed_plan(factory, active=True)
        with factory() as work:
            before = work.health.upsert_symbol(
                symbol=plan.symbol,
                status="LIVE",
                latest_bar_end=_BUCKET_END,
                data_age_seconds=18,
                gaps=(),
                error_streak=0,
                expected_revision=0,
            )
            RuntimeEvaluationService._mark_close_pending(
                work,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time,
                activation_revision=1,
                runtime_generation=LEGACY_RUNTIME_GENERATION,
            )
            work.commit()

        with factory() as restarted:
            RuntimeEvaluationService._clear_close_pending(
                restarted,
                plan=plan,
                symbol=plan.symbol,
                trade_date=_BUCKET_END.date(),
                evaluated_at=close_time + timedelta(minutes=1),
                activation_revision=1,
                runtime_generation=_RESTARTED_RUNTIME_GENERATION,
            )
            restarted.commit()
            restored = restarted.health.get_symbol(plan.symbol)
            projection = restarted.projections.get_symbol_health(plan.symbol)

        assert restored is not None
        assert restored.status is before.status
        assert restored.latest_bar_end == before.latest_bar_end
        assert restored.data_age_seconds == before.data_age_seconds
        assert restored.gap_json == before.gap_json
        assert restored.error_streak == before.error_streak
        assert projection is not None
        assert projection.runtime_generation == _RESTARTED_RUNTIME_GENERATION
        assert projection.projection["status"] == "STALE"
        assert projection.projection["requiredDataComplete"] is False
        assert projection.projection["fresh"] is False
        assert projection.projection["actionable"] is False
        assert projection.projection["errorCode"] == "STALE_DATA"

        replacement = SimpleNamespace(
            status=RuntimeServiceStatus.RUNNING,
            read_only=False,
            started_at=close_time - timedelta(seconds=30),
            next_poll_at=close_time + timedelta(minutes=2),
            runtime_generation=_RESTARTED_RUNTIME_GENERATION,
        )
        service = PersistentMonitorReadService(
            factory,
            lambda: replacement,
            clock=lambda: close_time + timedelta(minutes=1),
        )
        public = asyncio.run(service.get_symbol_health(symbol=plan.symbol))
        assert public is not None
        assert public.status is DataHealthStatus.STALE
        assert public.actionable is False
    finally:
        engine.dispose()
