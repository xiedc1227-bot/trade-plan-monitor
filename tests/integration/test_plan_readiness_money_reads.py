"""Read money inputs from actual owned output and the real simulation ledger."""

import asyncio
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from tests.integration.current_pipeline_fixture import current_three_rule_plan
from tests.integration.test_current_condition_plan_authority import OwnedProgress
from tests.integration.test_runtime_status_projection import _current_status
from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
from tests.unit.test_p2_economics import economics
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
from trade_plan_monitor.live_profiles import create_index_certification, write_live_certification
from trade_plan_monitor.market_index.identity import MarketIndexCode, resolve_board_reference
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)
from trade_plan_monitor.runtime import production
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_models import CapitalBook
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


class IndexInputs:
    """Actual typed provider batches; original coordinator builds and persists snapshots."""

    async def acquire_index_data(
        self, *, index_code, decision_cutoff, five_minute_bar_count, official_daily_bar_count
    ):
        days, day = [], decision_cutoff.date() - timedelta(days=1)
        while len(days) < max(official_daily_bar_count, 70):
            if day.weekday() < 5:
                days.append(day)
            day -= timedelta(days=1)

        def bar(at, interval):
            return MarketIndexBar(
                index_code=index_code,
                interval=interval,
                bar_at=at,
                open_points=Decimal(1000),
                high_points=Decimal(1000),
                low_points=Decimal(1000),
                close_points=Decimal(1000),
                observed_at=at + timedelta(seconds=1),
                source_kind=MarketIndexSourceKind.OFFICIAL
                if interval == MarketIndexInterval.OFFICIAL_DAILY
                else MarketIndexSourceKind.PROVISIONAL,
                provider_revision=1,
            )

        return MarketIndexProviderBatch(
            index_code=index_code,
            five_minute_bars=tuple(
                bar(
                    decision_cutoff - timedelta(minutes=5 * offset), MarketIndexInterval.FIVE_MINUTE
                )
                for offset in reversed(range(five_minute_bar_count))
            ),
            official_daily_bars=tuple(
                bar(
                    datetime.combine(day, time(15), decision_cutoff.tzinfo),
                    MarketIndexInterval.OFFICIAL_DAILY,
                )
                for day in reversed(days[:official_daily_bar_count])
            ),
            content_revision=1,
            observed_at=decision_cutoff + timedelta(seconds=2),
        )


