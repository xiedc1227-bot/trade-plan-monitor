"""Committed overview/session display contracts for ICDR acceptance."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_index_close_retention import (
    _FAILURE_AT,
    _FINAL_TARGET,
    _INDEX,
    _SUCCESS_AT,
    _failed_capture,
    _live_capture,
    _provider_batch,
)

from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_index.models import MarketIndexSnapshot
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES, DASHBOARD_INDEX_CODES
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
from trade_plan_monitor.state.models import MarketIndexAcquisitionState
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_pagination import BacktestApiCursorSigner
from trade_plan_monitor.web.market_index_overview import PersistentMarketIndexOverviewService
from trade_plan_monitor.web.persistent_market_index_history import (
    PersistentMarketIndexHistorySource,
)
from trade_plan_monitor.web.routers.market_indexes import (
    MarketIndexOverviewResponse,
    SignedMarketIndexHistoryService,
)

_SOURCE = "a" * 64
_NOW = _FINAL_TARGET + timedelta(hours=1, minutes=41)
_OVERVIEW_PATH = "/api/v1/market-indexes/overview"


class _OverviewDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine: Engine = create_sqlite_engine(path)
        upgrade_database(self.engine)
        self.sessions: sessionmaker[Session] = create_session_factory(self.engine)
        self.now: datetime = _NOW
        self.generation: UUID = uuid4()
        self.source: str | None = _SOURCE
        self.read_calls = 0

    def work(self) -> SqlAlchemyUnitOfWork:
        self.read_calls += 1
        return SqlAlchemyUnitOfWork(self.sessions, clock=lambda: self.now)

    def service(self) -> PersistentMarketIndexOverviewService:
        return PersistentMarketIndexOverviewService(
            self.work,
            clock=lambda: self.now,
            authority=lambda: (self.generation, self.source, True),
        )

    def seed_calendar(self) -> None:
        with self.work() as work:
            work.references.upsert_trading_days(
                tuple(
                    TradingDay(
                        exchange="SSE",
                        cal_date=_FINAL_TARGET.replace(day=day).date(),
                        is_open=True,
                        previous_trade_date=_FINAL_TARGET.replace(day=day - 1).date(),
                    )
                    for day in (8, 9)
                )
            )
            work.commit()

    def store(self, snapshot: MarketIndexSnapshot, *, source: str | None = _SOURCE) -> None:
        with self.work() as work:
            work.projections.put_market_index_snapshot(
                snapshot,
                provider_content_revision=snapshot.revision,
            )
            work.projections.advance_market_index_head(
                snapshot,
                provider_content_revision=snapshot.revision,
            )
            captured_event = work.events.append(
                MonitorEventDraft(
                    event_id=monitor_event_id(
                        MonitorEventType.MARKET_INDEX_UPDATED,
                        snapshot.index_code.value,
                        snapshot.snapshot_hash,
                    ),
                    event_type=MonitorEventType.MARKET_INDEX_UPDATED,
                    aggregate_id=snapshot.index_code.value,
                    payload=MonitorEventPayload(
                        entity_id=snapshot.index_code.value,
                        revision=snapshot.revision,
                        status=snapshot.health.value,
                    ),
                    occurred_at=snapshot.observed_at,
                )
            )
            work.projections.put_market_index_acquisition(
                snapshot,
                observed_at=snapshot.observed_at,
                sequence=captured_event.sequence,
                source_identity=source,
            )
            work.commit()

    def reopen(self) -> None:
        self.engine.dispose()
        self.engine = create_sqlite_engine(self.path)
        self.sessions = create_session_factory(self.engine)


@pytest.fixture
def overview_db(tmp_path: Path):
    database = _OverviewDatabase(tmp_path / "overview.db")
    try:
        yield database
    finally:
        database.engine.dispose()


def _response(service):
    client = TestClient(
        create_app(market_index_read_service=service),
        raise_server_exceptions=False,
    )
    try:
        return client.get(_OVERVIEW_PATH)
    finally:
        client.close()


def _snapshot_with_missing_data(
    *,
    remove_bar: Callable[[datetime], bool] | None = None,
    include_prior: bool = True,
    missing_amount: bool = False,
) -> MarketIndexSnapshot:
    batch = _provider_batch()
    bars = tuple(
        bar.model_copy(update={"amount": None})
        if missing_amount and bar.bar_at == _FINAL_TARGET
        else bar
        for bar in batch.five_minute_bars
        if remove_bar is None or not remove_bar(bar.bar_at)
    )
    return build_market_index_snapshot(
        index_code=_INDEX,
        decision_cutoff=_FINAL_TARGET,
        requests=(),
        five_minute_bars=bars,
        official_daily_bars=batch.official_daily_bars if include_prior else (),
        content_revision=batch.content_revision,
        observed_at=batch.observed_at,
        observed_no_later_than=batch.observed_at,
    )


@pytest.mark.parametrize("reopen", (False, True), ids=("A01", "A02"))
def test_actual_overview_keeps_close_and_48_bars_after_latest_failure(
    overview_db: _OverviewDatabase,
    reopen: bool,
) -> None:
    overview_db.seed_calendar()
    for code in ALWAYS_ON_INDEX_CODES:
        overview_db.store(_live_capture(index_code=code))
    failed = _failed_capture()
    overview_db.store(failed)
    if reopen:
        overview_db.reopen()

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.content) <= 512 * 1024
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["runtimeGeneration"] == str(overview_db.generation)
    assert body["marketSession"] == {
        "phase": "CLOSED",
        "calendarStatus": "KNOWN",
        "sessionDate": "2026-10-09",
        "displayTradeDate": "2026-10-09",
        "expectedBucketAt": _FINAL_TARGET.isoformat(),
    }
    assert tuple(item["indexCode"] for item in body["indexes"]) == tuple(
        code.value for code in DASHBOARD_INDEX_CODES
    )
    sse = body["indexes"][0]
    assert sse["displayName"] == "上证指数"
    assert sse["dataStatus"] == "CURRENT"
    assert sse["data"]["observedAt"] == _SUCCESS_AT.isoformat()
    assert sse["data"]["closePoints"] == "3813.791"
    assert sse["data"]["completedBucketAt"] == _FINAL_TARGET.isoformat()
    assert len(sse["data"]["bars"]) == 48
    assert sse["data"]["bars"][-1]["closePoints"] == sse["data"]["closePoints"]
    assert sse["data"]["bars"][-1]["barAt"] == sse["data"]["completedBucketAt"]
    assert sse["latestAcquisition"] == {
        "decisionCutoff": _FINAL_TARGET.isoformat(),
        "observedAt": _FAILURE_AT.isoformat(),
        "health": "BLOCKED",
        "issues": ["PROVIDER_UNAVAILABLE"],
        "nextRetryAt": None,
    }
    assert all(item["dataStatus"] == "CURRENT" for item in body["indexes"])
    assert body["marketTurnover"] is not None
    with overview_db.work() as work:
        assert work.projections.get_market_index_snapshot(failed.snapshot_hash).snapshot == failed


def test_overview_reads_one_local_transaction_without_writes_or_events(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()
    live = _live_capture()
    overview_db.store(live)
    with overview_db.work() as work:
        sequence_before = work.events.current_sequence()
    overview_db.read_calls = 0
    transactions = []
    statements = []

    def begin(connection) -> None:
        transactions.append(connection)

    def execute(connection, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement.strip().split(None, 1)[0].upper())

    event.listen(overview_db.engine, "begin", begin)
    event.listen(overview_db.engine, "before_cursor_execute", execute)
    try:
        response = _response(overview_db.service())
    finally:
        event.remove(overview_db.engine, "begin", begin)
        event.remove(overview_db.engine, "before_cursor_execute", execute)

    assert response.status_code == 200, response.text
    assert overview_db.read_calls == 1
    assert len(transactions) == 1
    assert not ({"INSERT", "UPDATE", "DELETE", "REPLACE"} & set(statements))
    assert response.json()["sequence"] == sequence_before
    with overview_db.work() as work:
        assert work.events.current_sequence() == sequence_before
        assert work.projections.get_market_index_snapshot(live.snapshot_hash).snapshot == live


@pytest.mark.parametrize("missing", ("tail", "internal"), ids=("47-bars", "internal-gap"))
def test_closed_incomplete_data_does_not_claim_current(
    overview_db: _OverviewDatabase,
    missing: str,
) -> None:
    overview_db.seed_calendar()
    cutoff = _FINAL_TARGET if missing == "tail" else _FINAL_TARGET.replace(hour=10, minute=0)
    snapshot = _snapshot_with_missing_data(remove_bar=lambda at: at == cutoff)
    overview_db.store(snapshot)

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marketSession"]["phase"] == "CLOSED"
    sse = body["indexes"][0]
    assert sse["dataStatus"] == "INCOMPLETE"
    assert len(sse["data"]["bars"]) == 47
    assert all(bar["barAt"] != cutoff.isoformat() for bar in sse["data"]["bars"])
    expected_tail = _FINAL_TARGET - timedelta(minutes=5) if missing == "tail" else _FINAL_TARGET
    assert sse["data"]["completedBucketAt"] == expected_tail.isoformat()
    assert body["marketTurnover"] is None


def test_missing_prior_close_retains_points_but_does_not_invent_ratio(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_snapshot_with_missing_data(include_prior=False))

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    sse = response.json()["indexes"][0]
    assert sse["dataStatus"] == "UNVERIFIED"
    assert sse["data"]["closePoints"] == "3813.791"
    assert len(sse["data"]["bars"]) == 48
    assert sse["data"]["priorClosePoints"] is None
    assert sse["data"]["sessionChangeRatio"] is None


def test_missing_amount_returns_null_without_discarding_points(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_snapshot_with_missing_data(missing_amount=True))

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    data = response.json()["indexes"][0]["data"]
    assert data["amount"] is None
    assert data["bars"][-1]["amount"] is None
    assert data["closePoints"] == "3813.791"


def test_unknown_calendar_never_certifies_closed_or_current(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.store(_live_capture())

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marketSession"]["phase"] == "UNKNOWN"
    assert body["marketSession"]["calendarStatus"] == "UNKNOWN"
    assert body["marketSession"]["expectedBucketAt"] is None
    assert body["marketSession"]["displayTradeDate"] == "2026-10-09"
    assert body["indexes"][0]["dataStatus"] == "UNVERIFIED"
    assert len(body["indexes"][0]["data"]["bars"]) == 48
    assert body["marketTurnover"] is None


@pytest.mark.parametrize("stored_source", (_SOURCE, None), ids=("changed-source", "unbound-source"))
def test_source_mismatch_is_cached_and_keeps_original_cutoff(
    overview_db: _OverviewDatabase,
    stored_source: str | None,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_live_capture(), source=stored_source)
    if stored_source is not None:
        overview_db.source = "b" * 64

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["indexes"][0]["dataStatus"] == "CACHED"
    assert body["indexes"][0]["data"]["completedBucketAt"] == _FINAL_TARGET.isoformat()
    assert body["indexes"][0]["data"]["observedAt"] == _SUCCESS_AT.isoformat()
    assert body["marketTurnover"] is None


def test_legacy_signed_history_keeps_the_final_48th_bar(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_live_capture())
    overview_db.store(_failed_capture())
    history = SignedMarketIndexHistoryService(
        source=PersistentMarketIndexHistorySource(overview_db.work),
        cursor_signer=BacktestApiCursorSigner(b"i" * 32),
    )
    client = TestClient(create_app(market_index_read_service=history))
    try:
        response = client.get(
            "/api/v1/market-indexes/000001.SH/bars",
            params={
                "interval": "FIVE_MINUTE",
                "startAt": _FINAL_TARGET.replace(hour=9, minute=30).isoformat(),
                "endAt": _NOW.isoformat(),
                "limit": 64,
            },
        )
    finally:
        client.close()

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 48
    assert body["items"][-1]["barAt"] == _FINAL_TARGET.isoformat()
    assert body["items"][-1]["closePoints"] == "3813.791"
    assert body["hasMore"] is False
    assert body["nextCursor"] is None


def test_empty_overview_keeps_exactly_four_explicit_empty_cards(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()

    response = _response(overview_db.service())

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["indexes"]) == 4
    assert body["indexes"][0]["indexCode"] == "000001.SH"
    assert all(item["dataStatus"] == "EMPTY" for item in body["indexes"])
    assert all(item["data"] is None for item in body["indexes"])
    assert all(item["latestAcquisition"] is None for item in body["indexes"])
    assert body["marketTurnover"] is None


@pytest.mark.parametrize(
    "path",
    (
        (),
        ("marketSession",),
        ("indexes", 0),
        ("indexes", 0, "data"),
        ("indexes", 0, "data", "bars", 0),
        ("indexes", 0, "latestAcquisition"),
    ),
)
def test_overview_json_contract_rejects_unexpected_fields(
    overview_db: _OverviewDatabase,
    path: tuple,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_live_capture())
    original = asyncio.run(overview_db.service().get_market_index_overview())
    payload = deepcopy(json.loads(original.model_dump_json(by_alias=True)))
    target = payload
    for part in path:
        target = target[part]
    target["unexpected"] = True

    with pytest.raises(ValidationError, match="extra_forbidden"):
        MarketIndexOverviewResponse.model_validate_json(json.dumps(payload))


def test_overview_route_rejects_response_larger_than_512_kib(
    overview_db: _OverviewDatabase,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_live_capture())
    original = asyncio.run(overview_db.service().get_market_index_overview())
    payload = json.loads(original.model_dump_json(by_alias=True))
    data = payload["indexes"][0]["data"]
    # Legal finite decimal fields can exceed the aggregate response budget.
    points = "1" + "0" * 3999
    for bar in data["bars"]:
        for field in ("openPoints", "highPoints", "lowPoints", "closePoints"):
            bar[field] = points
    for field in ("highPoints", "lowPoints", "closePoints"):
        data[field] = points
    data["sessionChangeRatio"] = format(
        Decimal(points) / Decimal(data["priorClosePoints"]) - Decimal(1),
        "f",
    )
    MarketIndexOverviewResponse.model_validate_json(json.dumps(payload))
    assert len(json.dumps(payload).encode("utf-8")) > 512 * 1024

    class OversizedReader:
        async def get_market_index_overview(self):
            return payload

    response = _response(OversizedReader())

    assert response.status_code == 503
    assert len(response.content) < 512 * 1024


@pytest.mark.parametrize("field", ("request_set_hash", "decision_cutoff"))
def test_corrupt_latest_acquisition_identity_returns_sanitized_503(
    overview_db: _OverviewDatabase,
    field: str,
) -> None:
    overview_db.seed_calendar()
    live = _live_capture()
    overview_db.store(live)
    with overview_db.work() as work:
        sequence_before = work.events.current_sequence()
    corrupted_value = (
        "b" * 64
        if field == "request_set_hash"
        else (_FINAL_TARGET - timedelta(minutes=5)).isoformat()
    )
    with Session(overview_db.engine) as session:
        row = session.get(
            MarketIndexAcquisitionState,
            (
                live.mapping_version,
                live.index_code.value,
            ),
        )
        assert row is not None
        setattr(row, field, corrupted_value)
        session.commit()

    response = _response(overview_db.service())

    assert response.status_code == 503, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "requestId"}
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["message"] == "Service unavailable"
    assert body["error"]["details"] == []
    assert re.fullmatch(r"[0-9a-f]{32}", body["error"]["requestId"])
    assert body["error"]["requestId"] == response.headers["X-Request-ID"]
    assert corrupted_value not in response.text
    assert "Invalid index acquisition linkage" not in response.text
    assert field not in response.text
    with overview_db.work() as work:
        assert work.events.current_sequence() == sequence_before
        assert work.projections.get_market_index_snapshot(live.snapshot_hash).snapshot == live


@pytest.mark.parametrize("fence", ["configuration", "generation", "admission", "semantics"])
def test_display_source_authority_rejects_revocation_without_publish(fence: str) -> None:
    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline

    current = {"configuration": True, "generation": True, "admission": True, "semantics": True}
    pipeline = object.__new__(ProductionMonitorPipeline)
    pipeline._configuration_current = lambda: current["configuration"]
    pipeline._generation_current = lambda: current["generation"]
    pipeline._admission_revoked = lambda: not current["admission"]
    pipeline._semantic_bindings = object()
    pipeline._index_semantics = object()
    pipeline._load_semantic_binding = lambda _surface: object() if current["semantics"] else None
    revoked = []
    pipeline._on_semantic_revoked = lambda: revoked.append(True)
    assert pipeline.index_display_source_current() is True
    current[fence] = False
    assert pipeline.index_display_source_current() is False
    assert revoked == []


def test_known_calendar_reads_complete_target_without_whole_history_scan(
    overview_db: _OverviewDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overview_db.seed_calendar()
    overview_db.store(_live_capture())
    from trade_plan_monitor.state.projections import ProjectionRepository

    def refuse_history_scan(*_args, **_kwargs):
        pytest.fail("Known calendar overview must not decode all historical heads")

    monkeypatch.setattr(
        ProjectionRepository, "list_latest_market_index_snapshots", refuse_history_scan
    )
    response = _response(overview_db.service())
    assert response.status_code == 200
    assert response.json()["indexes"][0]["data"]["closePoints"] == "3813.791"
    assert len(response.json()["indexes"][0]["data"]["bars"]) == 48
