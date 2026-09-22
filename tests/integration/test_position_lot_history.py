"""Durable lot proof from real writes, adversarial storage and coherent snapshots."""

import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEventType, monitor_event_id
from trade_plan_monitor.state.models import AuditLog, MonitorSequence, PositionLot
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow
from trade_plan_monitor.state.position_lot_evidence import (
    ValidatedLotMutation,
    decode_position_lot_mutation,
)
from trade_plan_monitor.state.position_lot_history import (
    PositionLotHistoryReader,
    ProvenLotHistory,
    UnknownLotHistory,
)
from trade_plan_monitor.state.repositories import PositionLotRecord, _position_lot_hash
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = datetime(2026, 9, 22, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def engine(tmp_path):
    database = create_sqlite_engine(tmp_path / "history.sqlite3")
    upgrade_database(database)
    yield database
    database.dispose()


def buy(work):
    return work.positions.record_buy(
        symbol="003043.SZ", bucket="CORE", quantity=400,
        acquired_trade_date=date(2026, 9, 11), cost_fen=990,
        board_lot=100, max_position_qty=1600,
    )


def seed(engine, reductions=()):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW) as work:
        lot = buy(work)
        for quantity in reductions:
            work.positions.reduce_lot(lot.id, quantity=quantity, trade_date=date(2026, 9, 14))
        work.commit()
    return lot.id


def read(engine, lot_id, **kwargs):
    return PositionLotHistoryReader(create_session_factory(engine)).read(lot_id, **kwargs)


def mutate(engine, statement, **params):
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        connection.execute(text(statement), params)
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")


@pytest.mark.parametrize("reductions", [(), (100,), (400,), (100, 100, 200)])
def test_real_commits_prove_chain_and_survive_reopen(engine, reductions):
    lot_id = seed(engine, reductions)
    engine.dispose()
    result = read(engine, lot_id)
    assert isinstance(result, ProvenLotHistory)
    assert result.status == "PROVEN"
    assert result.current_lot.remaining_qty == 400 - sum(reductions)
    assert tuple(item.quantity for item in result.mutations) == (400, *reductions)
    assert result.publication_sequences == tuple(range(1, len(reductions) + 2))
    assert result.high_water_sequence == len(reductions) + 1
    with pytest.raises(FrozenInstanceError):
        result.high_water_sequence = 20


def test_backdated_source_dates_negative_clock_and_global_gaps_are_valid(engine):
    lot_id = seed(engine)
    for index, day in enumerate((18, 14), start=1):
        with SqlAlchemyUnitOfWork(
            create_session_factory(engine),
            clock=lambda index=index: NOW - timedelta(days=index * 10),
        ) as work:
            buy(work)
            work.positions.reduce_lot(lot_id, quantity=100, trade_date=date(2026, 9, day))
            work.commit()
    result = read(engine, lot_id)
    assert isinstance(result, ProvenLotHistory)
    assert result.publication_sequences == (1, 3, 5)
    assert result.mutations[-1].effective_trade_date == date(2026, 9, 14)


def test_rollback_and_missing_lot_do_not_claim_absence(engine):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW) as work:
        lot = buy(work)
    result = read(engine, lot.id)
    assert isinstance(result, UnknownLotHistory)
    assert result.reason == "MISSING_EVIDENCE"


@pytest.mark.parametrize("statement", [
    "DELETE FROM position_lot",
    "DELETE FROM audit_log",
    "DELETE FROM monitor_event",
    "DELETE FROM monitor_sequence",
])
def test_missing_required_evidence(engine, statement):
    lot_id = seed(engine)
    mutate(engine, statement)
    assert read(engine, lot_id).reason == "MISSING_EVIDENCE"