@pytest.fixture
def capital_case(tmp_path, monkeypatch, request):
    options = getattr(request, "param", "MARKET_VALUE_CAP")
    options = {"mode": options} if isinstance(options, str) else options
    mode = options.get("mode", "MARKET_VALUE_CAP")
    raw = p3_payload(mode)
    original_symbol = raw["symbol"]
    raw.update(
        symbol="003043.SZ",
        market="SZSE",
        reference_market=resolve_board_reference("003043.SZ").binding.model_dump(mode="json"),
    )
    raw["activation"] = {"mode": "MANUAL"}
    raw["position"].update(core_target_qty=0, tactical_target_qty=100)
    if options.get("economics"):
        policy = economics()
        policy["fee_schedule"]["symbols"] = [original_symbol]
        if options["economics"] == "fail":
            policy["gates"]["min_net_reward_fen"] = 100000000
        else:
            policy.update(risk_price_fen=1200, target_price_fen=1300)
        raw["levels"]["low_buy"].update(low_fen=980, high_fen=1000)
        raw["levels"]["pressure"].update(
            low_fen=policy["target_price_fen"], high_fen=policy["target_price_fen"] + 100
        )
        raw["levels"]["risk_line_fen"] = policy["risk_price_fen"]
        raw["ordinary_rules"][0]["pretrade_policy"]["level_evidence"] = [
            dict(
                level=level,
                dimension=dimension,
                source="fixture",
                excerpt="synthetic, not market rates",
                as_of=None,
                indicator=None,
            )
            for level in ("PRESSURE", "RISK")
            for dimension in ("PRICE_STRUCTURE", "TREND")
        ]
        raw["ordinary_rules"][0]["pretrade_policy"]["economics"] = policy

    def dates(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if child == original_symbol:
                    value[key] = raw["symbol"]
                elif key == "as_of":
                    value[key] = "2026-09-11"
                elif key == "effective_from":
                    value[key] = "2026-01-01"
                elif key == "effective_through":
                    value[key] = "2026-12-31"
                else:
                    dates(child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if child == original_symbol:
                    value[index] = raw["symbol"]
                else:
                    dates(child)

    dates(raw)
    if options.get("cap_fail"):
        raw["position"]["limit"]["capital_policy"]["cap_fen"] = 1
    if options.get("cap_pass"):
        raw["position"]["limit"]["capital_policy"]["cap_fen"] = 10000000
    if options.get("s0_threshold") is not None:
        raw["ordinary_rules"][0]["condition"] = {
            "type": "DAILY_PRICE_COMPARE",
            "field": "close",
            "offset": 0,
            "comparator": "GT",
            "reference": {
                "mode": "FIXED",
                "value": options["s0_threshold"],
                "unit": "FEN",
                "as_of": "2026-09-11",
                "source": "fixture",
            },
        }
    if options.get("expired_fees"):
        raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"]["effective_through"] = (
            "2026-09-12"
        )
    if options.get("simple_sell"):
        sell = current_three_rule_plan().ordinary_rules[1].model_dump(mode="json")
        sell.update(
            zone=None,
            validity={"mode": "PLAN_ACTIVE"},
            independent_signal={"mode": "ONCE_PER_RULE"},
            condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 900},
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION",
        )
        raw["ordinary_rules"].append(sell)
    plan = P3TradePlan.model_validate(raw)
    trackers = []
    native_pipeline = production.ProductionMonitorPipeline
    native_coordinator = production.MarketIndexSnapshotCoordinator
    sources = []

    def build(**kwargs):
        if options.get("empty"):
            with kwargs["unit_of_work_factory"]() as work:
                DailyAccounting(work.daily).initialize(
                    symbol=plan.symbol,
                    core_qty=0,
                    tactical_qty=0,
                    expected_revision=0,
                    now=kwargs["clock"].now(),
                )
                work.commit()
        write_live_certification(
            kwargs["certification_directory"] / "tushare-board-index-live.json",
            create_index_certification(
                observed_at=kwargs["clock"].now(),
                endpoint_url=str(kwargs["configuration"].api_url),
                capabilities={
                    code: TushareMarketIndexCapabilityStatus.ERROR
                    if code == MarketIndexCode.BSE_50
                    else TushareMarketIndexCapabilityStatus.READY
                    for code in MarketIndexCode
                },
                source_time_label=TushareMarketIndexSourceTimeLabel.END,
            ),
        )
        owned = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        trackers.append(owned.tracker)
        return native_pipeline(**kwargs, progress_owner=owned)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", build)
    monkeypatch.setattr(
        production,
        "MarketIndexSnapshotCoordinator",
        lambda _provider, **kwargs: native_coordinator(IndexInputs(), **kwargs),
    )
    if options.get("empty"):
        from tests.integration import current_pipeline_fixture

        native_fixture = current_pipeline_fixture.current_pipeline_fixture

        def without_inventory(*args, **kwargs):
            return native_fixture(*args, **kwargs, seed_inventory=False)

        monkeypatch.setattr(current_pipeline_fixture, "current_pipeline_fixture", without_inventory)

    def configure(sdk, clock, current):
        source = CurrentCloseSDK(clock, (current.symbol,))
        sources.append(source)

        def daily(**kwargs):
            frame = source.daily(**kwargs)
            if options.get("economics"):
                frame[["open", "high", "low", "close"]] = "10.00"
            return frame

        sdk.daily, sdk.adj_factor = daily, source.adj_factor

    case = _current_status(tmp_path, monkeypatch, plan=plan, configure_sdk=configure)
    try:

        def owner():
            token, configuration, plans = case.pipeline.runtime_status_snapshot()
            return replace(
                case.current[0],
                token=token,
                configuration_revision=configuration,
                plans=plans,
                progress=trackers[0].snapshot(),
            )

        case.owner = owner
        case.options = options
        case.daily_source = sources[0]
        case.reader = RuntimeStatusReadService(case.sessions, owner, clock=case.pipeline._clock.now)
        assert owner().plans[0].completion is not None
        assert owner().plans[0].daily_admission is not None
        yield case
    finally:
        case.close()


def read_money(case):
    return asyncio.run(
        case.reader.get_plan_readiness(version_id=case.result.snapshot["plan_version_id"])
    )


