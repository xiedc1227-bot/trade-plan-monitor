"""Fresh ordinary simulations recheck real source authority inside their writer."""

from datetime import datetime

import pytest
from sqlalchemy import text
from tests.integration.test_daily_plan_chain import (
    FRIDAY,
    SH,
    TUESDAY,
    WEDNESDAY,
    Chain,
)
from tests.integration.test_daily_simulation import command

from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


@pytest.fixture(params=("BUY", "SELL"))
def current(tmp_path, request):
    chain = Chain(tmp_path)
    raw = chain.plan.model_dump(mode="json")
    raw["ordinary_rules"][0].update(side=request.param,
        zone="LOW_BUY" if request.param == "BUY" else None)
    chain.plan = type(chain.plan).model_validate(raw)
    with chain.client:
        chain.activate()
        with chain.plans._unit_of_work() as work:
            for previous, day in ((FRIDAY, TUESDAY), (TUESDAY, WEDNESDAY)):
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=True, previous_trade_date=previous))
            work.commit()
        series = chain.series()
        chain.evaluate(series=series, official=FRIDAY)
        chain.facts()
        chain.evaluate(series=series, official=FRIDAY)
        chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
        chain.post("simulation-position-confirmations", dict(symbol=chain.plan.symbol,
            coreQty=100, tacticalQty=100 if request.param == "SELL" else 0,
            expectedRevision=0))
        ready = chain.evaluate(series=series, price=3970)
        signal, = ready.snapshot["signals"]
        assert signal["side"] == request.param and signal["executable_qty"] == 100
        yield chain, signal


def _business(chain):
    with chain.plans._unit_of_work() as work:
        return {table: tuple(work.daily.session.execute(text(
            f"SELECT * FROM {table} ORDER BY id")).all())
            for table in ("daily_plan_record", "audit_log")}


def _stale(chain):
    with chain.plans._unit_of_work() as work:
        store = SourceCoverageStore(work.daily.session)
        old = store.latest(chain.version["id"])
        store.append(chain.version["id"], old.assessment, inputs=old.inputs,
            expected_revision=old.revision, command_id="new-independent-source-assessment",
            now=chain.now)
        work.commit()


def test_new_bundle_without_its_exact_review_blocks_fresh_ordinary_simulation(current):
    chain, signal = current
    payload = command(chain, signal)
    _stale(chain)
    before = _business(chain)
    response = chain.post("simulated-trades", payload, key="source-stale", status=409)
    assert response["error"]["code"] == "CONFLICT"
    assert "SOURCE_COVERAGE_STALE" in {row["code"] for row in response["error"]["details"]}
    assert _business(chain) == before


def test_completed_simulation_replay_keeps_its_original_receipt_after_reassessment(current):
    chain, signal = current
    payload = command(chain, signal)
    receipt = chain.post("simulated-trades", payload, key="completed-before-reassessment")
    _stale(chain)
    before = _business(chain)
    assert chain.post("simulated-trades", payload,
                      key="completed-before-reassessment") == receipt
    assert _business(chain) == before


def test_current_source_proof_does_not_resize_the_offered_ordinary_quantity(current):
    chain, signal = current
    payload = command(chain, signal, quantity=200)
    before = _business(chain)
    chain.post("simulated-trades", payload, key="whole-offered-quantity", status=422)
    assert _business(chain) == before


def test_current_source_check_runs_under_the_actual_existing_writer(current, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from trade_plan_monitor.state import source_action_authority

    chain, signal = current
    original = source_action_authority.require_source_action_authority
    observed = []

    def guarded(work, version_id, **kwargs):
        basis = original(work, version_id, **kwargs)
        with chain.plans._session_factory() as other:
            other.execute(text("PRAGMA busy_timeout=0"))
            store = SourceCoverageStore(other)
            old = store.latest(version_id)
            with pytest.raises(OperationalError, match="locked"):
                store.append(version_id, old.assessment, inputs=old.inputs,
                    expected_revision=old.revision, command_id="concurrent-reassessment",
                    now=chain.now)
            other.rollback()
        observed.append(basis.basis)
        return basis

    monkeypatch.setattr(source_action_authority, "require_source_action_authority", guarded)
    result = chain.post("simulated-trades", command(chain, signal), key="held-source-writer")
    assert result["quantity"] == 100 and observed == ["CURRENT"]
    with chain.plans._unit_of_work() as work:
        assert SourceCoverageStore(work.daily.session).latest(chain.version["id"]).revision == 1


def test_late_accounting_failure_rolls_back_even_after_current_source_passes(current, monkeypatch):
    from trade_plan_monitor.state.daily_accounting import DailyAccounting

    chain, signal = current
    payload = command(chain, signal)
    before = _business(chain)
    original = DailyAccounting.simulate

    def fail_after_write(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError("synthetic failure after staged accounting")

    monkeypatch.setattr(DailyAccounting, "simulate", fail_after_write)
    with pytest.raises(RuntimeError, match="after staged accounting"):
        chain.post("simulated-trades", payload, key="rollback-after-source-pass")
    assert _business(chain) == before


def test_corrupt_stored_source_evidence_is_a_sanitized_server_error(current, monkeypatch):
    from sqlalchemy import update

    from trade_plan_monitor.state.source_coverage_models import (
        COVERAGE_TRIGGER_SQL,
        CoverageAssessmentRow,
    )

    chain, signal = current
    payload = command(chain, signal)
    trigger = "pma_seal_source_coverage_assessment_update"
    with chain.plans._unit_of_work() as work:
        work.daily.session.execute(text(f"DROP TRIGGER {trigger}"))
        row = work.daily.session.query(CoverageAssessmentRow).filter_by(
            plan_version_id=chain.version["id"], revision=1).one()
        work.daily.session.execute(update(CoverageAssessmentRow).where(
            CoverageAssessmentRow.plan_version_id == chain.version["id"]
        ).values(payload_json=row.payload_json + " "))
        work.daily.session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        work.commit()
    before = _business(chain)
    monkeypatch.setattr(chain.client._transport, "raise_server_exceptions", False)
    response = chain.client.post("/api/v1/simulated-trades", json=payload,
                                 headers={"Idempotency-Key": "stored-source-corruption"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "coverage_assessment" not in response.text
    assert _business(chain) == before
