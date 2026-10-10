"""Offline acceptance of bounded recovery at the two session boundaries (A05/A06)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.snapshots import MarketIndexSnapshotCoordinator
from trade_plan_monitor.market_index.tushare import TushareMarketIndexProviderError
from trade_plan_monitor.runtime.market_indexes import (
    ALWAYS_ON_INDEX_CODES,
    RuntimeMarketIndexService,
)
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import RequestControlErrorCode
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketSessionScheduler
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.projections import ProjectionRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DAY = date(2026, 10, 9)
LAGGING_INDEX = MarketIndexCode.STAR_50
SOURCE_IDENTITY = "a" * 64


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self.sleeps: list[datetime] = []

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.sleeps.append(deadline)
        self.current = max(self.current, deadline)


def _target(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TRADE_DAY, time(hour, minute), SHANGHAI)


def _bucket_ends(trade_day: date) -> tuple[datetime, ...]:
    return tuple(
        datetime.combine(trade_day, start, SHANGHAI) + timedelta(minutes=5 * offset)
        for start in (time(9, 35), time(13, 5))
        for offset in range(24)
    )


def _bar(
    code: MarketIndexCode, at: datetime, observed: datetime, *, daily: bool = False
) -> MarketIndexBar:
    points = Decimal("3800") + Decimal(at.minute)
    return MarketIndexBar(
        index_code=code,
        interval=(
            MarketIndexInterval.OFFICIAL_DAILY if daily else MarketIndexInterval.FIVE_MINUTE
        ),
        bar_at=at,
        open_points=points,
        high_points=points,
        low_points=points,
        close_points=points,
        amount=Decimal("10000"),
        observed_at=observed,
        source_kind=MarketIndexSourceKind.OFFICIAL if daily else MarketIndexSourceKind.PROVISIONAL,
        provider_revision=1,
    )


class _BoundaryProvider:
    """A physical acquisition fake; siblings are complete and one index can lag."""

    def __init__(self, observed: datetime) -> None:
        self.observed = observed
        self.mode = "LAG"
        self.calls: list[tuple[MarketIndexCode, datetime]] = []
        self.hold = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        self.calls.append((index_code, decision_cutoff))
        if index_code is LAGGING_INDEX:
            if self.hold:
                self.started.set()
                await self.release.wait()
            if self.mode in {"TIMEOUT", "PERMISSION"}:
                raise TushareMarketIndexProviderError(
                    stage="REALTIME_MINUTES",
                    reason=(
                        RequestControlErrorCode.TIMEOUT
                        if self.mode == "TIMEOUT"
                        else RequestControlErrorCode.BLOCKED_PERMISSION
                    ),
                )
        cutoff = (
            decision_cutoff - timedelta(minutes=5)
            if index_code is LAGGING_INDEX and self.mode == "LAG"
            else decision_cutoff
        )
        buckets = _bucket_ends(TRADE_DAY - timedelta(days=1)) + tuple(
            at for at in _bucket_ends(TRADE_DAY) if at <= cutoff
        )
        return MarketIndexProviderBatch(
            index_code=index_code,
            five_minute_bars=tuple(
                _bar(index_code, at, self.observed) for at in buckets[-five_minute_bar_count:]
            ),
            official_daily_bars=tuple(
                _bar(
                    index_code,
                    datetime.combine(TRADE_DAY - timedelta(days=offset), time(15), SHANGHAI),
                    self.observed,
                    daily=True,
                )
                for offset in range(official_daily_bar_count, 0, -1)
            ),
            content_revision=1,
            observed_at=self.observed,
        )


def _prepare(
    service: RuntimeMarketIndexService, provider: _BoundaryProvider, target: datetime
) -> None:
    provider.observed = target + timedelta(seconds=12)
    initial = asyncio.run(service.prepare(
        plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
    ))
    assert initial.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.STALE
    assert initial.snapshots_by_index[LAGGING_INDEX].issues == (MarketIndexIssueCode.STALE_DATA,)
    assert all(
        snapshot.health is MarketIndexHealth.LIVE
        for code, snapshot in initial.snapshots_by_index.items()
        if code is not LAGGING_INDEX
    )


def _retry(
    service: RuntimeMarketIndexService, provider: _BoundaryProvider, observed: datetime
):
    provider.observed = observed
    return asyncio.run(service.retry_recoverable(observed_no_later_than=observed))


@pytest.mark.parametrize("target", [_target(11, 30), _target(15)])
def test_final_bucket_retries_without_a_following_market_minute_and_only_lagging_index(
    target: datetime,
) -> None:
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    siblings = {
        code: snapshot for code, snapshot in service.latest_snapshots().items()
        if code is not LAGGING_INDEX
    }
    assert service.next_recovery_due_at() == target + timedelta(seconds=72)
    assert service.recovery_kinds() == {LAGGING_INDEX: "FINAL_BUCKET"}
    assert _retry(service, provider, target + timedelta(seconds=71)) is None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES)

    provider.mode = "LIVE"
    result = _retry(service, provider, target + timedelta(seconds=72))
    assert result is not None
    assert set(result.snapshots_by_index) == {LAGGING_INDEX}
    assert result.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.LIVE
    assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)]
    assert all(service.latest_snapshots()[code] is snapshot for code, snapshot in siblings.items())
    assert service.next_recovery_due_at() is None
    assert service.recovery_records() == ()


def test_final_bucket_three_fixed_supplements_and_repeated_prepare_cannot_reset_budget() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)

    for attempt, offset in enumerate((72, 132, 252), start=1):
        assert service.next_recovery_due_at() == target + timedelta(seconds=offset)
        assert _retry(service, provider, target + timedelta(seconds=offset)) is not None
        records = service.recovery_records()
        if attempt < 3:
            assert len(records) == 1
            assert records[0][3] == attempt
        else:
            assert records == ()
    assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)] * 3
    assert _retry(service, provider, target + timedelta(seconds=253)) is None

    provider.observed = target + timedelta(seconds=260)
    asyncio.run(service.prepare(
        plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
    ))
    assert service.next_recovery_due_at() is None
    assert _retry(service, provider, target + timedelta(seconds=299)) is None


@pytest.mark.parametrize("expired_offset", [300, 301])
def test_final_bucket_window_expires_at_five_minutes_without_an_acquisition(
    expired_offset: int,
) -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    assert service.next_recovery_due_at() == target + timedelta(seconds=72)
    before = tuple(provider.calls)
    assert _retry(service, provider, target + timedelta(seconds=expired_offset)) is None
    assert service.next_recovery_due_at() is None
    assert service.recovery_records() == ()
    assert tuple(provider.calls) == before


def test_final_bucket_admission_deferral_preserves_budget_and_cannot_extend_expiry() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    durable = service.recovery_records()
    due = target + timedelta(seconds=72)
    service.defer_due_recoveries(
        now=due, until=target + timedelta(seconds=102),
        index_codes=frozenset({LAGGING_INDEX}),
    )
    assert service.next_recovery_due_at(now=due) == target + timedelta(seconds=102)
    assert service.recovery_records() == durable
    assert _retry(service, provider, target + timedelta(seconds=101)) is None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES)
    assert _retry(service, provider, target + timedelta(seconds=102)) is not None
    assert service.recovery_records()[0][3] == 1
    assert service.next_recovery_due_at() >= target + timedelta(seconds=162)

    service.defer_due_recoveries(
        now=target + timedelta(seconds=200), until=target + timedelta(seconds=400),
        index_codes=frozenset({LAGGING_INDEX}),
    )
    before = tuple(provider.calls)
    assert _retry(service, provider, target + timedelta(seconds=300)) is None
    assert service.next_recovery_due_at() is None
    assert tuple(provider.calls) == before


def test_final_bucket_kind_and_budget_survive_restart() -> None:
    target = _target(11, 30)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    assert _retry(service, provider, target + timedelta(seconds=72)) is not None
    records = service.recovery_records()
    assert records[0][3] == 1

    resumed = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    resumed.restore_recoveries(
        snapshots=service.latest_snapshots(), records=records,
        kinds=service.recovery_kinds(), now=target + timedelta(seconds=100),
    )
    assert resumed.recovery_kinds() == {LAGGING_INDEX: "FINAL_BUCKET"}
    assert resumed.next_recovery_due_at() == target + timedelta(seconds=132)
    assert _retry(resumed, provider, target + timedelta(seconds=132)) is not None
    assert resumed.recovery_records()[0][3] == 2
    assert _retry(resumed, provider, target + timedelta(seconds=252)) is not None
    assert resumed.next_recovery_due_at() is None
    assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)] * 3


def test_restart_discards_expired_final_bucket_work() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    original = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(original, provider, target)
    resumed = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    resumed.restore_recoveries(
        snapshots=original.latest_snapshots(), records=original.recovery_records(),
        kinds=original.recovery_kinds(), now=target + timedelta(seconds=300),
    )
    assert resumed.next_recovery_due_at() is None
    before = tuple(provider.calls)
    assert _retry(resumed, provider, target + timedelta(seconds=301)) is None
    assert tuple(provider.calls) == before


def test_final_bucket_failure_reason_changes_do_not_reset_supplement_budget() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    provider.mode = "TIMEOUT"
    first = _retry(service, provider, target + timedelta(seconds=72))
    assert first is not None
    assert first.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.BLOCKED
    assert service.recovery_records()[0][3] == 1
    assert service.recovery_kinds() == {LAGGING_INDEX: "FINAL_BUCKET"}
    assert service.next_recovery_due_at() == target + timedelta(seconds=132)

    provider.mode = "LAG"
    assert _retry(service, provider, target + timedelta(seconds=132)) is not None
    assert service.recovery_records()[0][3] == 2
    assert service.next_recovery_due_at() == target + timedelta(seconds=252)
    assert _retry(service, provider, target + timedelta(seconds=252)) is not None
    assert service.next_recovery_due_at() is None
    assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)] * 3


def test_late_restart_performs_one_overdue_supplement_then_waits_sixty_seconds() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    original = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(original, provider, target)
    resumed = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    late = target + timedelta(seconds=180)
    resumed.restore_recoveries(
        snapshots=original.latest_snapshots(), records=original.recovery_records(),
        kinds=original.recovery_kinds(), now=late,
    )
    assert _retry(resumed, provider, late) is not None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES) + 1
    assert resumed.next_recovery_due_at() >= late + timedelta(seconds=60)
    assert _retry(resumed, provider, late) is None
    assert _retry(resumed, provider, late + timedelta(seconds=59)) is None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES) + 1


def test_two_concurrent_recovery_wakes_share_one_physical_start_and_one_attempt() -> None:
    async def scenario() -> None:
        target = _target(15)
        provider = _BoundaryProvider(target + timedelta(seconds=12))
        service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
        await service.prepare(
            plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
        )
        assert service.next_recovery_due_at() == target + timedelta(seconds=72)
        provider.observed = target + timedelta(seconds=72)
        provider.hold = True
        first = asyncio.create_task(service.retry_recoverable(
            observed_no_later_than=provider.observed,
        ))
        await provider.started.wait()
        second = asyncio.create_task(service.retry_recoverable(
            observed_no_later_than=provider.observed,
        ))
        await asyncio.sleep(0)
        provider.release.set()
        results = await asyncio.gather(first, second)
        assert sum(result is not None for result in results) == 1
        assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)]
        assert service.recovery_records()[0][3] == 1
        assert service.next_recovery_due_at() == target + timedelta(seconds=132)

    asyncio.run(scenario())


@pytest.mark.parametrize("completion_offset", [180, 310])
def test_slow_final_bucket_completion_delays_remaining_work_or_expires_it(
    completion_offset: int,
) -> None:
    target = _target(15)

    class Clock:
        current = target + timedelta(seconds=12)

        def now(self) -> datetime:
            return self.current

        async def sleep_until(self, deadline: datetime) -> None:
            self.current = max(self.current, deadline)

    clock = Clock()

    class SlowProvider(_BoundaryProvider):
        slow = False

        async def acquire_index_data(self, **kwargs: object) -> MarketIndexProviderBatch:
            if self.slow and kwargs["index_code"] is LAGGING_INDEX:
                clock.current = target + timedelta(seconds=completion_offset)
                self.observed = clock.current
            return await super().acquire_index_data(**kwargs)

    provider = SlowProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider, clock=clock))
    _prepare(service, provider, target)
    provider.slow = True
    result = _retry(service, provider, target + timedelta(seconds=72))
    assert result is not None
    assert result.snapshots_by_index[LAGGING_INDEX].observed_at == clock.current
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES) + 1
    if completion_offset >= 300:
        assert service.next_recovery_due_at() is None
        assert _retry(service, provider, clock.current) is None
    else:
        assert service.recovery_records()[0][3] == 1
        assert service.next_recovery_due_at() >= clock.current + timedelta(seconds=60)
        assert _retry(service, provider, clock.current + timedelta(seconds=59)) is None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES) + 1


def test_permission_failure_cannot_create_final_bucket_recovery() -> None:
    target = _target(15)
    provider = _BoundaryProvider(target + timedelta(seconds=12))
    provider.mode = "PERMISSION"
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(service.prepare(
        plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
    ))
    assert initial.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.BLOCKED
    assert service.next_recovery_due_at() is None
    assert _retry(service, provider, target + timedelta(seconds=72)) is None
    assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES)


def test_newer_target_supersedes_final_bucket_recovery() -> None:
    target = _target(11, 30)
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    assert service.next_recovery_due_at() == target + timedelta(seconds=72)
    provider.mode = "LIVE"
    newer = _target(13, 5)
    provider.observed = newer + timedelta(seconds=12)
    asyncio.run(service.prepare(
        plans=(), decision_cutoff=newer, observed_no_later_than=provider.observed,
    ))
    before = tuple(provider.calls)
    assert service.next_recovery_due_at() is None
    assert _retry(service, provider, provider.observed) is None
    assert tuple(provider.calls) == before


@pytest.mark.parametrize("target", [_target(11, 30), _target(15)])
def test_final_bucket_deadline_uses_existing_scheduler_during_lunch_and_after_close(
    target: datetime,
) -> None:
    provider = _BoundaryProvider(target)
    service = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(service, provider, target)
    clock = _MutableClock(target + timedelta(seconds=12))
    scheduler = MarketSessionScheduler(
        clock=clock, is_open_on=lambda day: day == TRADE_DAY,
        next_index_recovery_at=lambda: service.next_recovery_due_at(now=clock.now()),
    )
    last_market = next(
        deadline for deadline in scheduler.deadlines_for_date(TRADE_DAY)
        if deadline.kind is DeadlineKind.REALTIME_MINUTE and deadline.bar_end == target
    )
    first = asyncio.run(scheduler.wait_for_next(after=last_market.due_at))
    assert first is not None
    assert first.kind is DeadlineKind.INDEX_RECOVERY
    assert first.due_at == target + timedelta(seconds=72)
    assert clock.sleeps == [first.due_at]
    assert first.bar_end is None
    provider.mode = "LIVE"
    assert _retry(service, provider, first.due_at) is not None

    following = scheduler.next_deadline(after=first.due_at)
    assert following is not None
    assert following.kind is not DeadlineKind.INDEX_RECOVERY
    if target.hour == 15:
        assert following.kind is DeadlineKind.OFFICIAL_CLOSE
        assert following.due_at == _target(15, 20)
    else:
        assert following.kind is DeadlineKind.REALTIME_MINUTE
        assert following.bar_end == _target(13, 1)


def _upgrade_to(engine: Engine, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(
        Path(__file__).resolve().parents[2] / "src/trade_plan_monitor/state/migrations"
    ))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def test_index_close_migration_preserves_legacy_recovery_and_allows_exhausted_final_budget(
    tmp_path: Path,
) -> None:
    target = _target(15)
    engine = create_sqlite_engine(tmp_path / "migration.sqlite3")
    try:
        _upgrade_to(engine, "0024_daily_plan")
        legacy = (
            MarketIndexCode.CHINEXT.value, target.isoformat(),
            (target + timedelta(seconds=12)).isoformat(), 1,
            (target + timedelta(seconds=102)).isoformat(),
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO market_index_recovery_state "
                "(index_code, decision_cutoff, first_failed_at, attempts, due_at) "
                "VALUES (?, ?, ?, ?, ?)", legacy,
            )
        upgrade_database(engine)
        assert {column["name"] for column in inspect(engine).get_columns(
            "market_index_recovery_state"
        )} >= {"kind", "source_identity"}
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT index_code, decision_cutoff, first_failed_at, attempts, due_at, "
                "kind, source_identity FROM market_index_recovery_state"
            ).one()
            assert tuple(row[:5]) == legacy
            assert row.kind == "TRANSIENT"
            assert row.source_identity is None
        exhausted = ((LAGGING_INDEX, target, target, 3, target + timedelta(minutes=5)),)
        with Session(engine) as session:
            repository = ProjectionRepository(session)
            repository.replace_market_index_recoveries(
                exhausted, kinds={LAGGING_INDEX: "FINAL_BUCKET"},
                source_identity=SOURCE_IDENTITY,
            )
            session.commit()
        upgrade_database(engine)
        with Session(engine) as session:
            repository = ProjectionRepository(session)
            assert repository.list_market_index_recoveries(include_exhausted=True) == exhausted
            assert repository.list_market_index_recoveries() == ()
            assert repository.market_index_recovery_kinds(
                source_identity=SOURCE_IDENTITY,
            ) == {LAGGING_INDEX: "FINAL_BUCKET"}
    finally:
        engine.dispose()


@pytest.mark.parametrize("consumed", [1, 3])
@pytest.mark.parametrize("same_source", [True, False])
def test_sqlite_reopen_restores_source_bound_budget_and_never_resets_exhausted_cap(
    tmp_path: Path, consumed: int, same_source: bool,
) -> None:
    target = _target(15)
    provider = _BoundaryProvider(target)
    original = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    _prepare(original, provider, target)
    for offset in (72, 132, 252)[:consumed]:
        assert _retry(original, provider, target + timedelta(seconds=offset)) is not None
    records = original.recovery_records(include_exhausted=True)
    assert records[0][3] == consumed
    if consumed == 3:
        assert original.recovery_records() == ()
        assert original.recovery_kinds() == {LAGGING_INDEX: "FINAL_BUCKET"}

    database = tmp_path / "budget.sqlite3"
    engine = create_sqlite_engine(database)
    try:
        upgrade_database(engine)
        with Session(engine) as session:
            repository = ProjectionRepository(session)
            for snapshot in original.latest_snapshots().values():
                revision = snapshot.cache_key.provider_content_revision
                repository.put_market_index_snapshot(snapshot, provider_content_revision=revision)
                repository.advance_market_index_head(snapshot, provider_content_revision=revision)
            repository.replace_market_index_recoveries(
                records, kinds=original.recovery_kinds(), source_identity=SOURCE_IDENTITY,
            )
            session.commit()
    finally:
        engine.dispose()

    reopened = create_sqlite_engine(database)
    try:
        sessions = create_session_factory(reopened)
        with sessions() as session:
            repository = ProjectionRepository(session)
            assert repository.list_market_index_recoveries(include_exhausted=True) == records
            assert repository.market_index_recovery_kinds(
                source_identity=SOURCE_IDENTITY,
            ) == {LAGGING_INDEX: "FINAL_BUCKET"}
            assert repository.market_index_recovery_kinds(source_identity="b" * 64) == {}

        restored = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
        restored_at = target + timedelta(seconds=100 if consumed == 1 else 260)
        clock = _MutableClock(restored_at)
        pipeline = object.__new__(ProductionMonitorPipeline)
        pipeline._work = lambda: SqlAlchemyUnitOfWork(sessions, clock=clock.now)
        pipeline._clock = clock
        pipeline.index_service = restored
        pipeline.index_source_identity = SOURCE_IDENTITY if same_source else "b" * 64
        pipeline.restore_index_recoveries()
        before = tuple(provider.calls)
        if not same_source:
            assert restored.recovery_records(include_exhausted=True) == ()
            assert restored.recovery_kinds() == {}
            assert restored.next_recovery_due_at() is None
            assert _retry(restored, provider, target + timedelta(seconds=299)) is None
            assert tuple(provider.calls) == before
            return

        assert restored.recovery_records(include_exhausted=True) == records
        if consumed == 1:
            assert restored.next_recovery_due_at() == target + timedelta(seconds=132)
            for offset in (132, 252):
                assert _retry(restored, provider, target + timedelta(seconds=offset)) is not None
        assert restored.next_recovery_due_at() is None
        assert restored.recovery_records(include_exhausted=True)[0][3] == 3
        calls_after_budget = tuple(provider.calls)
        provider.observed = target + timedelta(seconds=260)
        asyncio.run(restored.prepare(
            plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
        ))
        assert restored.next_recovery_due_at() is None
        assert restored.recovery_records(include_exhausted=True)[0][3] == 3
        assert _retry(restored, provider, target + timedelta(seconds=299)) is None
        assert tuple(provider.calls[len(calls_after_budget):]) == tuple(
            (code, target) for code in sorted(ALWAYS_ON_INDEX_CODES, key=lambda item: item.value)
        )
    finally:
        reopened.dispose()


@pytest.mark.parametrize("fence", ["configuration", "generation"])
def test_final_bucket_late_result_cannot_commit_after_source_or_generation_revocation(
    tmp_path: Path, fence: str,
) -> None:
    async def scenario() -> None:
        target = _target(15)
        engine = create_sqlite_engine(tmp_path / "revocation.sqlite3")
        try:
            upgrade_database(engine)
            sessions = create_session_factory(engine)
            clock = _MutableClock(target + timedelta(seconds=12))
            authority = {"configuration": True, "generation": True}
            pipeline = object.__new__(ProductionMonitorPipeline)
            pipeline._configuration_current = lambda: authority["configuration"]
            pipeline._generation_current = lambda: authority["generation"]
            pipeline._admission_revoked = lambda: False
            pipeline._index_certification_current = lambda: True
            provider = _BoundaryProvider(clock.now())
            indexes = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
            published = []
            evaluation = RuntimeEvaluationService(
                fetch_minutes=lambda *_args: (),
                unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(sessions, clock=clock.now),
                context_builder=lambda *_args: None,
                committed_event_publisher=published.append,
                market_index_service=indexes,
                index_commit_admission=pipeline._index_commit_current,
                index_source_identity=SOURCE_IDENTITY,
            )
            initial = await indexes.prepare(
                plans=(), decision_cutoff=target, observed_no_later_than=clock.now(),
            )
            evaluation._persist_market_index_batch(initial)
            with SqlAlchemyUnitOfWork(sessions, clock=clock.now) as work:
                before_snapshots = work.projections.list_latest_market_index_snapshots(
                    mapping_version="board-index-map-v1", index_codes=ALWAYS_ON_INDEX_CODES,
                )
                before_recoveries = work.projections.list_market_index_recoveries(
                    include_exhausted=True,
                )
                before_sequence = work.events.current_sequence()

            provider.hold = True
            provider.observed = target + timedelta(seconds=72)
            clock.current = provider.observed
            recovery = asyncio.create_task(evaluation.recover_transient_market_indexes(
                evaluated_at=clock.now(),
            ))
            await provider.started.wait()
            authority[fence] = False
            provider.release.set()
            with pytest.raises(RuntimeError, match="runtime index commit admission revoked"):
                await recovery
            assert len(provider.calls) == len(ALWAYS_ON_INDEX_CODES) + 1
            assert published == []
            with SqlAlchemyUnitOfWork(sessions, clock=clock.now) as work:
                assert work.projections.list_latest_market_index_snapshots(
                    mapping_version="board-index-map-v1", index_codes=ALWAYS_ON_INDEX_CODES,
                ) == before_snapshots
                assert work.projections.list_market_index_recoveries(
                    include_exhausted=True,
                ) == before_recoveries
                assert work.events.current_sequence() == before_sequence
        finally:
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("restart", [False, True])
def test_final_target_transient_budget_cannot_restart_as_publication_lag_budget(
    tmp_path: Path, restart: bool,
) -> None:
    target = _target(15)
    provider = _BoundaryProvider(target + timedelta(seconds=12))
    provider.mode = "TIMEOUT"
    original = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
    initial = asyncio.run(original.prepare(
        plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
    ))
    assert initial.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.BLOCKED
    assert original.recovery_kinds() == {LAGGING_INDEX: "TRANSIENT"}
    for offset in (42, 102, 222):
        assert original.next_recovery_due_at() == target + timedelta(seconds=offset)
        assert _retry(original, provider, target + timedelta(seconds=offset)) is not None
    assert provider.calls[len(ALWAYS_ON_INDEX_CODES):] == [(LAGGING_INDEX, target)] * 3
    assert original.recovery_records() == ()
    exhausted = original.recovery_records(include_exhausted=True)
    assert len(exhausted) == 1
    assert exhausted[0][3] == 3
    assert original.recovery_kinds() == {LAGGING_INDEX: "TRANSIENT"}
    assert original.next_recovery_due_at() is None

    selected = original
    reopened = None
    if restart:
        database = tmp_path / "transient-budget.sqlite3"
        engine = create_sqlite_engine(database)
        try:
            upgrade_database(engine)
            with Session(engine) as session:
                repository = ProjectionRepository(session)
                for snapshot in original.latest_snapshots().values():
                    revision = snapshot.cache_key.provider_content_revision
                    repository.put_market_index_snapshot(
                        snapshot, provider_content_revision=revision,
                    )
                    repository.advance_market_index_head(
                        snapshot, provider_content_revision=revision,
                    )
                repository.replace_market_index_recoveries(
                    exhausted, kinds=original.recovery_kinds(), source_identity=SOURCE_IDENTITY,
                )
                session.commit()
        finally:
            engine.dispose()
        reopened = create_sqlite_engine(database)
        sessions = create_session_factory(reopened)
        selected = RuntimeMarketIndexService(MarketIndexSnapshotCoordinator(provider))
        clock = _MutableClock(target + timedelta(seconds=240))
        pipeline = object.__new__(ProductionMonitorPipeline)
        pipeline._work = lambda: SqlAlchemyUnitOfWork(sessions, clock=clock.now)
        pipeline._clock = clock
        pipeline.index_service = selected
        pipeline.index_source_identity = SOURCE_IDENTITY
        pipeline.restore_index_recoveries()

    try:
        assert selected.recovery_records(include_exhausted=True) == exhausted
        provider.mode = "LAG"
        provider.observed = target + timedelta(seconds=260)
        changed = asyncio.run(selected.prepare(
            plans=(), decision_cutoff=target, observed_no_later_than=provider.observed,
        ))
        assert changed.snapshots_by_index[LAGGING_INDEX].health is MarketIndexHealth.STALE
        assert selected.recovery_records() == ()
        assert selected.recovery_records(include_exhausted=True)[0][3] == 3
        assert selected.next_recovery_due_at() is None
        before = tuple(provider.calls)
        assert _retry(selected, provider, target + timedelta(seconds=299)) is None
        assert tuple(provider.calls) == before
    finally:
        if reopened is not None:
            reopened.dispose()
