"""Regression evidence for durable closing-index selection (ICDR A01/A02/A04)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.snapshots import (
    MarketIndexSnapshotCoordinator,
    build_market_index_snapshot,
)
from trade_plan_monitor.market_index.tushare import TushareMarketIndexProviderError
from trade_plan_monitor.runtime.market_indexes import (
    RuntimeMarketIndexBatch,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.request_control import RequestControlErrorCode
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.index_close_repair import repair_current_index_display
from trade_plan_monitor.state.models import MarketIndexSnapshotHead
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_ZONE = ZoneInfo("Asia/Shanghai")
_FINAL_TARGET = datetime(2026, 10, 9, 15, 0, tzinfo=_ZONE)
_SUCCESS_AT = _FINAL_TARGET + timedelta(minutes=20, seconds=2)
_FAILURE_AT = _FINAL_TARGET + timedelta(hours=1, seconds=16)
_INDEX = MarketIndexCode.SSE_COMPOSITE


def _bar(
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    bar_at: datetime,
    observed_at: datetime,
    close: Decimal,
    revision: int,
) -> MarketIndexBar:
    return MarketIndexBar(
        index_code=index_code,
        interval=interval,
        bar_at=bar_at,
        open_points=close,
        high_points=close,
        low_points=close,
        close_points=close,
        volume=Decimal("100"),
        amount=Decimal("1000"),
        observed_at=observed_at,
        source_kind=(
            MarketIndexSourceKind.OFFICIAL
            if interval is MarketIndexInterval.OFFICIAL_DAILY
            else MarketIndexSourceKind.PROVISIONAL
        ),
        provider_revision=revision,
    )


def _provider_batch(
    *,
    index_code: MarketIndexCode = _INDEX,
    observed_at: datetime = _SUCCESS_AT,
    revision: int = 97,
    final_close: Decimal = Decimal("3813.791"),
) -> MarketIndexProviderBatch:
    # Include the previous session for the existing turnover acquisition contract.
    minute_bars = []
    for day in (8, 9):
        for hour, minute in ((9, 35), (13, 5)):
            start = _FINAL_TARGET.replace(day=day, hour=hour, minute=minute)
            for offset in range(24):
                bar_at = start + timedelta(minutes=5 * offset)
                close = final_close if bar_at == _FINAL_TARGET else Decimal("3811.9")
                minute_bars.append(
                    _bar(
                        index_code,
                        MarketIndexInterval.FIVE_MINUTE,
                        bar_at,
                        observed_at,
                        close,
                        revision,
                    )
                )
    daily_bars = tuple(
        _bar(
            index_code,
            MarketIndexInterval.OFFICIAL_DAILY,
            _FINAL_TARGET.replace(day=day),
            _FINAL_TARGET.replace(day=day) + timedelta(minutes=20),
            Decimal("3811.9043"),
            revision,
        )
        for day in (7, 8)
    )
    return MarketIndexProviderBatch(
        index_code=index_code,
        five_minute_bars=tuple(minute_bars),
        official_daily_bars=daily_bars,
        content_revision=revision,
        observed_at=observed_at,
    )


def _live_capture(**kwargs) -> MarketIndexSnapshot:
    batch = _provider_batch(**kwargs)
    snapshot = build_market_index_snapshot(
        index_code=batch.index_code,
        decision_cutoff=_FINAL_TARGET,
        requests=(),
        five_minute_bars=batch.five_minute_bars,
        official_daily_bars=batch.official_daily_bars,
        content_revision=batch.content_revision,
        observed_at=batch.observed_at,
        observed_no_later_than=batch.observed_at,
        minimum_five_minute_bar_count=96,
        minimum_official_daily_bar_count=2,
    )
    assert snapshot.health is MarketIndexHealth.LIVE
    return snapshot


def _failed_capture() -> MarketIndexSnapshot:
    class FailingProvider:
        async def acquire_index_data(self, **kwargs) -> MarketIndexProviderBatch:
            raise TushareMarketIndexProviderError(
                stage="REALTIME_MINUTES",
                reason=RequestControlErrorCode.TIMEOUT,
            )

    snapshot = asyncio.run(
        MarketIndexSnapshotCoordinator(FailingProvider()).get_snapshot(
            index_code=_INDEX,
            decision_cutoff=_FINAL_TARGET,
            requests=(),
            observed_no_later_than=_FAILURE_AT,
        )
    )
    assert snapshot.health is MarketIndexHealth.BLOCKED
    assert snapshot.issues == (MarketIndexIssueCode.PROVIDER_UNAVAILABLE,)
    return snapshot


def _runtime_service(session_factory) -> RuntimeEvaluationService:
    return RuntimeEvaluationService(
        fetch_minutes=lambda *_args: (),
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(
            session_factory,
            clock=lambda: _FAILURE_AT + timedelta(minutes=1),
        ),
        context_builder=lambda *_args: None,
        committed_event_publisher=lambda _event: None,
    )


def _persist(service: RuntimeEvaluationService, snapshot: MarketIndexSnapshot) -> None:
    service._persist_market_index_batch(
        RuntimeMarketIndexBatch(
            snapshot.decision_cutoff,
            MappingProxyType({snapshot.index_code: snapshot}),
        )
    )


def _head(work: SqlAlchemyUnitOfWork, snapshot: MarketIndexSnapshot):
    return work.projections.get_market_index_head(
        mapping_version=snapshot.mapping_version,
        index_code=snapshot.index_code,
        decision_cutoff=snapshot.decision_cutoff,
        request_set_hash=snapshot.request_set_hash,
    )


@pytest.mark.parametrize("reopen_database", (False, True), ids=("A01", "A02"))
def test_failed_close_acquisition_retains_full_effective_snapshot(
    tmp_path: Path,
    reopen_database: bool,
) -> None:
    path = tmp_path / "close-retention.db"
    engine = create_sqlite_engine(path)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    live = _live_capture()
    failed = _failed_capture()
    assert failed.request_set_hash == live.request_set_hash

    try:
        service = _runtime_service(factory)
        _persist(service, live)
        _persist(service, failed)

        if reopen_database:
            engine.dispose()
            engine = create_sqlite_engine(path)
            factory = create_session_factory(engine)

        with SqlAlchemyUnitOfWork(factory) as work:
            head = _head(work, live)
            assert head is not None
            assert head.snapshot.snapshot_hash == live.snapshot_hash
            assert head.snapshot.health is MarketIndexHealth.LIVE
            assert head.snapshot.latest_completed_five_minute.close_points == Decimal("3813.791")
            current_day_bars = tuple(
                bar
                for bar in head.snapshot.five_minute_bars
                if bar.bar_at.date() == _FINAL_TARGET.date()
            )
            assert len(current_day_bars) == 48
            assert current_day_bars[-1].bar_at == _FINAL_TARGET
            # The failure remains immutable evidence, separate from effective display data.
            assert (
                work.projections.get_market_index_snapshot(failed.snapshot_hash).snapshot == failed
            )
            assert work.projections.get_market_index_snapshot(live.snapshot_hash).snapshot == live
            latest_attempts = work.projections.list_market_index_acquisitions(
                mapping_version=live.mapping_version,
            )
            assert latest_attempts == ((failed, failed.observed_at),)
    finally:
        engine.dispose()


def test_newer_live_correction_with_smaller_provider_revision_is_persisted(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "close-correction.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    initial = _live_capture()
    corrected = _live_capture(
        observed_at=_SUCCESS_AT + timedelta(minutes=10),
        revision=7,
        final_close=Decimal("3813.8"),
    )
    assert corrected.revision < initial.revision

    try:
        service = _runtime_service(factory)
        _persist(service, initial)
        _persist(service, corrected)

        with SqlAlchemyUnitOfWork(factory) as work:
            head = _head(work, initial)
            assert head is not None
            assert head.snapshot.snapshot_hash == corrected.snapshot_hash
            assert head.snapshot.latest_completed_five_minute.close_points == Decimal("3813.8")
            original_record = work.projections.get_market_index_snapshot(initial.snapshot_hash)
            assert original_record is not None
            assert original_record.snapshot == initial
    finally:
        engine.dispose()


def test_runtime_selects_newer_live_correction_even_with_smaller_revision() -> None:
    class CorrectingProvider:
        observed_at = _SUCCESS_AT
        revision = 97
        close = Decimal("3813.791")

        async def acquire_index_data(self, *, index_code, **kwargs) -> MarketIndexProviderBatch:
            return _provider_batch(
                index_code=index_code,
                observed_at=self.observed_at,
                revision=self.revision,
                final_close=self.close,
            )

    provider = CorrectingProvider()
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(
        service.prepare(
            plans=(),
            decision_cutoff=_FINAL_TARGET,
            observed_no_later_than=_SUCCESS_AT,
        )
    ).snapshots_by_index[_INDEX]
    assert initial.health is MarketIndexHealth.LIVE

    provider.observed_at = _SUCCESS_AT + timedelta(minutes=10)
    provider.revision = 7
    provider.close = Decimal("3813.8")
    corrected = asyncio.run(
        service.prepare(
            plans=(),
            decision_cutoff=_FINAL_TARGET,
            observed_no_later_than=provider.observed_at,
        )
    ).snapshots_by_index[_INDEX]

    assert corrected.health is MarketIndexHealth.LIVE
    assert corrected.revision < initial.revision
    assert corrected.snapshot_hash != initial.snapshot_hash
    assert service.latest_snapshots()[_INDEX] == corrected


def test_poisoned_close_head_repair_is_idempotent_and_preserves_immutable_captures(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "poisoned-close-head.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    live = _live_capture()
    failed = _failed_capture()

    try:
        service = _runtime_service(factory)
        _persist(service, live)
        _persist(service, failed)

        # Recreate only the legacy persisted head fault in this isolated test database.
        key = (
            live.mapping_version,
            live.index_code.value,
            live.decision_cutoff.isoformat(),
            live.request_set_hash,
        )
        with Session(engine) as session:
            row = session.get(MarketIndexSnapshotHead, key)
            assert row is not None
            row.snapshot_hash = failed.snapshot_hash
            row.provider_content_revision = failed.revision
            row.updated_at = failed.observed_at.isoformat()
            session.commit()

        with SqlAlchemyUnitOfWork(factory) as work:
            assert _head(work, live).snapshot == failed
            assert work.projections.repair_market_index_heads(
                trade_date=_FINAL_TARGET.date(),
                mapping_version=live.mapping_version,
            ) == 1
            work.commit()

        with SqlAlchemyUnitOfWork(factory) as work:
            repaired = _head(work, live)
            assert repaired is not None
            assert repaired.snapshot == live
            assert repaired.snapshot.snapshot_hash == live.snapshot_hash
            assert len(tuple(
                bar for bar in repaired.snapshot.five_minute_bars
                if bar.bar_at.date() == _FINAL_TARGET.date()
            )) == 48
            assert work.projections.get_market_index_snapshot(live.snapshot_hash).snapshot == live
            assert (
                work.projections.get_market_index_snapshot(failed.snapshot_hash).snapshot == failed
            )
            assert work.projections.list_market_index_acquisitions(
                mapping_version=live.mapping_version,
            ) == ((failed, failed.observed_at),)
            sequence_before = work.events.current_sequence()
            assert work.projections.repair_market_index_heads(
                trade_date=_FINAL_TARGET.date(),
                mapping_version=live.mapping_version,
            ) == 0
            assert work.events.current_sequence() == sequence_before
            work.commit()
    finally:
        engine.dispose()


def test_preopen_startup_repairs_strictly_previous_trading_date(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "preopen-repair.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    today_live = _live_capture()
    today_failed = _failed_capture()
    delta = timedelta(days=1)
    previous_live = build_market_index_snapshot(
        index_code=_INDEX,
        decision_cutoff=today_live.decision_cutoff - delta,
        requests=(),
        five_minute_bars=tuple(
            bar.model_copy(update={
                "bar_at": bar.bar_at - delta,
                "observed_at": bar.observed_at - delta,
            })
            for bar in today_live.five_minute_bars
        ),
        official_daily_bars=tuple(
            bar.model_copy(update={
                "bar_at": bar.bar_at - delta,
                "observed_at": bar.observed_at - delta,
            })
            for bar in today_live.official_daily_bars
        ),
        content_revision=today_live.revision,
        observed_at=today_live.observed_at - delta,
        observed_no_later_than=today_live.observed_at - delta,
        minimum_five_minute_bar_count=96,
        minimum_official_daily_bar_count=2,
    )
    previous_failed = build_market_index_snapshot(
        index_code=_INDEX,
        decision_cutoff=today_failed.decision_cutoff - delta,
        requests=(),
        five_minute_bars=(),
        official_daily_bars=(),
        content_revision=today_failed.revision,
        observed_at=today_failed.observed_at - delta,
        observed_no_later_than=today_failed.observed_at - delta,
    )
    now = _FINAL_TARGET.replace(hour=9, minute=0)

    try:
        with SqlAlchemyUnitOfWork(factory) as work:
            work.references.upsert_trading_days(tuple(
                TradingDay(
                    exchange="SSE",
                    cal_date=_FINAL_TARGET.replace(day=day).date(),
                    is_open=True,
                    previous_trade_date=_FINAL_TARGET.replace(day=day - 1).date(),
                )
                for day in (8, 9)
            ))
            work.commit()
        service = _runtime_service(factory)
        for snapshot in (previous_live, previous_failed, today_live, today_failed):
            _persist(service, snapshot)

        with Session(engine) as session:
            for live, failed in (
                (previous_live, previous_failed),
                (today_live, today_failed),
            ):
                row = session.get(MarketIndexSnapshotHead, (
                    live.mapping_version, live.index_code.value,
                    live.decision_cutoff.isoformat(), live.request_set_hash,
                ))
                assert row is not None
                row.snapshot_hash = failed.snapshot_hash
                row.provider_content_revision = failed.revision
                row.updated_at = failed.observed_at.isoformat()
            session.commit()

        with SqlAlchemyUnitOfWork(factory) as work:
            repaired, backfilled = repair_current_index_display(work, now=now)
            assert repaired == 1
            assert backfilled == 0
            work.commit()

        with SqlAlchemyUnitOfWork(factory) as work:
            assert _head(work, previous_live).snapshot == previous_live
            assert _head(work, today_live).snapshot == today_failed
            assert work.projections.get_market_index_snapshot(
                previous_failed.snapshot_hash,
            ).snapshot == previous_failed
            assert work.projections.get_market_index_snapshot(
                today_live.snapshot_hash,
            ).snapshot == today_live
            assert repair_current_index_display(work, now=now) == (0, 0)
    finally:
        engine.dispose()


def test_reobserved_stored_revision_uses_new_attempt_time_and_rejects_older_correction(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "reobserved-correction.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    initial = _live_capture(revision=1)
    correction = _live_capture(
        observed_at=_SUCCESS_AT + timedelta(minutes=10),
        revision=2,
        final_close=Decimal("3813.8"),
    )
    reobserved_at = _SUCCESS_AT + timedelta(minutes=20)
    reobserved = _live_capture(observed_at=reobserved_at, revision=1)
    older_correction = _live_capture(
        observed_at=_SUCCESS_AT + timedelta(minutes=15),
        revision=3,
        final_close=Decimal("3813.75"),
    )
    assert reobserved.snapshot_hash != initial.snapshot_hash

    try:
        service = _runtime_service(factory)
        _persist(service, initial)
        _persist(service, correction)
        attempted, _events = service._persist_market_index_batch(RuntimeMarketIndexBatch(
            reobserved.decision_cutoff,
            MappingProxyType({_INDEX: reobserved}),
        ))

        # Reuse immutable revision 1 content while ordering this acquisition by t3.
        assert attempted.snapshots_by_index[_INDEX] == initial
        with SqlAlchemyUnitOfWork(factory) as work:
            head = _head(work, initial)
            assert head is not None
            assert head.snapshot == initial
            assert head.snapshot.snapshot_hash == initial.snapshot_hash
            assert head.provider_content_revision == 1
            assert head.updated_at == reobserved_at
            assert work.projections.list_market_index_acquisitions(
                mapping_version=initial.mapping_version,
            ) == ((initial, reobserved_at),)
            assert work.projections.get_market_index_snapshot(reobserved.snapshot_hash) is None
            assert work.projections.get_market_index_snapshot(
                initial.snapshot_hash,
            ).snapshot == initial
            assert work.projections.get_market_index_snapshot(
                correction.snapshot_hash,
            ).snapshot == correction

        _persist(service, older_correction)

        with SqlAlchemyUnitOfWork(factory) as work:
            head = _head(work, initial)
            assert head is not None
            assert head.snapshot == initial
            assert head.updated_at == reobserved_at
            assert work.projections.list_market_index_acquisitions(
                mapping_version=initial.mapping_version,
            ) == ((initial, reobserved_at),)
    finally:
        engine.dispose()
