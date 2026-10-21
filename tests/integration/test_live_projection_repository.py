"""Durable live projection repositories and transaction-boundary tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, text

from trade_plan_monitor.decision.models import (
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EvaluationResult,
    IntradayEvaluationIdentity,
    NextStep,
    NextStepCode,
    OfficialCloseEvaluationIdentity,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
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
from trade_plan_monitor.state.models import PositionBucket
from trade_plan_monitor.state.projections import (
    ProjectionError,
    ProjectionMissingDependencyError,
    ProjectionRevisionConflictError,
)
from trade_plan_monitor.state.repositories import EvaluationKind, PositionLotRecord
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_ZONE = ZoneInfo("Asia/Shanghai")
_BUCKET_END = datetime(2026, 9, 5, 10, 0, tzinfo=_ZONE)
_EVALUATED_AT = datetime(2026, 9, 5, 10, 0, 18, tzinfo=_ZONE)


def _plan():
    path = Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
    return load_plan_yaml(path.read_text(encoding="utf-8"))


def _result() -> EvaluationResult:
    plan = _plan()
    plan_hash = plan_sha256(plan)
    next_step = NextStep(code=NextStepCode.WAIT_FOR_COMPLETE_BAR)
    return EvaluationResult.build(
        snapshot=SymbolDecisionSnapshot(
            symbol=plan.symbol,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            plan_hash=plan_hash,
            evaluated_at=_EVALUATED_AT,
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


def _unit_of_work(path: Path) -> tuple[object, object]:
    engine = create_sqlite_engine(path)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    return engine, lambda: SqlAlchemyUnitOfWork(factory, clock=lambda: _EVALUATED_AT)


def _claim_and_event(work: SqlAlchemyUnitOfWork, result: EvaluationResult):
    identity = result.evaluation_identity
    claim = work.evaluations.claim(
        plan_hash=identity.plan_hash,
        symbol=identity.symbol,
        evaluation_kind=EvaluationKind.INTRADAY,
        bucket_end=identity.bucket_end,
        official_trade_date=None,
        formula_version=identity.formula_version,
        result_hash=result.result_hash,
        evaluated_at=result.snapshot.evaluated_at,
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
    return claim, event


def test_complete_result_and_head_survive_restart_with_exact_identity(tmp_path: Path) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    result = _result()

    try:
        with factory() as work:
            claim, event = _claim_and_event(work, result)
            assert claim.created is True
            assert work.projections.add_evaluation_result(result) is True
            head = work.projections.advance_decision_head(
                result=result,
                event_sequence=event.sequence,
            )
            work.commit()

        with factory() as restarted:
            restored = restarted.projections.get_decision_head(result.snapshot.symbol)
            assert restored == head
            assert restored is not None
            assert restored.result == result
            assert restored.result.result_hash == result.result_hash
            assert restored.event_sequence == event.sequence
            assert restarted.events.current_sequence() == event.sequence
    finally:
        engine.dispose()


def test_delayed_official_result_validates_t_plus_one_against_its_target_date(
    tmp_path: Path,
) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    base = _result()
    official_date = date(2026, 9, 4)
    evaluated_at = datetime(2026, 9, 5, 10, 0, tzinfo=_ZONE)
    market_data_at = datetime(2026, 9, 4, 15, 0, tzinfo=_ZONE)
    snapshot = base.snapshot.model_copy(
        update={
            "evaluated_at": evaluated_at,
            "market_data_at": market_data_at,
            "position": PositionSummary(
                core_quantity=100,
                tactical_quantity=0,
                total_quantity=100,
                sellable_core_quantity=0,
                sellable_tactical_quantity=0,
            ),
            "data_health": DataHealthSnapshot(
                symbol=base.snapshot.symbol,
                status=DataHealthStatus.STALE,
                latest_bar_end=market_data_at,
                data_age_seconds=int((evaluated_at - market_data_at).total_seconds()),
                required_data_complete=True,
                fresh=False,
            ),
        }
    )
    result = EvaluationResult.build(
        snapshot=snapshot,
        transitions=base.transitions,
        signal_intent=base.signal_intent,
        satisfied_conditions=base.satisfied_conditions,
        unmet_conditions=base.unmet_conditions,
        blockers=base.blockers,
        next_step=base.next_step,
        evaluation_identity=OfficialCloseEvaluationIdentity(
            plan_hash=snapshot.plan_hash,
            symbol=snapshot.symbol,
            official_trade_date=official_date,
        ),
    )
    lot = PositionLotRecord(
        id="00000000-0000-4000-8000-000000000001",
        symbol=snapshot.symbol,
        bucket=PositionBucket.CORE,
        quantity=100,
        remaining_qty=100,
        acquired_trade_date=official_date,
        cost_fen=6400,
        related_alert_id=None,
        closed_at=None,
    )
    try:
        with factory() as work:
            identity = result.evaluation_identity
            work.evaluations.claim(
                plan_hash=identity.plan_hash,
                symbol=identity.symbol,
                evaluation_kind=EvaluationKind.OFFICIAL_CLOSE,
                bucket_end=None,
                official_trade_date=identity.official_trade_date,
                formula_version=identity.formula_version,
                result_hash=result.result_hash,
                evaluated_at=evaluated_at,
            )
            assert work.projections.add_evaluation_result(result, position_lots=(lot,)) is True
            work.commit()
    finally:
        engine.dispose()


def test_decision_head_never_regresses_to_an_older_target_with_later_evaluation(
    tmp_path: Path,
) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    base = _result()

    def result_at(bucket_end: datetime, evaluated_at: datetime) -> EvaluationResult:
        snapshot = base.snapshot.model_copy(
            update={
                "evaluated_at": evaluated_at,
                "market_data_at": bucket_end,
                "data_health": DataHealthSnapshot(
                    symbol=base.snapshot.symbol,
                    status=DataHealthStatus.LIVE,
                    latest_bar_end=bucket_end,
                    data_age_seconds=int((evaluated_at - bucket_end).total_seconds()),
                    required_data_complete=True,
                    fresh=True,
                ),
            }
        )
        return EvaluationResult.build(
            snapshot=snapshot,
            transitions=base.transitions,
            signal_intent=base.signal_intent,
            satisfied_conditions=base.satisfied_conditions,
            unmet_conditions=base.unmet_conditions,
            blockers=base.blockers,
            next_step=base.next_step,
            evaluation_identity=IntradayEvaluationIdentity(
                plan_hash=snapshot.plan_hash,
                symbol=snapshot.symbol,
                bucket_end=bucket_end,
            ),
        )

    newer = result_at(
        _BUCKET_END.replace(minute=5),
        _BUCKET_END.replace(minute=5, second=18),
    )
    older_late = result_at(
        _BUCKET_END,
        _BUCKET_END.replace(minute=10),
    )
    try:
        with factory() as work:
            _, newer_event = _claim_and_event(work, newer)
            work.projections.add_evaluation_result(newer)
            newer_head = work.projections.advance_decision_head(
                result=newer,
                event_sequence=newer_event.sequence,
            )
            work.commit()

        with pytest.raises(ProjectionRevisionConflictError):
            with factory() as work:
                _, older_event = _claim_and_event(work, older_late)
                work.projections.add_evaluation_result(older_late)
                work.projections.advance_decision_head(
                    result=older_late,
                    event_sequence=older_event.sequence,
                )

        with factory() as work:
            assert work.projections.get_decision_head(base.snapshot.symbol) == newer_head
    finally:
        engine.dispose()


def test_legacy_hash_only_ledger_never_becomes_a_complete_projection(tmp_path: Path) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    result = _result()

    try:
        with factory() as work:
            identity = result.evaluation_identity
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
            work.commit()

        with factory() as restarted:
            assert restarted.projections.get_decision_head(result.snapshot.symbol) is None
            assert restarted.projections.get_evaluation_result(
                result.evaluation_identity
            ) is None
    finally:
        engine.dispose()


def test_rollback_removes_claim_result_head_event_and_sequence_together(tmp_path: Path) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    result = _result()

    try:
        with factory() as work:
            _, event = _claim_and_event(work, result)
            work.projections.add_evaluation_result(result)
            work.projections.advance_decision_head(
                result=result,
                event_sequence=event.sequence,
            )
            work.rollback()

        with factory() as restarted:
            identity = result.evaluation_identity
            assert not restarted.evaluations.has_claim(
                plan_hash=identity.plan_hash,
                symbol=identity.symbol,
                evaluation_kind=EvaluationKind.INTRADAY,
                bucket_end=identity.bucket_end,
                official_trade_date=None,
                formula_version=identity.formula_version,
            )
            assert restarted.projections.get_decision_head(identity.symbol) is None
            assert restarted.events.current_sequence() == 0
    finally:
        engine.dispose()


def test_health_and_pending_close_projections_are_revision_safe_and_recoverable(
    tmp_path: Path,
) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    result = _result()
    payload = {
        "symbol": result.snapshot.symbol,
        "status": "CLOSE_PENDING",
        "observedAt": _EVALUATED_AT.isoformat(),
    }

    try:
        with pytest.raises(ValueError, match="UUIDv4"):
            with factory() as work:
                work.projections.put_symbol_health(
                    symbol=result.snapshot.symbol,
                    revision=1,
                    runtime_generation=UUID("00000000-0000-1000-8000-000000000001"),
                    projection=payload,
                    observed_at=_EVALUATED_AT,
                )

        with factory() as work:
            health = work.projections.put_symbol_health(
                symbol=result.snapshot.symbol,
                revision=1,
                projection=payload,
                observed_at=_EVALUATED_AT,
            )
            pending = work.projections.put_pending_official_close(
                plan_hash=result.snapshot.plan_hash,
                symbol=result.snapshot.symbol,
                trade_date=date(2026, 9, 5),
                formula_version="ta-v1",
                pending={"resumeStatus": "LIVE", "resumeGaps": []},
                observed_at=_EVALUATED_AT,
            )
            work.commit()

        with factory() as restarted:
            assert restarted.projections.get_symbol_health(result.snapshot.symbol) == health
            assert restarted.projections.get_pending_official_close(
                symbol=result.snapshot.symbol,
                trade_date=date(2026, 9, 5),
            ) == pending
            with pytest.raises(ProjectionRevisionConflictError):
                restarted.projections.put_symbol_health(
                    symbol=result.snapshot.symbol,
                    revision=1,
                    projection={**payload, "status": "LIVE"},
                    observed_at=_EVALUATED_AT,
                )

        with factory() as work:
            assert work.projections.clear_pending_official_close(
                plan_hash=result.snapshot.plan_hash,
                symbol=result.snapshot.symbol,
                trade_date=date(2026, 9, 5),
                formula_version="ta-v1",
            ) is True
            work.commit()

        with factory() as restarted:
            assert restarted.projections.get_pending_official_close(
                symbol=result.snapshot.symbol,
                trade_date=date(2026, 9, 5),
            ) is None
    finally:
        engine.dispose()


def test_symbol_health_row_and_payload_observation_are_one_exact_identity(
    tmp_path: Path,
) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    result = _result()
    payload = {
        "symbol": result.snapshot.symbol,
        "status": "LIVE",
        "observedAt": _EVALUATED_AT.isoformat(),
    }
    try:
        with pytest.raises(ValueError, match="observation does not match"):
            with factory() as work:
                work.projections.put_symbol_health(
                    symbol=result.snapshot.symbol,
                    revision=1,
                    projection={
                        **payload,
                        "observedAt": _EVALUATED_AT.replace(second=19).isoformat(),
                    },
                    observed_at=_EVALUATED_AT,
                )

        with factory() as work:
            work.projections.put_symbol_health(
                symbol=result.snapshot.symbol,
                revision=1,
                projection=payload,
                observed_at=_EVALUATED_AT,
            )
            work.commit()

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE symbol_health_projection "
                    "SET observed_at = :observed_at WHERE symbol = :symbol"
                ),
                {
                    "observed_at": _EVALUATED_AT.replace(second=19).isoformat(),
                    "symbol": result.snapshot.symbol,
                },
            )
        with factory() as restarted, pytest.raises(ProjectionError):
            restarted.projections.get_symbol_health(result.snapshot.symbol)
    finally:
        engine.dispose()


def test_market_index_snapshot_and_head_preserve_every_hash_and_revision(tmp_path: Path) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    snapshot = build_market_index_snapshot(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        decision_cutoff=_BUCKET_END,
        requests=(),
        five_minute_bars=(),
        official_daily_bars=(),
        content_revision=7,
        observed_at=_EVALUATED_AT,
        observed_no_later_than=_EVALUATED_AT,
    )

    try:
        with factory() as work:
            created = work.projections.put_market_index_snapshot(
                snapshot,
                provider_content_revision=7,
            )
            head = work.projections.advance_market_index_head(
                snapshot,
                provider_content_revision=7,
            )
            work.commit()

        assert created is True
        with factory() as restarted:
            restored = restarted.projections.get_market_index_head(
                mapping_version=snapshot.mapping_version,
                index_code=snapshot.index_code,
                decision_cutoff=snapshot.decision_cutoff,
                request_set_hash=snapshot.request_set_hash,
            )
            assert restored == head
            assert restored is not None
            assert restored.snapshot == snapshot
            assert restored.provider_content_revision == 7
            assert restored.snapshot.revision == snapshot.revision
            assert restored.snapshot.bar_set_hash == snapshot.bar_set_hash
            assert restored.snapshot.request_set_hash == snapshot.request_set_hash
            assert (
                restored.snapshot.formula_definition_hash
                == snapshot.formula_definition_hash
            )
    finally:
        engine.dispose()


def test_latest_dashboard_index_snapshots_are_loaded_in_display_order(tmp_path: Path) -> None:
    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    snapshots = tuple(
        build_market_index_snapshot(
            index_code=index_code,
            decision_cutoff=_BUCKET_END,
            requests=(),
            five_minute_bars=(),
            official_daily_bars=(),
            content_revision=index + 1,
            observed_at=_EVALUATED_AT,
            observed_no_later_than=_EVALUATED_AT,
        )
        for index, index_code in enumerate(DASHBOARD_INDEX_CODES[:2])
    )

    try:
        with factory() as work:
            for snapshot in snapshots:
                work.projections.put_market_index_snapshot(
                    snapshot,
                    provider_content_revision=snapshot.cache_key.provider_content_revision,
                )
                work.projections.advance_market_index_head(
                    snapshot,
                    provider_content_revision=snapshot.cache_key.provider_content_revision,
                )
            work.commit()

        with factory() as restarted:
            restored = restarted.projections.list_latest_market_index_snapshots(
                mapping_version=snapshots[0].mapping_version,
                index_codes=DASHBOARD_INDEX_CODES,
            )

        assert tuple(record.snapshot.index_code for record in restored) == DASHBOARD_INDEX_CODES[:2]
        assert tuple(record.snapshot.snapshot_hash for record in restored) == tuple(
            snapshot.snapshot_hash for snapshot in snapshots
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", [None, "canonical", "missing", "identity"])
def test_latest_indexes_batch_all_history_and_reject_unselected_damage(
    tmp_path, monkeypatch, damage,
):
    """The newest head cannot hide corrupt older evidence or cause N+1 reads."""
    import sqlite3

    from trade_plan_monitor.state import projections

    engine, factory = _unit_of_work(tmp_path / "monitor.db")
    snapshots = tuple(
        build_market_index_snapshot(
            index_code=DASHBOARD_INDEX_CODES[0],
            decision_cutoff=_BUCKET_END + timedelta(minutes=5 * index),
            requests=(), five_minute_bars=(), official_daily_bars=(),
            content_revision=130 - index,
            observed_at=_EVALUATED_AT + timedelta(minutes=5 * index),
            observed_no_later_than=_EVALUATED_AT + timedelta(minutes=5 * index),
        )
        for index in range(130)
    )
    queries = []
    verified = []
    decode = projections._market_index_from_row

    def observed_decode(row):
        verified.append(row.snapshot_hash)
        return decode(row)

    monkeypatch.setattr(projections, "_market_index_from_row", observed_decode)

    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    try:
        with factory() as work:
            for snapshot in snapshots:
                revision = snapshot.cache_key.provider_content_revision
                work.projections.put_market_index_snapshot(
                    snapshot, provider_content_revision=revision,
                )
                work.projections.advance_market_index_head(
                    snapshot, provider_content_revision=revision,
                )
            work.commit()
        # Deliberately bypass foreign keys only in isolated corrupt-storage fixtures.
        # A 130-head history crosses the 128-row fetch boundary; damage an older head.
        damaged_hash = snapshots[-2].snapshot_hash
        if damage:
            with sqlite3.connect(tmp_path / "monitor.db") as connection:
                if damage == "canonical":
                    connection.execute(
                        "UPDATE market_index_snapshot SET snapshot_json=snapshot_json || ' ' "
                        "WHERE snapshot_hash=?",
                        (damaged_hash,),
                    )
                elif damage == "missing":
                    connection.execute(
                        "DELETE FROM market_index_snapshot WHERE snapshot_hash=?",
                        (damaged_hash,),
                    )
                else:
                    connection.execute(
                        "UPDATE market_index_snapshot_head SET provider_content_revision=999 "
                        "WHERE snapshot_hash=?",
                        (damaged_hash,),
                    )
        verified.clear()
        event.listen(engine, "before_cursor_execute", count)
        with factory() as work:
            if damage:
                expected = (
                    ProjectionMissingDependencyError if damage == "missing" else ProjectionError
                )
                with pytest.raises(expected):
                    work.projections.list_latest_market_index_snapshots(
                        mapping_version=snapshots[0].mapping_version,
                        index_codes=DASHBOARD_INDEX_CODES,
                    )
            else:
                restored = work.projections.list_latest_market_index_snapshots(
                    mapping_version=snapshots[0].mapping_version, index_codes=DASHBOARD_INDEX_CODES,
                )
                assert tuple(item.snapshot for item in restored) == (snapshots[-1],)
                assert restored[0].provider_content_revision == 1
                assert len(queries) == 1
                assert set(verified) == {item.snapshot_hash for item in snapshots}
                assert len(verified) == len(snapshots)
    finally:
        engine.dispose()