@pytest.mark.parametrize(
    "capital_case",
    [
        {"cap_pass": True},
        {"cap_fail": True},
        {"mode": "OPEN_COST_CAP"},
    ],
    indirect=True,
)
def test_native_money_projection_preserves_actual_phase_and_verdict(capital_case):
    from trade_plan_monitor.web.plan_readiness_models import ReadinessAssessment

    case = capital_case
    decision = case.result.snapshot["market_linkage"][0]
    assert not case.result.snapshot.get("ordinary_evaluations")
    proof = decision["confirmation"][0]
    assert proof["condition"] == case.plan.ordinary_rules[0].condition.model_dump(mode="json")
    assert proof["outcome"] == "MISSING_INPUT"
    assert len(proof["children"]) == 3
    assert all(child["condition"]["type"] == "REVIEWED_FACT" for child in proof["children"])
    assessed = read_money(case)
    result = next(rule for rule in assessed.rules if rule.facts.side == "BUY")
    buy = result.facts
    expected = case.result.snapshot["market_linkage"][0]["calculation"]["capital"]
    assert expected["outcome"] == (
        "PASS"
        if case.options.get("cap_pass")
        else "FAIL"
        if case.options.get("cap_fail")
        else "UNKNOWN"
    )
    assert buy.money is not None
    assert buy.money.capital.model_dump(mode="json") == expected
    assert buy.money.inputs.state == ("UNKNOWN" if expected["outcome"] == "UNKNOWN" else "PASS")
    assert buy.money.capital.phase == "CONFIRMATION"
    assert (
        buy.money.economics.model_dump(mode="json")
        == case.result.snapshot["pretrade"][0]["economics"]
    )
    assert buy.execution.approved_quantity is None
    assert buy.money.inputs.observation.as_of == datetime.fromisoformat(
        case.result.snapshot["evaluated_at"]
    )
    assert buy.root_outcome == proof["outcome"]
    states = {
        "SATISFIED": "CONDITION_TRUE",
        "UNSATISFIED": "CONDITION_FALSE",
        "MISSING_INPUT": "MISSING_INPUT",
    }
    assert result.state == states[proof["outcome"]]
    expected_leaves = []
    pending = [("condition", proof)]
    while pending:
        path, item = pending.pop()
        if item["condition"]["type"] in {"ALL", "ANY"}:
            pending.extend(
                (f"{path}.conditions[{index}]", child)
                for index, child in reversed(list(enumerate(item["children"])))
            )
        else:
            expected_leaves.append((path, states[item["outcome"]]))
    assert [(leaf.condition_path, leaf.state) for leaf in buy.leaves] == expected_leaves
    assert all(leaf.reason == "HUMAN_EVIDENCE_REQUIRED" for leaf in buy.leaves)
    assert buy.observation.availability == "CURRENT"
    assert buy.evaluated_at == datetime.fromisoformat(decision["evidence_cutoff"])
    assert buy.evaluated_target.kind == "OFFICIAL_CLOSE"
    assert buy.evaluated_target.trade_date.isoformat() == decision["decision_session"]
    assert (
        ReadinessAssessment.model_validate_json(assessed.model_dump_json(by_alias=True)) == assessed
    )


@pytest.mark.parametrize(
    ("capital_case", "outcome", "leaf_state"),
    [
        pytest.param(
            {"cap_fail": True, "s0_threshold": "6400"},
            "SATISFIED",
            "CONDITION_TRUE",
            id="complete-s0-true",
        ),
        pytest.param(
            {"cap_fail": True, "s0_threshold": "6500"},
            "UNSATISFIED",
            "CONDITION_FALSE",
            id="complete-s0-false",
        ),
    ],
    indirect=["capital_case"],
)
def test_native_complete_s0_survives_the_monetary_early_return(capital_case, outcome, leaf_state):
    case = capital_case
    snapshot = case.result.snapshot
    assert not snapshot.get("ordinary_evaluations")
    decision = snapshot["market_linkage"][0]
    proof = decision["confirmation"][0]
    assert proof["condition"] == case.plan.ordinary_rules[0].condition.model_dump(mode="json")
    assert proof["outcome"] == outcome and not proof["children"]
    assert proof["bar_ids"]
    assessed = read_money(case)
    result = next(rule for rule in assessed.rules if rule.facts.side == "BUY")
    buy = result.facts
    assert buy.root_outcome == proof["outcome"]
    assert [(leaf.condition_path, leaf.state) for leaf in buy.leaves] == [("condition", leaf_state)]
    assert buy.leaves[0].reason is None and buy.leaves[0].evidence_refs
    assert buy.evaluated_target.kind == "OFFICIAL_CLOSE"
    assert buy.evaluated_target.trade_date.isoformat() == decision["decision_session"]
    assert buy.evaluated_at == datetime.fromisoformat(decision["evidence_cutoff"])
    # The next official close still uses the existing complex-rule expiry policy.
    assert buy.observation.availability == "CACHED" and buy.observation.expires_at is None
    assert result.state == "UNKNOWN" and result.reason == "AUTHORITY_UNAVAILABLE"
    assert buy.money.capital.model_dump(mode="json") == decision["calculation"]["capital"]
    assert buy.execution.approved_quantity is None


