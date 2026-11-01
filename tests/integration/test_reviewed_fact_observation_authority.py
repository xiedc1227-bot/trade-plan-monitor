"""Recorded ordinary minute observation recheck on real temporary SQL.

Signals are explicit typed engineering arrangements; FACTs use actual private
admission. Fixture setup prepares market history. Read checks never fill it.
"""

from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, select, update
from tests.integration.test_reviewed_fact_target_authority import (
    _check,
    _proof,
    _register,
    _save_signal,
    _variant,
)
from tests.integration.test_reviewed_fact_target_registration import _current
from tests.integration.test_reviewed_fact_target_runtime import _minute_at_current_clock
from tests.integration.test_unified_runtime import minute_inputs

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.models import FiveMinuteBar as FiveMinuteRow
from trade_plan_monitor.state.models import MinuteBar as MinuteRow
from trade_plan_monitor.state.reviewed_fact_authority import signal_fact_evidence_satisfied
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError


def _ready(chain):
    return _save_signal(chain, [_proof(chain, [_register(chain, i) for i in range(2)])])


def _save_fact(chain, row, payload):
    with chain.plans._unit_of_work() as work:
        work.daily.save(row["id"], kind="FACT", symbol=chain.plan.symbol,
            lineage=row["lineage"], expected_revision=row["revision"], payload=payload)
        work.commit()


@pytest.mark.parametrize("damage", ["missing-observation", "wrong-bar", "source-correction"])
def test_actual_sql_observation_cannot_borrow_missing_other_bar_or_corrected_source(
        tmp_path, damage):
    with _current(tmp_path) as chain:
        facts = [_register(chain, i) for i in range(2)]
        identity = _save_signal(chain, [_proof(chain, facts)])
        assert _check(chain, identity)
        inputs = minute_inputs(chain)
        if damage == "missing-observation":
            payload = deepcopy(facts[0]["payload"])
            payload.pop("reviewed_fact_observation")  # Readable legacy shape, never a null bypass.
            _save_fact(chain, facts[0], payload)
        elif damage == "wrong-bar":
            chain.now += timedelta(minutes=5)
            later = _minute_at_current_clock(chain, inputs)
            with chain.plans._unit_of_work() as work:
                work.history.upsert_minutes(later.minute_prefix)
                work.history.upsert_five_minute(**later.five_minute_bars[-1].model_dump())
                signal = work.daily.get(identity)
                # Deliberate typed counterexample: the stored signal now names
                # 09:40, but its cited registered FACTs still observe09:35.
                work.daily.save(identity, kind="SIGNAL", symbol=chain.plan.symbol,
                    lineage=signal["lineage"], expected_revision=signal["revision"],
                    payload={**signal["payload"], "confirmed_at": later.minute_target.isoformat()})
                work.commit()
        else:
            chain.now += timedelta(seconds=1)
            corrected = [value.model_copy(update={"received_at": chain.now})
                         for value in inputs.minute_prefix]
            corrected[1] = corrected[1].model_copy(update={"close_fen": 3969})
            with chain.plans._unit_of_work() as work:
                # Valid source correction with unchanged aggregate and head.
                work.history.upsert_minutes(tuple(corrected))
                work.commit()
        assert not _check(chain, identity)


def test_equivalent_later_receipts_and_later_head_do_not_replace_original_bucket(tmp_path):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        inputs = minute_inputs(chain)
        chain.now += timedelta(seconds=1)
        with chain.plans._unit_of_work() as work:
            work.history.upsert_minutes(tuple(value.model_copy(update={"received_at": chain.now})
                for value in inputs.minute_prefix))
            work.commit()
        assert _check(chain, identity)
        chain.now += timedelta(minutes=5)
        # Actual runtime advances its evaluation head. Its missing new facts
        # cannot invalidate the recorded 09:35 observation or supply new ones.
        chain.runtime.run_inputs(plan=chain.plan, inputs=_minute_at_current_clock(chain, inputs))
        assert _check(chain, identity)


@pytest.mark.parametrize("damage", ["missing-minute", "missing-aggregate", "foreign-symbol",
    "wrong-formula", "aggregate-correction", "malformed-amount", "future-receipt"])