@pytest.mark.parametrize("statement", [
    "UPDATE position_lot SET remaining_qty=100",
    "UPDATE position_lot SET cost_fen=990.5",
    "UPDATE position_lot SET acquired_trade_date='20260911'",
    "UPDATE position_lot SET acquired_trade_date=2461294",
    "UPDATE position_lot SET symbol=CAST(symbol AS BLOB)",
    "UPDATE position_lot SET closed_at='2026-09-22T10:30:00+08:00'",
    "UPDATE audit_log SET action='OTHER'",
    "UPDATE audit_log SET before_hash='bad'",
    "UPDATE audit_log SET after_hash='bad'",
    "UPDATE audit_log SET created_at='2026-09-22T10:30:00'",
    "UPDATE monitor_event SET id=upper(id)",
    "UPDATE monitor_event SET occurred_at='2026-09-22T10:30:01+08:00'",
    "UPDATE monitor_event SET occurred_at='2026-09-22T02:30:00+00:00'",
    "UPDATE monitor_event SET event_type='system.health.updated'",
    "UPDATE monitor_event SET schema_version=2",
    "UPDATE monitor_event SET sequence=0",
    "UPDATE monitor_sequence SET last_sequence=0",
])
def test_strict_storage_corruption_is_unknown(engine, statement):
    lot_id = seed(engine)
    mutate(engine, statement)
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("table,column", [
    ("audit_log", "details_json"), ("audit_log", "action"),
    ("audit_log", "created_at"), ("position_lot", "symbol"),
    ("position_lot", "acquired_trade_date"), ("monitor_event", "payload_json"),
    ("monitor_event", "id"), ("monitor_event", "occurred_at"),
])
@pytest.mark.parametrize("suffix", ["\x00hidden", "x" * 20000, "界" * 6000],
                         ids=["nul", "oversized", "utf8-oversized"])
def test_sql_bounds_cannot_hide_nul_or_oversized_text(engine, table, column, suffix):
    lot_id = seed(engine)
    mutate(engine, f"UPDATE {table} SET {column}={column} || :suffix", suffix=suffix)
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("variant,reason", [
    ("legacy", "MISSING_EVIDENCE"), ("future", "UNSUPPORTED_VERSION"),
    ("boolean", "INVALID_EVIDENCE"), ("duplicate", "INVALID_EVIDENCE"),
])
def test_decoder_outcomes_are_preserved(engine, variant, reason):
    lot_id = seed(engine)
    with engine.connect() as connection:
        raw = connection.scalar(text("SELECT details_json FROM audit_log"))
    details = json.loads(raw)
    if variant == "legacy":
        del details["recoveryEvidence"]
    elif variant in ("future", "boolean"):
        details["recoveryEvidence"]["schemaVersion"] = 2 if variant == "future" else True
    raw = json.dumps(details)
    if variant == "duplicate":
        raw = raw[:-1] + ',"quantity":400}'
    mutate(engine, "UPDATE audit_log SET details_json=:raw", raw=raw)
    assert read(engine, lot_id).reason == reason


@pytest.mark.parametrize("transform", [
    lambda raw: raw.replace('"OPEN"', '"CLOSED"'),
    lambda raw: raw.replace("003043.SZ", "003044.SZ"),
    lambda raw: raw[:-1] + ',"status":"OPEN"}',
    lambda raw: raw[:-1] + ',"revision":null}',
    lambda raw: raw.replace("entityId", "entity_id"),
    lambda raw: " " + raw,
])
def test_publication_payload_must_be_exact_writer_canonical_json(engine, transform):
    lot_id = seed(engine)
    with engine.connect() as connection:
        raw = connection.scalar(text("SELECT payload_json FROM monitor_event"))
    mutate(engine, "UPDATE monitor_event SET payload_json=:raw", raw=transform(raw))
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("statement", [
    "DELETE FROM audit_log WHERE action='POSITION_BUY_RECORDED'",
    "DELETE FROM audit_log WHERE after_hash IN "
    "(SELECT before_hash FROM audit_log WHERE json_extract(details_json, "
    "'$.recoveryEvidence.after.remaining_qty')=200)",
    "INSERT INTO audit_log SELECT 'duplicate',action,entity_type,entity_id,before_hash,"
    "after_hash,details_json,created_at FROM audit_log LIMIT 1",
    "UPDATE monitor_event SET sequence=sequence+10 WHERE sequence=1",
])
def test_missing_root_gaps_duplicate_and_publication_order_cannot_prove(engine, statement):
    lot_id = seed(engine, (100, 100))
    mutate(engine, statement)
    assert isinstance(read(engine, lot_id), UnknownLotHistory)