@pytest.mark.parametrize("capital_case", [{"cap_pass": True}], indirect=True)
def test_new_daily_admission_cannot_certify_the_old_native_money(capital_case):
    case = capital_case
    before = read_money(case)
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    day = inputs.series.bars[-1].trade_date
    old_admission = case.owner().plans[0].daily_admission
    case.daily_source.official_closes[day] = "65.00"
    corrected = asyncio.run(
        case.pipeline.prepare_daily_inputs(case.plan, case.now, day, inputs.minute_prefix)
    )
    assert corrected.series is not None and corrected.series.bars[-1].close == 6500
    assert case.owner().plans[0].daily_admission != old_admission
    assessed = read_money(case)
    buy = next(rule.facts for rule in assessed.rules if rule.facts.side == "BUY")
    assert buy.money is not None and buy.money.inputs.state == "UNKNOWN"
    assert buy.money.inputs.observation.availability == "CACHED"
    assert buy.money.capital is None and buy.money.economics is None
    assert buy.root_outcome is None
    assert buy.observation.availability == "CACHED"
    assert all(leaf.state == "UNKNOWN" for leaf in buy.leaves)
    assert buy.execution.approved_quantity == before.rules[0].facts.execution.approved_quantity


def test_market_value_inputs_do_not_require_or_create_a_cost_book(capital_case):
    case = capital_case
    with case.sessions() as session:
        assert CapitalRepository(session).get(case.plan.symbol) is None
    assessed = read_money(case)
    axis = next(axis for axis in assessed.axes if axis.axis == "INVENTORY_CAPITAL")
    assert axis.state == "PASS"
    with case.sessions() as session:
        assert CapitalRepository(session).get(case.plan.symbol) is None
    assert assessed.fresh_until is None


@pytest.mark.parametrize("capital_case", ["OPEN_COST_CAP"], indirect=True)
def test_nonempty_open_cost_inputs_do_not_invent_retained_basis(capital_case):
    assessed = read_money(capital_case)
    axis = next(axis for axis in assessed.axes if axis.axis == "INVENTORY_CAPITAL")
    assert axis.state == "UNKNOWN"
    assert assessed.snapshot.context.book_revision is None