def test_actual_local_sources_are_required_and_not_recovered_from_head(tmp_path, damage):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        inputs = minute_inputs(chain)
        with chain.plans._unit_of_work() as work:
            session = work.daily.session
            minute = MinuteRow.bar_end == inputs.minute_prefix[1].bar_end.isoformat()
            if damage == "missing-minute":
                session.execute(delete(MinuteRow).where(minute))
            elif damage == "missing-aggregate":
                session.execute(delete(FiveMinuteRow))
            elif damage == "foreign-symbol":
                session.execute(update(MinuteRow).values(symbol="600000.SH"))
                session.execute(update(FiveMinuteRow).values(symbol="600000.SH"))
            elif damage == "wrong-formula":
                session.execute(update(FiveMinuteRow).values(formula_version="other-v1"))
            elif damage == "aggregate-correction":
                session.execute(update(FiveMinuteRow).values(volume_shares=1))
            elif damage == "malformed-amount":
                # Deliberate stored corruption; not accepted market admission.
                session.execute(update(MinuteRow).where(minute).values(amount_yuan="NaN"))
            else:
                session.execute(update(MinuteRow).where(minute).values(
                    received_at=(chain.now + timedelta(seconds=1)).isoformat()))
            work.commit()
        assert not _check(chain, identity)
        with chain.plans._unit_of_work() as work:
            if damage == "missing-minute":
                assert len(work.daily.session.scalars(select(MinuteRow)).all()) == 4
            elif damage == "missing-aggregate":
                assert work.daily.session.scalar(select(FiveMinuteRow)) is None


@pytest.mark.parametrize("field,value", [
    ("plan_version_id", "another-version"), ("review_id", "another-review"),
    ("rule_id", "sell-other"), ("side", "SELL"), ("lineage", "another-lineage"),
    ("confirmed_at", "2026-09-22T09:36:00+08:00"),
])
def test_actual_signal_native_metadata_cannot_be_replaced_by_equal_fact_evidence(
        tmp_path, field, value):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work:
            row = work.daily.get(identity)
            # Typed engineering counterexamples, not newly approved signals.
            work.daily.save(identity, kind="SIGNAL", symbol=chain.plan.symbol,
                lineage=row["lineage"], expected_revision=row["revision"],
                payload={**row["payload"], field: value})
            work.commit()
        assert not _check(chain, identity)


def test_supplied_signal_projection_cannot_outrun_actual_sql_confirmation(tmp_path):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            work.daily.lock_symbol(chain.plan.symbol)
            supplied = work.daily.get(identity)["payload"]
            supplied["confirmed_at"] = "2026-09-22T09:40:00+08:00"
            assert not signal_fact_evidence_satisfied(work, chain.plan, supplied)


@pytest.mark.parametrize("damage", ["missing", "foreign-symbol", "projected-version"])
def test_signal_identity_comes_from_actual_sql_not_only_supplied_payload(tmp_path, damage):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work:
            signal = work.daily.get(identity)["payload"]
            if damage == "missing":
                work.daily.session.execute(delete(DailyRecord).where(DailyRecord.id == identity))
            elif damage == "foreign-symbol":
                work.daily.session.execute(update(DailyRecord).where(
                    DailyRecord.id == identity).values(symbol="600000.SH"))
            else:
                signal["plan_version_id"] = "another-version"
            work.commit()
        with chain.plans._unit_of_work() as work:
            work.daily.lock_symbol(chain.plan.symbol)
            assert not signal_fact_evidence_satisfied(work, chain.plan, signal)


@pytest.mark.parametrize("model", [MinuteRow, FiveMinuteRow])
@pytest.mark.parametrize("pending", ["dirty", "delete", "new", "moved-key"])
def test_related_pending_market_owners_reject_without_flush_or_discard(tmp_path, model, pending):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            session = work.daily.session
            work.daily.lock_symbol(chain.plan.symbol)
            signal = work.daily.get(identity)["payload"]
            row = session.scalar(select(model).order_by(model.bar_end))
            if pending == "new":
                fields = {column.name: getattr(row, column.name)
                          for column in model.__table__.columns}
                session.expunge(row)
                row = model(**fields)
                session.add(row)  # Duplicate actual key, deliberately left unflushed.
            elif pending == "delete":
                session.delete(row)
            elif pending == "moved-key":
                row.symbol = "600000.SH"
            else:
                row.volume_shares += 1
            before = (tuple(session.new), tuple(session.dirty), tuple(session.deleted))
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                signal_fact_evidence_satisfied(work, chain.plan, signal)
            assert (tuple(session.new), tuple(session.dirty), tuple(session.deleted)) == before


@pytest.mark.parametrize("model", [MinuteRow, FiveMinuteRow])
def test_fresh_sql_source_correction_is_seen_despite_clean_stale_identity_map(tmp_path, model):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            session = work.daily.session
            work.daily.lock_symbol(chain.plan.symbol)
            signal = work.daily.get(identity)["payload"]
            cached = session.scalar(select(model).order_by(model.bar_end))
            old = cached.volume_shares
            # Simulate SQL already differing from a clean session cache. Core
            # table update intentionally does not synchronize that ORM object.
            session.execute(update(model.__table__).values(volume_shares=old + 1))
            assert cached.volume_shares == old and cached not in session.dirty
            assert not signal_fact_evidence_satisfied(work, chain.plan, signal)
            assert cached.volume_shares == old and cached not in session.dirty


