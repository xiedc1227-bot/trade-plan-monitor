"""Actual market repository writes revoke guard coverage in the same transaction."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from tests.unit.test_plan_buy_suspension_transition import apply, at, batch, minute

from trade_plan_monitor.state.daily_repository import DailyRepository, buy_suspension_record_id
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
from trade_plan_monitor.state.models import MinuteBar as MinuteRow
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.repositories import MarketHistoryRepository, MarketReferenceRepository

NOW = at("2026-10-09T16:00:00")


@pytest.fixture
def store(tmp_path):
    engine = create_sqlite_engine(tmp_path / "guard-market.sqlite3")
    upgrade_database(engine)
    yield engine
    engine.dispose()


def seed(session, *, latched=False):
    repo = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
    source = minute(at(), 2419 if latched else 2430)
    MarketHistoryRepository(session).upsert_minutes((source,))
    state = apply(value=batch(closes={at(): source.close_fen}))
    repo.lock_symbol(state.symbol)
    identity = buy_suspension_record_id(state.symbol, state.owner_plan_version_id)
    repo.save(identity, kind="BUY_SUSPENSION", symbol=state.symbol,
        lineage=state.owner_plan_version_id, payload=state.model_dump(mode="json"),
        expected_revision=0)
    return repo, identity, state, source


def test_accepted_minute_correction_revokes_clear_and_rollback_restores_both(store):
    with Session(store) as session:
        repo, identity, state, source = seed(session)
        session.commit()
        corrected = source.model_copy(update={"close_fen": 2419, "low_fen": 2419,
                                               "received_at": NOW})
        MarketHistoryRepository(session).upsert_minutes((corrected,))
        row = repo.get(identity)
        assert row["revision"] == 2
        assert row["payload"]["coverage"] is None
        assert row["payload"]["blocker"] == "PROOF_INVALIDATED"
        session.rollback()
        assert repo.get(identity)["revision"] == 1
        assert MarketHistoryRepository(session).list_minutes(
            state.symbol, start=at(), end=at()) == (source,)
        MarketHistoryRepository(session).upsert_minutes((corrected,))
        session.commit()
    with Session(store) as session:
        repo = DailyRepository(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        assert repo.get(identity)["payload"]["coverage"] is None
        assert MarketHistoryRepository(session).list_minutes(
            state.symbol, start=at(), end=at())[0].close_fen == 2419


def test_receipt_only_update_and_latched_correction_preserve_evidence(store):
    with Session(store) as session:
        repo, identity, state, source = seed(session)
        MarketHistoryRepository(session).upsert_minutes((source.model_copy(
            update={"received_at": NOW}),))
        assert repo.get(identity)["revision"] == 1
        session.rollback()
        repo, identity, state, source = seed(session, latched=True)
        MarketHistoryRepository(session).upsert_minutes((minute(at()).model_copy(
            update={"received_at": NOW}),))
        assert repo.get(identity)["payload"]["trigger"] == state.model_dump(mode="json")["trigger"]


def test_calendar_and_actual_factor_change_revoke_but_equal_factor_does_not(store):
    with Session(store) as session:
        repo, identity, state, source = seed(session)
        repo.invalidate_buy_suspension_market(symbol=state.symbol,
            start=state.definition.effective_from, end=state.target,
            factor=Decimal("2.75"))
        assert repo.get(identity)["revision"] == 1
        repo.invalidate_buy_suspension_market(symbol=state.symbol,
            start=state.definition.effective_from, end=state.target,
            factor=Decimal("2.76"))
        assert repo.get(identity)["revision"] == 2

        session.rollback()
        repo, identity, state, source = seed(session)
        cal = batch().calendar.model_copy(update={"is_open": False,
            "previous_trade_date": at().date() - timedelta(days=2)})
        MarketReferenceRepository(session).upsert_trading_days((cal,))
        assert repo.get(identity)["revision"] == 2


@pytest.mark.parametrize("surface", ["minute", "calendar"])
def test_reused_session_cannot_hide_a_committed_correction_behind_identity_cache(store, surface):
    with Session(store, expire_on_commit=False) as old:
        old_repo = DailyRepository(old, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        if surface == "minute":
            original = minute(at(), 2419)
            MarketHistoryRepository(old).upsert_minutes((original,))
            cached = old.get(MinuteRow, (original.symbol, at().isoformat()))
        else:
            original = batch().calendar.model_copy(update={"is_open": False})
            MarketReferenceRepository(old).upsert_trading_days((original,))
            cached = old.get(TradingCalendar, (original.exchange, original.cal_date))
        old.commit()
        with Session(store) as newer:
            DailyRepository(newer, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
            if surface == "minute":
                MarketHistoryRepository(newer).upsert_minutes((minute(at()).model_copy(
                    update={"received_at": NOW - timedelta(seconds=1)}),))
            else:
                MarketReferenceRepository(newer).upsert_trading_days((batch().calendar,))
            _, identity, _, _ = seed(newer)
            newer.commit()
        assert cached is not None  # Retain the actual old ORM object across transactions.
        if surface == "minute":
            MarketHistoryRepository(old).upsert_minutes((original.model_copy(
                update={"received_at": NOW}),))
        else:
            MarketReferenceRepository(old).upsert_trading_days((original,))
        assert old_repo.get(identity)["revision"] == 2
        assert old_repo.get(identity)["payload"]["coverage"] is None


@pytest.mark.parametrize("order", ["reader_first", "writer_first"])
def test_read_only_repository_never_claims_or_replaces_market_writer(store, order):
    with Session(store) as session:
        if order == "reader_first":
            DailyRepository(session, clock=lambda: NOW, id_factory=None)
            assert "buy_suspension_repository" not in session.info
        writer, identity, _, source = seed(session)
        session.commit()
        if order == "writer_first":
            DailyRepository(session, clock=lambda: NOW, id_factory=None)
        corrected = source.model_copy(update={
            "close_fen": 2419, "low_fen": 2419, "received_at": NOW})
        MarketHistoryRepository(session).upsert_minutes((corrected,))
        assert session.info["buy_suspension_repository"] is writer
        assert writer.get(identity)["revision"] == 2
        assert writer.get(identity)["payload"]["coverage"] is None
        session.commit()
        assert MarketHistoryRepository(session).list_minutes(
            source.symbol, start=source.bar_end, end=source.bar_end) == (corrected,)


def test_actual_source_coverage_read_preserves_unit_of_work_market_writer(store):
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    from trade_plan_monitor.state.source_coverage_authority import (
        _verify_buy_suspension_replacement_intent,
    )
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

    with Session(store) as session:
        _, identity, _, source = seed(session)
        session.commit()
    with SqlAlchemyUnitOfWork(sessionmaker(bind=store), clock=lambda: NOW) as work:
        _verify_buy_suspension_replacement_intent(work.daily.session,
            SimpleNamespace(id="absent-review"), None, clock=lambda: NOW)
        corrected = source.model_copy(update={
            "close_fen": 2419, "low_fen": 2419, "received_at": NOW})
        work.history.upsert_minutes((corrected,))
        assert work.daily.session.info["buy_suspension_repository"] is work.daily
        assert work.daily.get(identity)["revision"] == 2
        assert work.daily.get(identity)["payload"]["coverage"] is None
        work.commit()