@pytest.mark.parametrize("capital_case", [{"mode": "OPEN_COST_CAP", "empty": True}], indirect=True)
def test_known_empty_open_cost_is_zero_without_creating_a_book(capital_case):
    case = capital_case
    assessed = read_money(case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "PASS"
    assert assessed.snapshot.context.book_revision == 0
    money = next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY")
    assert money.inputs.state == "PASS" and money.capital.book_revision == 0
    assert money.capital.before_fen == 0
    with case.sessions() as session:
        assert CapitalRepository(session).get(case.plan.symbol) is None


@pytest.mark.parametrize("capital_case", [{"cap_fail": True}], indirect=True)
def test_actual_whole_cap_failure_does_not_mean_missing_monitor_inputs(capital_case):
    case = capital_case
    assert case.result.snapshot["market_linkage"][0]["calculation"]["capital"]["outcome"] == "FAIL"
    assessed = read_money(case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "PASS"
    assert assessed.summary != "READY_FOR_MONITORING"
    assert case.result.snapshot["pretrade"][0]["sizing"]["q0"] is not None
    assert (
        next(
            rule.facts.execution
            for rule in assessed.rules
            if rule.facts.owner_kind == "ORDINARY_RULE"
        ).approved_quantity
        is None
    )


@pytest.mark.parametrize(
    "capital_case", [{"economics": "fail"}, {"economics": "unknown"}], indirect=True
)
def test_existing_economics_fail_is_complete_but_unknown_inputs_are_not(capital_case):
    case = capital_case
    outcome = case.result.snapshot["pretrade"][0]["economics"]["outcome"]
    assert outcome == ("FAIL" if case.options["economics"] == "fail" else "UNKNOWN")
    assessed = read_money(case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == (
        "PASS" if outcome == "FAIL" else "UNKNOWN"
    )
    money = next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY")
    assert (
        money.economics.model_dump(mode="json") == case.result.snapshot["pretrade"][0]["economics"]
    )
    assert money.economics.outcome == outcome
    assert money.inputs.state == ("PASS" if outcome == "FAIL" else "UNKNOWN")


@pytest.mark.parametrize(
    "capital_case", [{"mode": "OPEN_COST_CAP", "empty": True, "expired_fees": True}], indirect=True
)
def test_expired_native_fee_schedule_is_not_available(capital_case):
    assessed = read_money(capital_case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "UNKNOWN"
    money = next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY")
    assert money.inputs.state == "UNKNOWN"
    assert money.capital is None and money.economics is None


@pytest.mark.parametrize("capital_case", ["OPEN_COST_CAP"], indirect=True)
@pytest.mark.parametrize("mismatch", ["none", "inventory", "lot", "quantity", "future"])
def test_open_cost_checks_the_actual_book_inventory_and_exact_lots(capital_case, mismatch):
    case = capital_case
    with case.work() as work:
        inventory = DailyAccounting(work.daily).snapshot(case.plan.symbol, case.now.date())
        lot = DailyAccounting(work.daily)._position(case.plan.symbol)["payload"]["batches"][0]
        lots = [
            dict(
                lot_id=lot["id"],
                bucket=lot["bucket"],
                quantity=lot["quantity"],
                retained_basis_fen=100000,
            )
        ]
        if mismatch == "lot":
            lots[0]["lot_id"] = "other-lot"
        if mismatch == "quantity":
            lots[0]["quantity"] += 100
        at = case.now + timedelta(seconds=1) if mismatch == "future" else case.now
        book = CapitalBook.build(
            symbol=case.plan.symbol,
            revision=1,
            inventory_revision=inventory["revision"] + (mismatch == "inventory"),
            lots=lots,
            updated_at=at,
        )
        CapitalRepository(work.daily.session).write(
            book,
            expected_revision=0,
            command_id="fixture-opening",
            request_hash="a" * 64,
            kind="OPENING",
            now=at,
            details={},
        )
        work.commit()
    assessed = read_money(case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == (
        "PASS" if mismatch == "none" else "UNKNOWN"
    )


def test_expired_quote_is_unknown_and_get_never_renews_its_time(capital_case):
    case = capital_case
    prior = case.result.snapshot["quote"]
    case.pipeline._clock.current += timedelta(minutes=5, seconds=1)
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))
    assessed = read_money(case)
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "UNKNOWN"
    assert case.result.snapshot["quote"] == prior
    assert assessed.fresh_until is None
    money = next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY")
    assert money.inputs.state == "UNKNOWN" and money.inputs.observation.availability == "CACHED"
    assert money.capital is None and money.economics is None


@pytest.mark.parametrize(
    "capital_case", [{"mode": "OPEN_COST_CAP", "simple_sell": True}], indirect=True
)
def test_independent_sell_keeps_its_result_when_buy_cost_is_unavailable(capital_case):
    assessed = read_money(capital_case)
    sell = next(
        rule
        for rule in assessed.rules
        if rule.facts.side == "SELL" and rule.facts.owner_kind == "ORDINARY_RULE"
    )
    assert sell.state == "CONDITION_FALSE"
    assert sell.facts.requirements.quote is False
    assert sell.facts.requirements.simulation_book is False
    assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "UNKNOWN"
    assert sell.facts.money.inputs.state == "PASS"
    assert sell.facts.money.capital is None and sell.facts.money.economics is None
    buy = next(rule.facts for rule in assessed.rules if rule.facts.side == "BUY")
    assert buy.money.inputs.state == "UNKNOWN" and buy.money.capital.outcome == "UNKNOWN"


def test_money_get_has_no_business_writes_or_recalculation(capital_case, monkeypatch):
    from trade_plan_monitor.decision import p2_economics, p3_capital, unified_lifecycle
    from trade_plan_monitor.runtime import daily_service

    def forbidden(*_args, **_kwargs):
        raise AssertionError("GET must only read existing native facts")

    for module, name in (
        (p3_capital, "assess_capital"),
        (p2_economics, "calculate_economics"),
        (unified_lifecycle, "check_execution"),
        (daily_service, "check_execution"),
        (daily_service, "risk_execution"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    case, writes = capital_case, []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(case.engine, "before_cursor_execute", record)
    try:
        assessed = read_money(case)
        assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "PASS"
        assert next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY").capital
        assert writes == []
    finally:
        event.remove(case.engine, "before_cursor_execute", record)


@pytest.mark.parametrize("capital_case", ["MARKET_VALUE_CAP", "OPEN_COST_CAP"], indirect=True)
@pytest.mark.parametrize("repeated", [False, True])
def test_actual_book_changes_are_fenced_only_for_the_relevant_policy(
    capital_case,
    monkeypatch,
    repeated,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case, calls = capital_case, []

    def advance():
        with case.work() as work:
            accounting = DailyAccounting(work.daily)
            inventory = accounting.snapshot(case.plan.symbol, case.now.date())
            lots = accounting._position(case.plan.symbol)["payload"]["batches"]
            repo = CapitalRepository(work.daily.session)
            previous = repo.get(case.plan.symbol)
            revision = 0 if previous is None else previous.revision
            book = CapitalBook.build(
                symbol=case.plan.symbol,
                revision=revision + 1,
                inventory_revision=inventory["revision"],
                updated_at=case.now,
                lots=[
                    dict(
                        lot_id=lot["id"],
                        bucket=lot["bucket"],
                        quantity=lot["quantity"],
                        retained_basis_fen=100000 + revision,
                    )
                    for lot in lots
                ],
            )
            repo.write(
                book,
                expected_revision=revision,
                command_id=f"actual-book-{revision}",
                request_hash="b" * 64,
                kind="OPENING" if revision == 0 else "RECONCILIATION",
                now=case.now,
                details={},
            )
            work.commit()

    advance()
    original = projection.read_readiness_binding

    def changed(*args):
        if repeated or not calls:
            advance()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    assessed = read_money(case)
    if case.options["mode"] == "MARKET_VALUE_CAP":
        assert len(calls) == 1 and assessed.snapshot.context.book_revision is None
        assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "PASS"
        assert next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY").capital
    else:
        assert len(calls) == 2
        if repeated:
            assert all(a.reason == "CONTEXT_CHANGED" for a in assessed.axes)
            assert all(rule.facts.money.inputs.state == "UNKNOWN" for rule in assessed.rules)
            assert all(rule.facts.money.capital is None for rule in assessed.rules)
        else:
            assert assessed.snapshot.context.book_revision == 2
            assert next(a for a in assessed.axes if a.axis == "INVENTORY_CAPITAL").state == "PASS"
            money = next(rule.facts.money for rule in assessed.rules if rule.facts.side == "BUY")
            assert money.inputs.state == "PASS" and money.capital is None


def test_actual_quote_loss_between_reads_cannot_reuse_the_old_quote(capital_case, monkeypatch):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case, calls = capital_case, []
    original = projection.read_readiness_binding

    def changed(*args):
        if not calls:
            case.sdk.current_close_fen = 991
            asyncio.run(case.pipeline.run_deadline(case.deadline))
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    assessed = read_money(case)
    assert len(calls) == 2
    assert assessed.snapshot.computed_at == case.pipeline._clock.now()
    with case.work() as work:
        assert work.daily.get("evaluation-head-" + case.plan.symbol)["payload"]["quote"] is None
    data = next(axis for axis in assessed.axes if axis.axis == "DATA_EVALUATION")
    assert data.state == "UNKNOWN"
    assert (
        next(axis for axis in assessed.axes if axis.axis == "INVENTORY_CAPITAL").state == "UNKNOWN"
    )
    assert assessed.fresh_until is None


def test_current_quote_read_preserves_original_evaluation_and_quote_times(capital_case):
    case = capital_case
    original = case.result.snapshot["quote"].copy()
    case.pipeline._clock.current += timedelta(seconds=20)
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))
    assessed = read_money(case)
    data = next(axis for axis in assessed.axes if axis.axis == "DATA_EVALUATION")
    assert data.observation.as_of.isoformat() == case.result.snapshot["evaluated_at"]
    assert case.result.snapshot["quote"] == original
    assert next(axis for axis in assessed.axes if axis.axis == "INVENTORY_CAPITAL").state == "PASS"
    assert assessed.fresh_until is None