def test_extraneous_aggregate_publication_and_audit_scope(engine):
    lot_id = seed(engine)
    mutate(engine, "INSERT INTO audit_log SELECT 'unrelated',action,'OTHER',entity_id,"
           "before_hash,after_hash,details_json,created_at FROM audit_log")
    assert isinstance(read(engine, lot_id), ProvenLotHistory)
    mutate(engine, "INSERT INTO monitor_event SELECT 'extra',2,'system.health.updated',"
           "1,aggregate_id,payload_json,occurred_at FROM monitor_event")
    mutate(engine, "UPDATE monitor_sequence SET last_sequence=2")
    assert isinstance(read(engine, lot_id), UnknownLotHistory)


def test_history_limit_counts_all_scoped_rows(engine):
    lot_id = seed(engine, (100,))
    assert read(engine, lot_id, max_mutations=1).reason == "HISTORY_LIMIT"
    assert isinstance(read(engine, lot_id, max_mutations=2), ProvenLotHistory)
    mutate(engine, "INSERT INTO monitor_event SELECT 'extra',3,'system.health.updated',"
           "1,aggregate_id,payload_json,occurred_at FROM monitor_event LIMIT 1")
    mutate(engine, "UPDATE monitor_sequence SET last_sequence=3")
    assert read(engine, lot_id, max_mutations=2).reason == "HISTORY_LIMIT"


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "3", None])
def test_invalid_limit_raises_before_opening_session(limit):
    def no_session():
        pytest.fail("invalid arguments must not open a session")
    with pytest.raises((ValueError, TypeError)):
        PositionLotHistoryReader(no_session).read("lot", max_mutations=limit)


@pytest.mark.parametrize("lot_id", [None, 1, "", " x", "x" * 129, "lot\x00tail"])
def test_invalid_identity_raises_before_opening_session(lot_id):
    with pytest.raises((ValueError, TypeError)):
        PositionLotHistoryReader(lambda: pytest.fail("unexpected session")).read(lot_id)


def test_nonfresh_session_is_rejected_without_flushing(engine):
    session = create_session_factory(engine)()
    session.add(AuditLog(id="pending"))
    with pytest.raises(ValueError, match="fresh"):
        PositionLotHistoryReader(lambda: session).read("lot")
    assert session.new
    session.close()


def test_reader_only_issues_bounded_selects_and_no_flush(engine):
    lot_id = seed(engine)
    session = create_session_factory(engine)()
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    event.listen(session, "before_flush", lambda *_: pytest.fail("reader flushed"))
    result = PositionLotHistoryReader(lambda: session).read(lot_id)
    assert isinstance(result, ProvenLotHistory)
    assert statements[0] == "BEGIN"
    assert all(sql == "BEGIN" or sql.lstrip().upper().startswith("SELECT") for sql in statements)
    for table in ("audit_log", "monitor_event"):
        queries = [sql for sql in statements if f"FROM {table}" in sql and "_bytes" in sql]
        assert len(queries) == 1 and "LIMIT" in queries[0] and "substr(" in queries[0]
    maximum = next(sql for sql in statements if "ORDER BY monitor_event.sequence DESC" in sql)
    assert "LIMIT" in maximum and "max(" not in maximum


def test_storage_failure_propagates(engine):
    lot_id = seed(engine)
    mutate(engine, "DROP TABLE audit_log")
    with pytest.raises(OperationalError):
        read(engine, lot_id)


