"""One coherent, bounded display read; acquisition and execution stay elsewhere."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from anyio import to_thread
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.market_data.sessions import DEFAULT_DATA_GRACE
from trade_plan_monitor.market_index.identity import MAPPING_VERSION, identity_for_index_code
from trade_plan_monitor.market_index.models import MarketIndexIssueCode
from trade_plan_monitor.market_index.selection import snapshot_rank
from trade_plan_monitor.market_index.turnover import (
    MARKET_TURNOVER_INDEX_CODES,
    build_market_turnover_summary,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES, DASHBOARD_INDEX_CODES
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import MarketTurnoverSummaryView
from trade_plan_monitor.web.routers.market_indexes import (
    MarketIndexBarView,
    MarketIndexLatestAcquisition,
    MarketIndexOverviewData,
    MarketIndexOverviewItem,
    MarketIndexOverviewResponse,
    MarketSessionView,
)

_INTEGRITY_ISSUES = frozenset(
    {
        MarketIndexIssueCode.DUPLICATE_IDENTITY,
        MarketIndexIssueCode.INDEX_IDENTITY_MISMATCH,
        MarketIndexIssueCode.FUTURE_DATA,
        MarketIndexIssueCode.INVALID_TIMESTAMP,
        MarketIndexIssueCode.NONCANONICAL_DECIMAL,
        MarketIndexIssueCode.INVALID_OHLC,
        MarketIndexIssueCode.FORMULA_MISMATCH,
    }
)


def expected_display_buckets(target: datetime) -> tuple[datetime, ...]:
    return tuple(
        datetime.combine(target.date(), start, SHANGHAI) + timedelta(minutes=5 * i)
        for start in (time(9, 35), time(13, 5))
        for i in range(24)
        if datetime.combine(target.date(), start, SHANGHAI) + timedelta(minutes=5 * i) <= target
    )


def resolve_market_session(
    now: datetime,
    *,
    is_open: bool | None,
    previous_open_date: date | None,
    stored_date: date | None,
) -> MarketSessionView:
    now = now.astimezone(SHANGHAI)
    local = now.time()
    if is_open is None:
        return MarketSessionView(
            phase="UNKNOWN",
            calendar_status="UNKNOWN",
            session_date=now.date(),
            display_trade_date=stored_date,
            expected_bucket_at=None,
        )
    phase = (
        "CLOSED"
        if not is_open or local >= time(15)
        else "PREOPEN"
        if local < time(9, 30)
        else "BREAK"
        if time(11, 30) <= local < time(13)
        else "OPEN"
    )
    display_date = now.date() if is_open and local >= time(9, 30) else previous_open_date
    target = None
    if display_date is not None:
        end = datetime.combine(display_date, time(15), SHANGHAI)
        if display_date < now.date() or phase == "CLOSED":
            target = end
        elif phase == "BREAK":
            target = end.replace(hour=11, minute=30)
        else:
            candidates = expected_display_buckets(end)
            target = max(
                (value for value in candidates if value + DEFAULT_DATA_GRACE <= now), default=None
            )
    return MarketSessionView(
        phase=phase,
        calendar_status="KNOWN",
        session_date=now.date(),
        display_trade_date=display_date,
        expected_bucket_at=target,
    )


def build_overview_item(code, snapshot, session, latest, *, source_verified: bool):
    board, name = identity_for_index_code(code)
    data = None
    status = "EMPTY"
    if snapshot is not None and session.display_trade_date is not None:
        bars = tuple(
            bar
            for bar in snapshot.five_minute_bars
            if bar.bar_at.date() == session.display_trade_date and bar.bar_at.time() != time(9, 30)
        )
        if bars:
            prior = tuple(
                bar
                for bar in snapshot.official_daily_bars
                if bar.bar_at.date() < session.display_trade_date
            )
            prior_close = prior[-1].close_points if prior else None
            data = MarketIndexOverviewData(
                snapshot_hash=snapshot.snapshot_hash,
                observed_at=snapshot.observed_at,
                completed_bucket_at=bars[-1].bar_at,
                source_kind=bars[-1].source_kind,
                close_points=bars[-1].close_points,
                prior_close_points=prior_close,
                session_change_ratio=None
                if prior_close is None
                else bars[-1].close_points / prior_close - Decimal(1),
                high_points=max(bar.high_points for bar in bars),
                low_points=min(bar.low_points for bar in bars),
                amount=None
                if any(bar.amount is None for bar in bars)
                else sum((bar.amount for bar in bars), Decimal(0)),
                bars=tuple(
                    MarketIndexBarView.model_validate(bar.model_dump(mode="python")) for bar in bars
                ),
            )
            integrity = latest is not None and bool(set(latest.issues) & _INTEGRITY_ISSUES)
            target = session.expected_bucket_at
            if integrity or prior_close is None or session.calendar_status == "UNKNOWN":
                status = "UNVERIFIED"
            elif not source_verified:
                status = "CACHED"
            elif target is not None and tuple(
                bar.bar_at for bar in bars
            ) == expected_display_buckets(target):
                status = "CURRENT"
            else:
                status = "INCOMPLETE"
    return MarketIndexOverviewItem(
        index_code=code,
        display_name=name,
        board=board,
        data_status=status,
        data=data,
        latest_acquisition=latest,
    )


class PersistentMarketIndexOverviewService:
    def __init__(self, unit_of_work_factory, *, clock, authority=lambda: (None, None, False)):
        self._work = unit_of_work_factory
        self._clock = clock
        self._authority = authority

    async def get_market_index_overview(self):
        captured = self._authority()
        now = self._clock().astimezone(SHANGHAI)
        try:
            value = await to_thread.run_sync(lambda: self._read(now, captured))
        except RepositoryError, SQLAlchemyError, ValidationError, ValueError:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None
        if self._authority() != captured:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        return value

    def _read(self, now, authority):
        generation, source_identity, source_current = authority
        with self._work() as work:
            days = work.references.list_trading_days(
                "SSE", now.date() - timedelta(days=366), now.date()
            )
            today = next((day for day in days if day.cal_date == now.date()), None)
            previous = max(
                (day.cal_date for day in days if day.is_open and day.cal_date < now.date()),
                default=None,
            )
            stored_date = None
            if today is None:
                latest_records = work.projections.list_latest_market_index_snapshots(
                    mapping_version=MAPPING_VERSION, index_codes=ALWAYS_ON_INDEX_CODES
                )
                stored_date = max(
                    (
                        record.snapshot.completed_bucket_at.date()
                        for record in latest_records
                        if record.snapshot.completed_bucket_at is not None
                        and record.snapshot.observed_at <= now
                        and record.snapshot.completed_bucket_at.date() <= now.date()
                    ),
                    default=None,
                )
            session = resolve_market_session(
                now,
                is_open=None if today is None else today.is_open,
                previous_open_date=previous,
                stored_date=stored_date,
            )
            attempts = {
                snap.index_code: (snap, observed)
                for snap, observed in work.projections.list_market_index_acquisitions(
                    mapping_version=MAPPING_VERSION
                )
            }
            recoveries = {
                record[0]: record for record in work.projections.list_market_index_recoveries()
            }
            selected = {}
            if session.display_trade_date is not None:
                start = datetime.combine(session.display_trade_date, time(9, 30), SHANGHAI)
                end = datetime.combine(session.display_trade_date, time(15), SHANGHAI)
                for code in ALWAYS_ON_INDEX_CODES:
                    target = session.expected_bucket_at
                    exact_records = (
                        ()
                        if target is None
                        else (
                            work.projections.list_market_index_snapshot_heads(
                                mapping_version=MAPPING_VERSION,
                                index_code=code,
                                start_at=target,
                                end_at=target,
                            )
                        )
                    )
                    exact = [
                        record.snapshot
                        for record in exact_records
                        if record.snapshot.health.value == "LIVE"
                        and record.snapshot.observed_at <= now
                        and record.snapshot.five_minute_bars
                    ]
                    if exact:
                        selected[code] = max(exact, key=snapshot_rank)
                        continue
                    records = work.projections.list_market_index_snapshot_heads(
                        mapping_version=MAPPING_VERSION, index_code=code, start_at=start, end_at=end
                    )
                    usable = [
                        record.snapshot
                        for record in records
                        if record.snapshot.five_minute_bars
                        and record.snapshot.observed_at <= now
                        and any(
                            bar.bar_at.date() == session.display_trade_date
                            for bar in record.snapshot.five_minute_bars
                        )
                    ]
                    selected[code] = max(usable, key=snapshot_rank, default=None)
            items = []
            for code in DASHBOARD_INDEX_CODES:
                attempt = attempts.get(code)
                recovery = recoveries.get(code)
                latest = (
                    None
                    if attempt is None
                    else MarketIndexLatestAcquisition(
                        decision_cutoff=attempt[0].decision_cutoff,
                        observed_at=attempt[1],
                        health=attempt[0].health,
                        issues=attempt[0].issues,
                        next_retry_at=None
                        if recovery is None or recovery[4] <= now
                        else recovery[4],
                    )
                )
                snapshot = selected.get(code)
                verified = (
                    snapshot is not None
                    and source_current
                    and work.projections.market_index_source_matches(snapshot, source_identity)
                )
                items.append(
                    build_overview_item(code, snapshot, session, latest, source_verified=verified)
                )
            turnover_inputs = tuple(selected.get(code) for code in MARKET_TURNOVER_INDEX_CODES)
            turnover = None
            if all(
                snap is not None
                and source_current
                and work.projections.market_index_source_matches(snap, source_identity)
                and snap.completed_bucket_at == session.expected_bucket_at
                for snap in turnover_inputs
            ):
                summary = build_market_turnover_summary(turnover_inputs)
                if summary is not None:
                    turnover = MarketTurnoverSummaryView.model_validate(
                        {
                            **summary.model_dump(mode="python"),
                            "benchmark_codes": MARKET_TURNOVER_INDEX_CODES,
                        }
                    )
            return MarketIndexOverviewResponse(
                observed_at=now,
                runtime_generation=generation,
                sequence=work.events.current_sequence(),
                market_session=session,
                indexes=tuple(items),
                market_turnover=turnover,
            )
