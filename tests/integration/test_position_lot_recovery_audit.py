"""Writer evidence preserves accepted dates and exact lot mutation snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEventType, monitor_event_id
from trade_plan_monitor.state.models import (
    AuditLog,
    MonitorEvent,
    MonitorSequence,
    PositionInventoryState,
    PositionLot,
)
from trade_plan_monitor.state.repositories import PositionRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 22, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    database = create_sqlite_engine(tmp_path / "lot-evidence.sqlite3")
    upgrade_database(database)
    try:
        yield database
    finally:
        database.dispose()


def _work(engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW)


def _snapshot(
    lot_id: str,
    remaining: int,
    *,
    closed: bool = False,
) -> dict[str, object]:
    return {
        "id": lot_id,
        "symbol": "003043.SZ",
        "bucket": "CORE",
        "quantity": 400,
        "remaining_qty": remaining,
        "acquired_trade_date": "2026-09-11",
        "cost_fen": 990,
        "related_alert_id": None,
        "closed_at": NOW.isoformat() if closed else None,
    }


def _legacy_hash(snapshot: dict[str, object]) -> str:
    # Independently encode the existing camelCase hash contract, not the new envelope.
    payload = {
        "id": snapshot["id"],
        "symbol": snapshot["symbol"],
        "bucket": snapshot["bucket"],
        "quantity": snapshot["quantity"],
        "remainingQty": snapshot["remaining_qty"],
        "acquiredTradeDate": snapshot["acquired_trade_date"],
        "costFen": snapshot["cost_fen"],
        "relatedAlertId": snapshot["related_alert_id"],
        "closedAt": snapshot["closed_at"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _buy(work: SqlAlchemyUnitOfWork):
    return work.positions.record_buy(
        symbol="003043.SZ",
        bucket="CORE",
        quantity=400,
        acquired_trade_date=date(2026, 9, 11),
        cost_fen=990,
        board_lot=100,
        max_position_qty=800,
    )


@pytest.mark.parametrize("reductions", [(), (100,), (400,), (100, 100)])
def test_delayed_mutations_keep_exact_source_date_snapshots_and_hashes(
    engine: Engine,
    reductions: tuple[int, ...],
) -> None:
    with _work(engine) as work:
        lot = _buy(work)
        for quantity in reductions:
            work.positions.reduce_lot(
                lot.id,
                quantity=quantity,
                trade_date=date(2026, 9, 14),
            )
        work.commit()

    with create_session_factory(engine)() as session:
        events = session.scalars(select(MonitorEvent).order_by(MonitorEvent.sequence)).all()
        audits_by_hash = {row.after_hash: row for row in session.scalars(select(AuditLog)).all()}
    expected = [(None, _snapshot(lot.id, 400), 400, "2026-09-11")]
    remaining = 400
    for quantity in reductions:
        before = _snapshot(lot.id, remaining)
        remaining -= quantity
        after = _snapshot(lot.id, remaining, closed=remaining == 0)
        expected.append((before, after, quantity, "2026-09-14"))
    assert len(audits_by_hash) == len(expected)
    assert [event.id for event in events] == [
        str(
            monitor_event_id(MonitorEventType.POSITION_UPDATED, lot.id, str(after["remaining_qty"]))
        )
        for _, after, _, _ in expected
    ]
    for before, after, quantity, effective_date in reversed(expected):
        audit = audits_by_hash[_legacy_hash(after)]
        assert audit.entity_type == "POSITION_LOT"
        assert audit.entity_id == lot.id
        assert audit.action == (
            "POSITION_BUY_RECORDED" if before is None else "POSITION_REDUCTION_RECORDED"
        )
        assert audit.created_at == NOW.isoformat()
        assert audit.before_hash == (None if before is None else _legacy_hash(before))
        assert audit.after_hash == _legacy_hash(after)
        assert json.loads(audit.details_json) == {
            "bucket": "CORE",
            "quantity": quantity,
            "symbol": "003043.SZ",
            "recoveryEvidence": {
                "schemaVersion": 1,
                "effectiveTradeDate": effective_date,
                "before": before,
                "after": after,
            },
        }


def _persisted_state(engine: Engine) -> dict[str, list[tuple]]:
    with engine.connect() as connection:
        return {
            model.__tablename__: [tuple(row) for row in connection.execute(select(model.__table__))]
            for model in (
                PositionLot,
                AuditLog,
                MonitorEvent,
                MonitorSequence,
                PositionInventoryState,
            )
        }


@pytest.mark.parametrize("mutation", ["buy", "partial", "full"])
def test_failure_rolls_back_lot_audit_event_and_inventory_revision(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    with _work(engine) as work:
        original = _buy(work)
        work.commit()
    before = _persisted_state(engine)

    def fail_after_writes(repository: PositionRepository, symbol: str, **kwargs: object) -> None:
        # This hook runs after audit, monitor event and inventory revision were flushed.
        del repository, symbol, kwargs
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(PositionRepository, "_sync_inventory_confirmation", fail_after_writes)
    with pytest.raises(RuntimeError, match="injected failure before commit"), _work(engine) as work:
        if mutation == "buy":
            _buy(work)
        else:
            work.positions.reduce_lot(
                original.id,
                quantity=100 if mutation == "partial" else 400,
                trade_date=date(2026, 9, 14),
            )
        work.commit()

    assert _persisted_state(engine) == before


def test_new_mutation_does_not_rewrite_legacy_audit(engine: Engine) -> None:
    legacy = {
        "id": "legacy-position-audit",
        "action": "POSITION_REDUCTION_RECORDED",
        "entity_type": "POSITION_LOT",
        "entity_id": "legacy-lot",
        "before_hash": "a" * 64,
        "after_hash": "b" * 64,
        "details_json": '{"bucket":"CORE","quantity":100,"symbol":"003043.SZ"}',
        "created_at": "2026-09-10T10:30:00+08:00",
    }
    with engine.begin() as connection:
        connection.execute(AuditLog.__table__.insert().values(**legacy))
    with _work(engine) as work:
        _buy(work)
        work.commit()
    with engine.connect() as connection:
        restored = (
            connection.execute(select(AuditLog.__table__).where(AuditLog.id == legacy["id"]))
            .mappings()
            .one()
        )
    assert dict(restored) == legacy


@pytest.mark.parametrize("mutation", ["buy", "partial", "full"])
def test_unsupported_utc_clock_preserves_existing_rejection_and_rolls_back(
    engine: Engine,
    mutation: str,
) -> None:
    # Position events already require an Asia/Shanghai write clock. Evidence does not
    # broaden that admission contract, even when the audit has already been flushed.
    with _work(engine) as work:
        original = _buy(work)
        work.commit()
    before = _persisted_state(engine)
    with (
        pytest.raises(ValidationError, match="timestamp timezone must be Asia/Shanghai"),
        SqlAlchemyUnitOfWork(
            create_session_factory(engine),
            clock=lambda: NOW.astimezone(UTC),
        ) as work,
    ):
        if mutation == "buy":
            _buy(work)
        else:
            work.positions.reduce_lot(
                original.id,
                quantity=100 if mutation == "partial" else 400,
                trade_date=date(2026, 9, 14),
            )
        work.commit()
    assert _persisted_state(engine) == before
