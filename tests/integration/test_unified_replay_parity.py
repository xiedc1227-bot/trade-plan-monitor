"""An independent public monitor ledger is an oracle for every replay event."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_unified_replay import fixture, run

from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFactor,
    ResearchSimulation,
)
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, admit_qfq_daily
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.state.daily_state_models import DailyRiskState, DailySignalState
from trade_plan_monitor.web.routers.daily_plans import DailyInventoryApiView


def _semantic_signals(values):
    # Public mutation also schedules a same-instant reevaluation. Storage revision
    # counts differ; semantic evidence, quantities, state and blockers must agree.
    excluded = {"signal_id", "plan_version_id", "review_id", "lineage", "revision"}
    return [
        DailySignalState.model_validate(value).model_dump(mode="json", exclude=excluded)
        for value in values
    ]


@pytest.mark.parametrize("mixed_risk", [False, True])
def test_each_event_matches_independent_current_monitor_and_public_simulation(tmp_path, mixed_risk):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    if mixed_risk:
        from tests.unit.test_unified_plan_domain import unified_payload
        from tests.unit.test_unified_replay_input import research_input

        raw = plan.model_dump(mode="python")
        raw["monitoring"] = unified_payload()["monitoring"]
        daily = dict(raw["ordinary_rules"][0])
        daily.update(
            rule_id="daily-companion",
            side="SELL",
            confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
            execution_window="NEXT_EXCHANGE_SESSION_ONLY",
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
                    "source": "Explicit synthetic comparison",
                },
            },
        )
        raw["ordinary_rules"] = [raw["ordinary_rules"][0], daily]
        severe = unified_payload()["risk_branches"][1]
        severe["condition"] = raw["ordinary_rules"][0]["condition"]
        raw["risk_branches"] = [severe]
        plan = type(plan).model_validate(raw)
        from trade_plan_monitor.market_data.models import TradingDay

        with store.open_frozen_dataset(dataset_hash) as reader:
            dates = [day.trade_date for day in reader if day.daily_bar is not None]
        proofs = []
        for anchor, at in [
            (date(2026, 8, 21), frozen.started_at),
            (date(2026, 8, 24), frozen.started_at.replace(hour=15, minute=20)),
        ]:
            proofs.append(
                ResearchAdjustmentProof(
                    proof_id="proof-" + str(anchor),
                    dataset_hash=dataset_hash,
                    symbol=plan.symbol,
                    provider="TUSHARE",
                    adjustment_as_of=anchor,
                    available_at=at,
                    received_at=at,
                    quote_basis_factor=Decimal("1"),
                    factors=tuple(
                        ResearchFactor(trade_date=day, factor=Decimal("1"))
                        for day in dates
                        if day <= anchor
                    ),
                    evidence="Explicit synthetic verified adjustment factors",
                )
            )
        frozen = research_input(plan).model_copy(
            update={
                "started_at": frozen.started_at,
                "adjustment_proofs": tuple(proofs),
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
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="explicit-buy",
        order=0,
        at=frozen.started_at.replace(hour=9, minute=35, second=12),
        rule_id=plan.ordinary_rules[0].rule_id,
        occurrence=1,
        quantity=100,
    )
    report = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (operation,)}))
    with store.open_frozen_dataset(dataset_hash) as reader:
        days = tuple(reader)
    minutes = [minute for day in days for minute in day.minutes]
    calendar = (*tuple(day.trading_day for day in days), *frozen.calendar_extension)
    chain = Chain(tmp_path / "online-oracle")
    chain.plan = plan
    chain.now = frozen.started_at
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar

        with chain.plans._unit_of_work() as work:
            for day in calendar:
                work.daily.session.add(TradingCalendar(**day.model_dump()))
            work.commit()
        chain.post(
            "simulation-position-confirmations",
            {"symbol": plan.symbol, "coreQty": 0, "tacticalQty": 0, "expectedRevision": 0},
        )
        for event in report.current_events:
            chain.now = event.at
            available = [minute for minute in minutes if minute.received_at <= event.at]
            complete_ends = [
                minute.bar_end
                for minute in available
                if minute.bar_end.date() == event.at.date() and minute.bar_end.minute % 5 == 0
            ]
            target = max(complete_ends, default=None)
            assert event.minute_target == target
            prefix = tuple(
                minute
                for minute in available
                if target is not None
                and minute.bar_end.date() == target.date()
                and minute.bar_end <= target
            )
            completed = []
            for minute in prefix:
                if minute.bar_end.minute % 5:
                    continue
                source = tuple(
                    value
                    for value in prefix
                    if minute.bar_end - timedelta(minutes=5) < value.bar_end <= minute.bar_end
                )
                bar = aggregate_five_minute_bar(source, bucket_end=minute.bar_end, is_open=True)
                if bar is not None:
                    completed.append(bar)
            latest = available[-1] if available else None
            quote = None
            if latest is not None and event.at - latest.bar_end <= timedelta(minutes=5):
                quote = DailyExecutionQuote(
                    symbol=plan.symbol,
                    price_fen=latest.close_fen,
                    quote_at=latest.bar_end,
                    available_at=latest.received_at,
                    evaluated_at=event.at,
                    tradable=True,
                    special_state_verified=True,
                    liquidity_available=True,
                )
            series = None
            visible_proofs = [
                proof for proof in frozen.adjustment_proofs if proof.received_at <= event.at
            ]
            if visible_proofs:
                proof = visible_proofs[-1]
                series = admit_qfq_daily(
                    raw_bars=tuple(
                        day.daily_bar
                        for day in days
                        if day.daily_bar is not None and day.daily_bar.received_at <= event.at
                    ),
                    factors={factor.trade_date: factor.factor for factor in proof.factors},
                    adjustment_as_of=proof.adjustment_as_of,
                    quote_basis_factor=proof.quote_basis_factor,
                    provider=proof.provider,
                    session_dates=tuple(day.cal_date for day in calendar if day.is_open),
                    suspended_dates=(),
                    cutoff=event.at,
                )
            inputs = DailyRuntimeInputs(
                evaluated_at=event.at,
                official_trade_date=None
                if event.official_trade_date is None
                else datetime.fromisoformat(event.official_trade_date).date(),
                series=series,
                session_dates=tuple(day.cal_date for day in calendar if day.is_open),
                suspended_dates=(),
                quote=quote,
                data_blockers=(),
                minute_prefix=prefix,
                five_minute_bars=tuple(completed),
                minute_target=target,
                trading_calendar=calendar,
            )
            with chain.plans._unit_of_work() as work:
                work.history.upsert_minutes(prefix)
                for bar in completed:
                    work.history.upsert_five_minute(**bar.model_dump())
                work.commit()
            actual = chain.runtime.run_inputs(plan=plan, inputs=inputs)
            assert _semantic_signals(actual.snapshot["signals"]) == _semantic_signals(
                [signal.model_dump(mode="python") for signal in event.signals]
            )
            assert actual.snapshot["inventory"] == event.inventory_before.model_dump(mode="json")
            assert actual.snapshot["risk_action"] == event.risk_action.model_dump(
                mode="json", exclude_none=True
            )

            def semantic_risks(values):
                return [
                    DailyRiskState.model_validate(value).model_dump(
                        mode="json",
                        exclude={"risk_id", "revision", "plan_version_id", "review_id", "lineage"},
                    )
                    for value in values
                ]

            assert semantic_risks(actual.snapshot["risks"]) == semantic_risks(
                [risk.model_dump(mode="json") for risk in event.risks]
            )
            if event.at == operation.at:
                signal = actual.snapshot["signals"][0]
                assert signal["planned_qty"] == 100
                assert signal["executable_qty"] == (0 if mixed_risk else 100)
                assert signal["confirmed_at"] == "2026-08-24T09:35:00+08:00"
                assert signal["execution_window"] == "CURRENT_SESSION"
                chain.post(
                    "simulated-trades",
                    {
                        "planVersionId": chain.version["id"],
                        "causeId": signal["signal_id"],
                        "expectedCauseRevision": signal["revision"],
                        "expectedInventoryRevision": actual.snapshot["inventory"]["revision"],
                        "quantity": 100,
                    },
                    status=409 if mixed_risk else 200,
                )
            inventory = chain.client.get(
                "/api/v1/simulation-position-inventory",
                params={"symbol": plan.symbol, "asOfTradeDate": str(event.at.date())},
            ).json()["snapshot"]
            assert DailyInventoryApiView.model_validate(inventory).model_dump(
                mode="json", by_alias=False
            ) == event.inventory_after.model_dump(mode="json")
            if not mixed_risk and event.at == operation.at.replace(minute=40):
                # Saving a successor draft must not end the original runtime authority.
                chain.activate(
                    version=2, activation_revision=1, supplement_revision=1, review=False
                )
                with chain.plans._unit_of_work() as work:
                    assert work.plans.get_active(plan.symbol).plan_version_id != chain.version["id"]
        assert report.final_inventory.total_qty == (0 if mixed_risk else 100)
        assert report.operations[0].inventory_before.total_qty == 0
        assert report.operations[0].inventory_after.total_qty == (0 if mixed_risk else 100)
        assert report.operations[0].status == ("BLOCKED" if mixed_risk else "APPLIED")
        if mixed_risk:
            # With known zero inventory the confirmed zero target is already fulfilled.
            assert report.current_events[-1].risks[0].status == "FULFILLED"
            assert not any(
                signal.rule_id == "daily-companion" for signal in report.current_events[-1].signals
            )