def test_wal_commit_after_first_read_does_not_mix_snapshots(engine):
    lot_id = seed(engine)
    writer_engine = create_sqlite_engine(engine.url.database)
    fired = False
    def concurrent_commit(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal fired
        if fired or not statement.lstrip().upper().startswith("SELECT"):
            return
        fired = True
        with SqlAlchemyUnitOfWork(create_session_factory(writer_engine), clock=lambda: NOW) as work:
            work.positions.reduce_lot(lot_id, quantity=100, trade_date=date(2026, 9, 14))
            work.commit()
    event.listen(engine, "after_cursor_execute", concurrent_commit)
    result = read(engine, lot_id)
    event.remove(engine, "after_cursor_execute", concurrent_commit)
    writer_engine.dispose()
    assert fired and isinstance(result, ProvenLotHistory)
    assert result.current_lot.remaining_qty == 400
    assert result.publication_sequences == (1,)
    assert result.high_water_sequence == 1
    assert read(engine, lot_id).current_lot.remaining_qty == 300


@pytest.mark.parametrize("kind", ["branch", "orphan"])
def test_individually_valid_extra_mutation_and_publication_break_connected_chain(engine, kind):
    lot_id = seed(engine, (100,))
    with engine.connect() as connection:
        audit = dict(connection.execute(text(
            "SELECT * FROM audit_log WHERE action='POSITION_REDUCTION_RECORDED'"
        )).mappings().one())
        publication = dict(connection.execute(text(
            "SELECT * FROM monitor_event WHERE sequence=2"
        )).mappings().one())
    details = json.loads(audit["details_json"])
    before = details["recoveryEvidence"]["before"]
    after = details["recoveryEvidence"]["after"]
    before["remaining_qty"] = 400 if kind == "branch" else 250
    after["remaining_qty"] = 200
    details["quantity"] = before["remaining_qty"] - 200
    audit.update(
        id="extra-mutation", details_json=json.dumps(details),
        before_hash=_position_lot_hash(PositionLotRecord.model_validate(before)),
        after_hash=_position_lot_hash(PositionLotRecord.model_validate(after)),
    )
    assert isinstance(decode_position_lot_mutation(
        **{key: value for key, value in audit.items() if key != "id"}
    ), ValidatedLotMutation)
    publication.update(
        id=str(monitor_event_id(MonitorEventType.POSITION_UPDATED, lot_id, "200")), sequence=3,
    )
    with engine.begin() as connection:
        for table, row in (("audit_log", audit), ("monitor_event", publication)):
            connection.execute(text(
                f"INSERT INTO {table} ({','.join(row)}) VALUES "
                f"({','.join(':' + key for key in row)})"
            ), row)
        connection.execute(text("UPDATE monitor_sequence SET last_sequence=3"))
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


def test_deleted_middle_publication_never_proves(engine):
    lot_id = seed(engine, (100, 100))
    mutate(engine, "DELETE FROM monitor_event WHERE sequence=2")
    assert isinstance(read(engine, lot_id), UnknownLotHistory)


def test_long_custom_id_and_nonstandard_board_lot(engine):
    identities = iter(("x" * 64, "custom-buy-audit", "custom-sell-audit"))
    with SqlAlchemyUnitOfWork(
        create_session_factory(engine), clock=lambda: NOW, id_factory=lambda: next(identities),
    ) as work:
        lot = work.positions.record_buy(
            symbol="830001.BJ", bucket="TACTICAL", quantity=14,
            acquired_trade_date=date(2026, 9, 11), cost_fen=123,
            board_lot=7, max_position_qty=28,
        )
        work.commit()
    result = read(engine, lot.id)
    assert isinstance(result, ProvenLotHistory) and result.current_lot.remaining_qty == 14


def test_closure_timestamp_need_not_equal_audit_timestamp(engine):
    lot_id = seed(engine)
    ticks = iter(NOW + timedelta(seconds=index) for index in range(20))
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: next(ticks)) as work:
        work.positions.reduce_lot(lot_id, quantity=400, trade_date=date(2026, 9, 14))
        work.commit()
    result = read(engine, lot_id)
    assert isinstance(result, ProvenLotHistory)
    assert result.current_lot.closed_at != result.mutations[-1].created_at