@pytest.mark.parametrize("missing", [False, True])
def test_recheck_does_only_selects_after_writer_fence_and_never_flushes_or_acquires(
        tmp_path, monkeypatch, missing):
    def forbidden(*args, **kwargs):
        pytest.fail("read recheck attempted network or flush")

    with _current(tmp_path) as chain:
        identity = _ready(chain)
        if missing:
            with chain.plans._unit_of_work() as work:
                work.daily.session.execute(delete(MinuteRow))
                work.commit()
        with chain.plans._unit_of_work() as work, work.daily.session.no_autoflush:
            session = work.daily.session
            work.daily.lock_symbol(chain.plan.symbol)  # Existing lock DML precedes capture.
            signal = work.daily.get(identity)["payload"]
            models = (DailyRecord, AuditLog, MinuteRow, FiveMinuteRow)

            def snapshot():
                return tuple(tuple(tuple(row) for row in session.execute(
                    select(model.__table__).order_by(*model.__table__.primary_key.columns)))
                    for model in models)

            before = snapshot()
            statements = []

            def capture(conn, cursor, statement, parameters, context, many):
                statements.append(statement.lstrip().split()[0].upper())

            connection = session.connection()
            event.listen(connection, "before_cursor_execute", capture)
            event.listen(session, "before_flush", forbidden)
            try:
                with monkeypatch.context() as no_network:
                    no_network.setattr("socket.create_connection", forbidden)
                    no_network.setattr("socket.socket", forbidden)
                    assert signal_fact_evidence_satisfied(work, chain.plan, signal) is not missing
                assert snapshot() == before
                assert statements and set(statements) == {"SELECT"}
            finally:
                event.remove(connection, "before_cursor_execute", capture)
                event.remove(session, "before_flush", forbidden)


def test_missing_manual_observation_source_preserves_decisive_numeric_any(tmp_path):
    with _variant(tmp_path, operator="ANY", numeric=True) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work:
            work.daily.session.execute(delete(MinuteRow))
            work.daily.session.execute(delete(FiveMinuteRow))
            work.commit()
        assert _check(chain, identity)


@pytest.mark.parametrize("owner", ["minute", "aggregate", "signal", "fact", "unrelated"])
def test_wrapper_protects_real_callers_without_an_outer_no_autoflush(tmp_path, owner):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        with chain.plans._unit_of_work() as work:
            session = work.daily.session
            work.daily.lock_symbol(chain.plan.symbol)
            signal = work.daily.get(identity)["payload"]
            if owner in {"minute", "aggregate", "unrelated"}:
                model = FiveMinuteRow if owner == "aggregate" else MinuteRow
                row = session.scalar(select(model).order_by(model.bar_end))
                if owner == "unrelated":
                    fields = {column.name: getattr(row, column.name)
                              for column in model.__table__.columns}
                    fields["symbol"] = "600000.SH"
                    row = model(**fields)
                    session.add(row)
                else:
                    row.volume_shares += 1
            else:
                key = (identity if owner == "signal"
                       else signal["evidence"][0]["children"][0]["fact_ids"][0])
                row = session.get(DailyRecord, key)
                row.revision += 1

            def forbidden(*args, **kwargs):
                pytest.fail("wrapper flushed a pending owner without outer no_autoflush")

            before = (tuple(session.new), tuple(session.dirty), tuple(session.deleted))
            event.listen(session, "before_flush", forbidden)
            try:
                if owner == "unrelated":
                    assert signal_fact_evidence_satisfied(work, chain.plan, signal)
                else:
                    with pytest.raises(SourceCoverageAuthorityError,
                                       match="SOURCE_COVERAGE_INTEGRITY"):
                        signal_fact_evidence_satisfied(work, chain.plan, signal)
                assert (tuple(session.new), tuple(session.dirty), tuple(session.deleted)) == before
            finally:
                event.remove(session, "before_flush", forbidden)


@pytest.mark.parametrize("borrow_sibling", [False, True])
def test_equal_content_actual_active_sibling_cannot_supply_original_recorded_owner(
        tmp_path, borrow_sibling):
    with _current(tmp_path) as chain:
        identity = _ready(chain)
        original_id = chain.version["id"]
        content = chain.version["contentHash"]
        chain.activate(version=2, activation_revision=1, supplement_revision=1)
        assert chain.version["id"] != original_id and chain.version["contentHash"] == content
        with chain.plans._unit_of_work() as work:
            sibling = work.plans.get_version_details(chain.version["id"])
            assert sibling.review_id is not None
            row = work.daily.get(identity)
            if borrow_sibling:
                work.daily.save(identity, kind="SIGNAL", symbol=chain.plan.symbol,
                    lineage=row["lineage"], expected_revision=row["revision"],
                    payload={**row["payload"], "plan_version_id": sibling.id,
                             "review_id": sibling.review_id})
                work.commit()
        # This helper rechecks attribution only. The existing live action gate
        # still owns whether a superseded original can perform any action.
        assert _check(chain, identity) is not borrow_sibling
