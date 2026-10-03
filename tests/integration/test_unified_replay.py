"""Isolated frozen research calls the current runtime and preserves independent expectations."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from tests.integration.test_backtest_runner import (
    SHANGHAI,
    SYMBOL,
    _execution_config,
    _seed_dataset,
)
from tests.unit.test_unified_plan_domain import unified_payload
from tests.unit.test_unified_replay_input import research_input, research_plan

from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchDeactivate,
    ResearchFact,
    ResearchFactor,
    ResearchReassessment,
    ResearchReplace,
    ResearchReview,
    ResearchSimulation,
)
from trade_plan_monitor.backtest.run_input import BacktestInitialLotInput
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.state.daily_state_models import DailyOfficialProof


def fixture(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite")
    dataset_hash = _seed_dataset(store)
    plan = research_plan()
    raw = plan.model_dump(mode="python")
    raw["symbol"] = SYMBOL
    raw["ordinary_rules"] = (
        plan.ordinary_rules[0].model_copy(
            update={
                "condition": {
                    "type": "MINUTE_CLOSE_BELOW",
                    "timeframe_minutes": 5,
                    "price_fen": 6500,
                }
            }
        ),
    )
    plan = type(plan).model_validate(raw)
    frozen = research_input(plan).model_copy(
        update={"started_at": datetime(2026, 8, 24, 9, 0, tzinfo=SHANGHAI)}
    )
    return store, dataset_hash, plan, frozen


def run(store, dataset_hash, plan, frozen, **kwargs):
    return OfflineBacktestRunner(store).run(
        plan=plan,
        dataset_hash=dataset_hash,
        initial_cash_fen=1_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
        **kwargs,
    )


def test_minute_research_current_runtime_without_activation_or_inventory_changes(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    report = run(store, dataset_hash, plan, frozen)
    assert report.schema_version == "backtest-report-v3"
    assert len(report.current_events) >= 48
    first = next(e for e in report.current_events if e.signals)
    assert first.at == datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI)
    signal = first.signals[0]
    assert signal.planned_qty == signal.executable_qty == 100
    assert signal.confirmation_kind == "COMPLETED_BAR_CLOSE"
    assert signal.execution_window == "CURRENT_SESSION"
    assert signal.confirmed_at == datetime(2026, 8, 24, 9, 35, tzinfo=SHANGHAI)
    assert first.inventory_before.total_qty == first.inventory_after.total_qty == 0
    assert report.final_inventory.total_qty == 0
    assert report.operations == ()
    repeated = run(store, dataset_hash, plan, frozen)
    assert repeated.model_dump_json() == report.model_dump_json()


def test_daily_requires_frozen_proof_and_next_session_calendar(tmp_path):
    store, dataset_hash, minute_plan, frozen = fixture(tmp_path)
    raw = unified_payload()
    raw.update(symbol=SYMBOL, risk_branches=[])
    raw["ordinary_rules"][0].update(
        zone=None,
        validity={"mode": "PLAN_ACTIVE"},
        condition={
            "type": "DAILY_PRICE_COMPARE",
            "field": "close",
            "offset": 0,
            "comparator": "LT",
            "reference": {
                "mode": "FIXED",
                "value": "6500",
                "unit": "FEN",
                "as_of": "2026-08-20",
                "source": "Synthetic research threshold",
            },
        },
    )
    plan = type(minute_plan).model_validate(raw)
    frozen = research_input(plan).model_copy(update={"started_at": frozen.started_at})
    missing = run(store, dataset_hash, plan, frozen)
    assert not any(event.signals for event in missing.current_events)
    assert "PRICE_BASIS_UNVERIFIED" in missing.current_events[-1].blockers
    with store.open_frozen_dataset(dataset_hash) as reader:
        dates = tuple(day.trade_date for day in reader if day.daily_bar is not None)
    proof = ResearchAdjustmentProof(
        proof_id="explicit-adjustment-proof",
        dataset_hash=dataset_hash,
        symbol=SYMBOL,
        provider="TUSHARE",
        adjustment_as_of=date(2026, 8, 24),
        available_at=datetime(2026, 8, 24, 15, 20, tzinfo=SHANGHAI),
        received_at=datetime(2026, 8, 24, 15, 20, tzinfo=SHANGHAI),
        quote_basis_factor=Decimal("1"),
        factors=tuple(ResearchFactor(trade_date=day, factor=Decimal("1")) for day in dates),
        evidence="Synthetic explicitly verified constant-factor proof; never an inferred default",
    )
    frozen = frozen.model_copy(
        update={
            "adjustment_proofs": (proof,),
            "calendar_extension": (
                TradingDay(
                    exchange="SSE",
                    cal_date=date(2026, 8, 25),
                    is_open=True,
                    previous_trade_date=date(2026, 8, 24),
                ),
            ),
        }
    )
    report = run(store, dataset_hash, plan, frozen)
    confirmed = next(event for event in report.current_events if event.signals)
    assert confirmed.at == proof.received_at
    assert confirmed.signals[0].execution_date == date(2026, 8, 25)
    assert confirmed.signals[0].execution_window == "NEXT_EXCHANGE_SESSION_ONLY"
    assert not any(event.signals for event in report.current_events if event.at < proof.received_at)


def test_scoped_negative_then_positive_fact_and_future_mutation_preserve_prior_events(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    rule = plan.ordinary_rules[0]
    rule = rule.model_copy(
        update={
            "condition": {
                "type": "ALL",
                "conditions": [
                    rule.condition.model_dump(mode="json"),
                    {
                        "type": "REVIEWED_FACT",
                        "fact_kind": "TECHNICAL",
                        "evidence_requirement": "Human verified the completed technical pattern",
                        "validity_scope": "TRADE_DATE",
                    },
                ],
            }
        }
    )
    plan = plan.model_copy(update={"ordinary_rules": (rule,)})
    frozen = research_input(plan).model_copy(update={"started_at": frozen.started_at})
    negative = ResearchFact(
        kind="FACT",
        operation_id="negative",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        fact_id="scoped-technical",
        fact_kind="TECHNICAL",
        trade_date=date(2026, 8, 24),
        satisfied=False,
        evidence="Synthetic technical review says completed structure is absent",
    )
    positive = negative.model_copy(
        update={
            "operation_id": "positive",
            "satisfied": True,
            "at": datetime(2026, 8, 24, 9, 40, 12, tzinfo=SHANGHAI),
        }
    )
    old = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (negative,)}))
    new = run(
        store, dataset_hash, plan, frozen.model_copy(update={"operations": (negative, positive)})
    )
    assert old.operations[0].status == new.operations[0].status == "APPLIED"
    assert not any(event.signals for event in old.current_events)
    assert next(event for event in new.current_events if event.signals).at == positive.at
    assert [event.model_dump() for event in old.current_events if event.at < positive.at] == [
        event.model_dump() for event in new.current_events if event.at < positive.at
    ]


def test_deactivation_and_replacement_end_original_signal_authority(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    stop = ResearchDeactivate(
        kind="DEACTIVATE",
        operation_id="stop",
        order=0,
        at=datetime(2026, 8, 24, 9, 40, 12, tzinfo=SHANGHAI),
    )
    report = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (stop,)}))
    assert report.operations[0].status == "APPLIED"
    assert all(
        not signal.executable_qty and signal.state == "INVALIDATED"
        for event in report.current_events
        if event.at >= stop.at
        for signal in event.signals
    )
    replacement = ResearchReplace(
        kind="REPLACE",
        operation_id="replace",
        order=0,
        at=stop.at,
        replacement_plan_hash="1" * 64,
        replacement_version_id="reviewed-replacement-2",
        replacement_review=ResearchReview(
            content_hash="2" * 64,
            confirmed=True,
            reviewed_at=datetime(2026, 10, 3, 14, tzinfo=SHANGHAI),
            evidence="Synthetic explicit reviewed successor identity for research termination",
        ),
    )
    changed = run(
        store, dataset_hash, plan, frozen.model_copy(update={"operations": (replacement,)})
    )
    assert changed.operations[0].status == "APPLIED"
    assert all(
        not signal.executable_qty
        for event in changed.current_events
        if event.at >= stop.at
        for signal in event.signals
    )


def test_explicit_simulation_consumes_complete_occurrence_once_and_stop_blocks(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    simulation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="buy-one",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        rule_id=plan.ordinary_rules[0].rule_id,
        occurrence=1,
        quantity=100,
    )
    duplicate = simulation.model_copy(
        update={
            "operation_id": "buy-again",
            "at": datetime(2026, 8, 24, 9, 40, 12, tzinfo=SHANGHAI),
        }
    )
    report = run(
        store, dataset_hash, plan, frozen.model_copy(update={"operations": (simulation, duplicate)})
    )
    assert report.operations[0].status == "APPLIED"
    assert report.operations[0].inventory_after.total_qty == 100
    assert report.operations[1].status == "BLOCKED"
    assert report.final_inventory.total_qty == 100
    stop = ResearchDeactivate(
        kind="DEACTIVATE",
        operation_id="stop",
        order=0,
        at=datetime(2026, 8, 24, 9, 36, tzinfo=SHANGHAI),
    )
    blocked = run(
        store, dataset_hash, plan, frozen.model_copy(update={"operations": (stop, duplicate)})
    )
    assert blocked.operations[1].status == "BLOCKED"
    assert "ORDINARY_AUTHORITY_ENDED" in blocked.operations[1].blockers
    assert blocked.final_inventory.total_qty == 0


@pytest.mark.parametrize(
    "side,bucket,acquired,initial,requested,known,expected",
    [
        ("SELL", "TACTICAL", date(2026, 8, 24), 100, 100, True, "BLOCKED"),
        ("SELL", "TACTICAL", date(2026, 8, 21), 100, 100, True, "APPLIED"),
        ("SELL", "CORE", date(2026, 8, 21), 100, 100, True, "BLOCKED"),
        ("BUY", "TACTICAL", date(2026, 8, 21), 1000, 100, True, "BLOCKED"),
        ("BUY", "TACTICAL", date(2026, 8, 21), 0, 200, True, "BLOCKED"),
        ("BUY", "TACTICAL", date(2026, 8, 21), 0, 100, False, "BLOCKED"),
    ],
)
def test_full_simulation_reuses_t1_core_capacity_unknown_and_quantity_guards(
    tmp_path,
    side,
    bucket,
    acquired,
    initial,
    requested,
    known,
    expected,
):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    rule = plan.ordinary_rules[0].model_copy(update={"side": side})
    plan = plan.model_copy(update={"ordinary_rules": (rule,)})
    frozen = research_input(plan, known=known).model_copy(update={"started_at": frozen.started_at})
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="explicit-whole",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        rule_id=rule.rule_id,
        occurrence=1,
        quantity=requested,
    )
    lots = (
        ()
        if not initial
        else (
            BacktestInitialLotInput(
                lot_key="historical-inventory",
                bucket=bucket,
                acquired_trade_date=acquired,
                quantity=initial,
                cost_basis_fen=initial * 6400,
            ),
        )
    )
    report = run(
        store,
        dataset_hash,
        plan,
        frozen.model_copy(update={"operations": (operation,)}),
        initial_lots=lots,
    )
    assert report.operations[0].status == expected
    if expected == "APPLIED":
        assert report.operations[0].quantity == 100
        assert report.final_inventory.total_qty == 0
    elif known:
        assert report.final_inventory.total_qty == initial
    else:
        assert report.final_inventory.total_qty is None
        assert "UNKNOWN_INVENTORY" in report.limitations


def test_future_official_fact_proof_is_rejected_by_shared_online_participant(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    proof = DailyOfficialProof(
        issuer="Synthetic exchange proof",
        document_title="Synthetic report",
        document_url="https://example.test/synthetic",
        published_at=frozen.started_at,
        verified_at=datetime(2026, 8, 24, 10, tzinfo=SHANGHAI),
        applicable_assertion="Synthetic exact technical tradability assertion for research only",
    )
    operation = ResearchFact(
        kind="FACT",
        operation_id="future-official",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        fact_id="future-proof",
        fact_kind="TRADABILITY",
        trade_date=date(2026, 8, 24),
        satisfied=True,
        evidence="Synthetic technical tradability evidence for this research session",
        official_evidence=proof,
    )
    report = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (operation,)}))
    assert report.operations[0].status == "BLOCKED"
    assert report.operations[0].blockers == ("RESEARCH_FACT_OFFICIAL_PROOF_UNAVAILABLE",)


def test_latched_severe_risk_survives_stop_then_explicit_reassessment_consumes_cause(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    raw = unified_payload()
    severe = raw["risk_branches"][1]
    severe["condition"] = {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 6500}
    plan = plan.model_copy(update={"risk_branches": (severe,)})
    with store.open_frozen_dataset(dataset_hash) as reader:
        dates = tuple(day.trade_date for day in reader if day.daily_bar is not None)
    proof = ResearchAdjustmentProof(
        proof_id="reviewed-factor-proof",
        dataset_hash=dataset_hash,
        symbol=SYMBOL,
        provider="TUSHARE",
        adjustment_as_of=date(2026, 8, 24),
        available_at=datetime(2026, 8, 24, 15, 20, tzinfo=SHANGHAI),
        received_at=datetime(2026, 8, 24, 15, 20, tzinfo=SHANGHAI),
        quote_basis_factor=Decimal("1"),
        factors=tuple(ResearchFactor(trade_date=day, factor=Decimal("1")) for day in dates),
        evidence="Synthetic explicit verified factor proof for latched-risk research",
    )
    stop = ResearchDeactivate(
        kind="DEACTIVATE",
        operation_id="stop-risk",
        order=0,
        at=datetime(2026, 8, 24, 15, 30, tzinfo=SHANGHAI),
    )
    reassess = ResearchReassessment(
        kind="REASSESS",
        operation_id="remove-risk",
        order=0,
        at=datetime(2026, 8, 24, 16, tzinfo=SHANGHAI),
        risk_kind="SEVERE_TECHNICAL",
        removal_evidence="Synthetic explicit technical scope reassessment of the consumed close",
    )
    observe = ResearchFact(
        kind="FACT",
        operation_id="after-removal",
        order=0,
        at=reassess.at.replace(minute=1),
        fact_id="negative-after-removal",
        fact_kind="TECHNICAL",
        trade_date=reassess.at.date(),
        satisfied=False,
        evidence="Synthetic later negative observation must not replay the consumed risk evidence",
    )
    frozen = research_input(plan).model_copy(
        update={
            "started_at": frozen.started_at,
            "adjustment_proofs": (proof,),
            "operations": (stop, reassess, observe),
            "calendar_extension": (
                TradingDay(
                    exchange="SSE",
                    cal_date=date(2026, 8, 25),
                    is_open=True,
                    previous_trade_date=date(2026, 8, 24),
                ),
            ),
        }
    )
    lot = BacktestInitialLotInput(
        lot_key="settled-tactical",
        bucket="TACTICAL",
        acquired_trade_date=date(2026, 8, 21),
        quantity=100,
        cost_basis_fen=640000,
    )
    report = run(store, dataset_hash, plan, frozen, initial_lots=(lot,))
    stopped = next(event for event in report.current_events if event.at == stop.at)
    assert stopped.risks[0].status == "CONFIRMED"
    assert stopped.risks[0].earliest_execution_date == date(2026, 8, 25)
    assert report.operations[-1].status == "APPLIED"
    final = report.current_events[-1].resulting_risks[0]
    assert final.status == "CLEAR"
    assert final.reassessment_id
    assert final.consumed_evidence_ids
    assert report.final_inventory.total_qty == 100


def test_suspension_fact_is_visibly_unsupported_instead_of_silently_applied(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    operation = ResearchFact(
        kind="FACT",
        operation_id="suspension",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        fact_id="suspension",
        fact_kind="FULL_SESSION_SUSPENSION",
        trade_date=date(2026, 8, 24),
        satisfied=True,
        evidence="Synthetic suspension cannot override frozen traded minutes",
    )
    report = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (operation,)}))
    assert report.operations[0].status == "BLOCKED"
    assert report.operations[0].blockers == ("RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED",)
    assert "RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED" in report.limitations


def test_current_report_persists_reopens_and_exports_typed_evidence(tmp_path):
    import json

    from trade_plan_monitor.backtest.reporting import iter_export_summary, persist_report
    from trade_plan_monitor.backtest.results import BacktestDetailKind, BacktestResultStore
    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    store, dataset_hash, plan, frozen = fixture(tmp_path)
    report = run(store, dataset_hash, plan, frozen)
    run_input = BacktestRunInput.create(
        plan=plan,
        manifest=store.dataset_manifest(dataset_hash),
        initial_cash_fen=1_000_000,
        initial_lots=(),
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
    )
    results = BacktestResultStore(tmp_path / "results.sqlite")
    assert persist_report(results, report, run_input=run_input).summary_created
    reopened = BacktestResultStore(tmp_path / "results.sqlite")
    summary = reopened.get_verified_run(report.run_id)
    assert summary.formula_versions["report"] == "backtest-report-v3"
    assert summary.coverage["decisionCount"] == len(report.current_events)
    records = reopened.list_details(report.run_id, kind=BacktestDetailKind.DECISION)
    assert records[0].payload["schema_version"] == "unified-research-decision-v1"
    export = b"".join(iter_export_summary(reopened, report.run_id, lambda: False))
    assert json.loads(export)["schemaVersion"] == "backtest-report-summary-v4"
    assert b"".join(iter_export_summary(reopened, report.run_id, lambda: False)) == export


def test_research_cash_never_resizes_monitor_receipt_and_csv_is_reproducible(tmp_path):
    from trade_plan_monitor.backtest.reporting import iter_export_fills, persist_report
    from trade_plan_monitor.backtest.results import BacktestResultStore
    from trade_plan_monitor.backtest.run_input import BacktestRunInput

    store, dataset_hash, plan, frozen = fixture(tmp_path)
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="full-buy",
        order=0,
        at=datetime(2026, 8, 24, 9, 35, 12, tzinfo=SHANGHAI),
        rule_id=plan.ordinary_rules[0].rule_id,
        occurrence=1,
        quantity=100,
    )
    frozen = frozen.model_copy(update={"operations": (operation,)})
    report = OfflineBacktestRunner(store).run(
        plan=plan,
        dataset_hash=dataset_hash,
        initial_cash_fen=100,
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
    )
    assert report.operations[0].status == "APPLIED"
    assert report.operations[0].quantity == report.final_inventory.total_qty == 100
    assert report.operations[0].valuation.blockers == ("INSUFFICIENT_RESEARCH_CASH",)
    assert report.metrics.total_return is None
    assert report.daily_equity[-1].equity_fen is None
    run_input = BacktestRunInput.create(
        plan=plan,
        manifest=store.dataset_manifest(dataset_hash),
        initial_cash_fen=100,
        initial_lots=(),
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
    )
    results = BacktestResultStore(tmp_path / "results.sqlite")
    persist_report(results, report, run_input=run_input)
    csv = b"".join(iter_export_fills(results, report.run_id, lambda: False))
    assert b"INSUFFICIENT_RESEARCH_CASH" in csv
    assert b"explicit-simulation-valuation-v1" in csv
    assert b"".join(iter_export_fills(results, report.run_id, lambda: False)) == csv