@pytest.mark.parametrize("size,proven", [(16384, True), (16385, False)])
def test_audit_byte_budget_exact_boundary(engine, size, proven):
    lot_id = seed(engine)
    with engine.connect() as connection:
        raw = connection.scalar(text("SELECT details_json FROM audit_log"))
    mutate(engine, "UPDATE audit_log SET details_json=:raw", raw=raw.ljust(size))
    assert isinstance(read(engine, lot_id), ProvenLotHistory) is proven


@pytest.mark.parametrize("table,column", [
    ("position_lot", "quantity"), ("position_lot", "cost_fen"),
    ("monitor_event", "sequence"), ("monitor_event", "schema_version"),
    ("monitor_sequence", "last_sequence"),
])
def test_wrong_type_numeric_storage_is_bounded_and_unknown(engine, table, column):
    lot_id = seed(engine)
    mutate(engine, f"UPDATE {table} SET {column}=:bad", bad="x" * 20000)
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("table,column", [
    ("position_lot", "symbol"), ("audit_log", "details_json"),
    ("monitor_event", "payload_json"),
])
@pytest.mark.parametrize("storage", ["blob", "text"])
def test_invalid_utf8_storage_returns_unknown(engine, table, column, storage):
    lot_id = seed(engine)
    expression = ":bad" if storage == "blob" else "CAST(:bad AS TEXT)"
    mutate(engine, f"UPDATE {table} SET {column}={expression}", bad=b"\xff")
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


def test_nonstandard_board_lot_reductions_remain_provable(engine):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: NOW) as work:
        lot = work.positions.record_buy(
            symbol="830001.BJ", bucket="TACTICAL", quantity=14,
            acquired_trade_date=date(2026, 9, 11), cost_fen=123,
            board_lot=7, max_position_qty=28,
        )
        work.positions.reduce_lot(lot.id, quantity=7, trade_date=date(2026, 9, 14), board_lot=7)
        work.commit()
    result = read(engine, lot.id)
    assert isinstance(result, ProvenLotHistory) and result.current_lot.remaining_qty == 7


def test_publication_sequence_reordering_within_highwater_is_invalid(engine):
    lot_id = seed(engine, (100, 100))
    mutate(engine, "UPDATE monitor_event SET sequence=10 WHERE sequence=1")
    mutate(engine, "UPDATE monitor_sequence SET last_sequence=10")
    assert read(engine, lot_id).reason == "INVALID_EVIDENCE"


@pytest.mark.parametrize("routing", ["connection", "model", "table"])
def test_reader_rejects_external_uncommitted_transaction_without_touching_writer(engine, routing):
    factory = create_session_factory(engine)
    writer = factory()
    with SqlAlchemyUnitOfWork(lambda: writer, clock=lambda: NOW) as work:
        lot = buy(work)
        connection = writer.connection()
        models = (MonitorSequence, MonitorRow, AuditLog, PositionLot)
        if routing == "connection":
            reader_session = factory(bind=connection)
        else:
            keys = models if routing == "model" else tuple(model.__table__ for model in models)
            reader_session = factory(binds=dict.fromkeys(keys, connection))
        statements = []
        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        event.listen(writer, "before_flush", lambda *_: pytest.fail("writer flushed"))
        with pytest.raises(ValueError, match="engine"):
            PositionLotHistoryReader(lambda: reader_session).read(lot.id)
        event.remove(engine, "before_cursor_execute", capture)
        assert not statements and not reader_session.in_transaction()
        assert not connection.closed and connection.in_transaction() and writer.in_transaction()
        assert writer.scalar(text("SELECT count(*) FROM position_lot")) == 1
        reader_session.close()
    assert read(engine, lot.id).reason == "MISSING_EVIDENCE"


def test_reader_rejects_single_model_routing_to_another_database(engine, tmp_path):
    other_engine = create_sqlite_engine(tmp_path / "other.sqlite3")
    session = create_session_factory(engine)(binds={PositionLot: other_engine})
    with pytest.raises(ValueError, match="one engine"):
        PositionLotHistoryReader(lambda: session).read("lot")
    assert not session.in_transaction()
    session.close()
    other_engine.dispose()
