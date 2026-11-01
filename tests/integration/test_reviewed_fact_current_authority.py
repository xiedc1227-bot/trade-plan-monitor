"""Actual current FACT use and explicitly arranged pre-fix persisted artifacts.

FIELD source is a complete engineering fixture, not NL extraction acceptance.
The legacy arrangement deliberately invokes the unchanged kind-only pure engine,
then records its actual result. Current source/review authority is never mocked.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from tests.integration.test_daily_plan_chain import (
    FRIDAY,
    SH,
    TUESDAY,
    WEDNESDAY,
    Chain,
)
from tests.integration.test_source_action_cutover import _install_severe
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_unified_runtime import (
    current_plan,
    minute_inputs,
    persist_minute_inputs,
)

from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

_VOLUME, _WICK = "成交不异常放大", "明显下影"


def _fact(requirement):
    return {
        "type": "REVIEWED_FACT",
        "fact_kind": "VOLUME_OR_CANDLE",
        "evidence_requirement": requirement,
        "validity_scope": "TRADE_DATE",
    }


def _plan(mode):
    raw = current_plan(mixed=False).model_dump(mode="json")
    condition = _fact(_VOLUME)
    if mode != "unique":
        condition = {
            "type": "ALL" if mode == "ambiguous" else "ANY",
            "conditions": [_fact(_VOLUME), _fact(_WICK)],
        }
        if mode == "numeric-any":
            condition["conditions"].append(
                {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000}
            )
    raw["ordinary_rules"][0]["condition"] = condition
    return UnifiedTradePlan.model_validate(raw)


@contextmanager
def _current(tmp_path, mode="ambiguous"):
    chain = Chain(tmp_path)
    chain.plan = _plan(mode)
    with chain.client:
        chain.activate()
        with chain.plans._unit_of_work() as work:
            for previous, day in (
                (FRIDAY - timedelta(days=1), FRIDAY),
                (FRIDAY, TUESDAY),
                (TUESDAY, WEDNESDAY),
            ):
                work.daily.session.add(
                    TradingCalendar(
                        exchange=chain.plan.market,
                        cal_date=day,
                        is_open=True,
                        previous_trade_date=previous,
                    )
                )
            work.commit()
        chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=SH)
        chain.position()
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "only-volume-asserted",
                "kind": "VOLUME_OR_CANDLE",
                "tradeDate": str(TUESDAY),
                "evidence": ("人工仅确认成交不异常放大；未核验任何下影线形态条件，"
                             "不作此项满足声明。"),
                "expectedRevision": 0,
            },
        )
        native = chain.client.get("/api/v1/plan-versions/" + chain.version["id"]).json()
        assert native["sourceCoverage"]["coverageComplete"] is True
        assert native["sourceCoverage"]["currentReviewBound"] is True
        with chain.plans._unit_of_work() as work:
            facts = work.daily.list(symbol=chain.plan.symbol, kind="FACT")
            assert len(facts) == 1 and facts[0]["payload"]["kind"] == "VOLUME_OR_CANDLE"
        yield chain, inputs


def _legacy_ready(chain, inputs):
    """Persist a genuine pre-fix kind-only result independently of new producer hooks.

    The original pure confirmation/check_execution contract is intentionally left
    unchanged for frozen replay. This arrangement does not claim current approval
    of the old signal; the following current consumers must inspect it themselves.
    """
    # FACT HTTP reevaluation may lack its quote provider. Refresh the actual
    # observation frame before arranging the old pure-engine signal, so a
    # consumer denial cannot pass merely because quote/data are missing.
    chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(chain.plan.symbol)
        review = work.daily.get("review-" + chain.version["id"])["payload"]
        facts = tuple(
            {"id": row["id"], **row["payload"]}
            for row in work.daily.list(symbol=chain.plan.symbol, kind="FACT")
        )
        signal = confirm_signal(
            chain.plan,
            chain.plan.ordinary_rules[0],
            series=None,
            facts=facts,
            previous=(),
            session_dates=inputs.session_dates,
            plan_version_id=chain.version["id"],
            review_id=review["review_id"],
            bars=inputs.five_minute_bars,
            target=inputs.minute_target,
            trading_calendar=inputs.trading_calendar,
        )
        assert signal is not None
        children = signal["evidence"][0]["children"]
        assert children[0]["fact_ids"] == children[1]["fact_ids"] == [facts[0]["id"]]
        inventory = DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date())
        ready = check_execution(
            chain.plan,
            signal,
            inventory=inventory,
            quote_fen=inputs.quote.price_fen,
            evaluated_at=chain.now,
            tradable=True,
            risk_blocked=False,
            risk_known=True,
        )
        assert ready["state"] == "READY" and ready["executable_qty"] == 100
        previous = work.daily.get(ready["signal_id"])
        row = work.daily.save(
            ready["signal_id"],
            kind="SIGNAL",
            symbol=chain.plan.symbol,
            lineage=chain.plan.plan_id,
            payload=ready,
            expected_revision=0 if previous is None else previous["revision"],
        )
        head = work.daily.get("evaluation-head-" + chain.plan.symbol)
        assert head["payload"]["quote"]["price_fen"] == inputs.quote.price_fen
        assert head["payload"]["data_blockers"] == []
        snapshot = {
            **head["payload"],
            "signals": [{**ready, "revision": row["revision"]}],
            "fact_revisions": [
                {"id": fact["id"], "revision": fact["revision"]}
                for fact in work.daily.list(symbol=chain.plan.symbol, kind="FACT")
            ],
            "inventory": inventory,
        }
        work.daily.save(
            head["id"],
            kind="EVALUATION",
            symbol=chain.plan.symbol,
            lineage=head["lineage"],
            payload=snapshot,
            expected_revision=head["revision"],
        )
        chain.runtime._enqueue(
            work,
            chain.plan,
            active,
            review,
            chain.now,
            cause_id=ready["signal_id"],
            side=ready["side"],
            quantity=100,
            simulated=0,
            confirmed=ready["confirmed_trade_date"],
            execution=ready["execution_date"],
            scope=None,
            evidence=ready["evidence"],
        )
        work.commit()
    return ready


def _event(chain, signal):
    with chain.plans._unit_of_work() as work:
        rows, _ = work.alerts.list_events(
            symbol=chain.plan.symbol,
            signal_type=None,
            acknowledged=None,
            start_at=None,
            end_at=None,
            offset=0,
            limit=100,
        )
        (event,) = (
            row
            for row in rows
            if row.cause_id == signal["signal_id"] and row.evaluated_at == chain.now
        )
        return event


def _business(chain):
    with chain.plans._unit_of_work() as work:
        return {
            kind: tuple(
                (r["id"], r["revision"], json.dumps(r["payload"], sort_keys=True))
                for r in work.daily.list(symbol=chain.plan.symbol, kind=kind)
            )
            for kind in ("POSITION", "SIGNAL", "FACT", "SIMULATION")
        }


def _command(chain, signal):
    with chain.plans._unit_of_work() as work:
        row = work.daily.get(signal["signal_id"])
        inventory = DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date())
    return {
        "planVersionId": chain.version["id"],
        "causeId": signal["signal_id"],
        "expectedCauseRevision": row["revision"],
        "expectedInventoryRevision": inventory["revision"],
        "quantity": 100,
    }


def test_new_current_producer_cannot_confirm_two_hard_requirements_from_one_kind_fact(tmp_path):
    with _current(tmp_path) as (chain, inputs):
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        assert result.snapshot["signals"] == []
        with chain.plans._unit_of_work() as work:
            facts = work.daily.list(symbol=chain.plan.symbol, kind="FACT")
        assert result.snapshot["fact_revisions"] == [
            {"id": row["id"], "revision": row["revision"]} for row in facts]


@pytest.mark.parametrize("old_state", ["READY", "CONFIRMED"])
def test_new_evaluation_does_not_repromote_an_old_unattributed_signal(tmp_path, old_state):
    with _current(tmp_path) as (chain, inputs):
        signal = _legacy_ready(chain, inputs)
        with chain.plans._unit_of_work() as work:
            row = work.daily.get(signal["signal_id"])
            work.daily.save(row["id"], kind="SIGNAL", symbol=chain.plan.symbol,
                lineage=chain.plan.plan_id, payload={**row["payload"], "state": old_state},
                expected_revision=row["revision"])
            work.commit()
        chain.now += timedelta(seconds=1)
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        (current,) = result.snapshot["signals"]
        assert current["state"] == "CONFIRMED" and current["executable_qty"] == 0
        assert "REVIEWED_FACT_REQUIRED" in current["blockers"]
        with chain.plans._unit_of_work() as work:
            stored = work.daily.get(signal["signal_id"])["payload"]
        assert stored["planned_qty"] == 100 and stored["simulated_qty"] == 0
        assert stored["evidence"] == signal["evidence"]


def test_duplicate_evaluation_projects_old_signal_without_rewriting_cached_evidence(tmp_path):
    with _current(tmp_path) as (chain, inputs):
        signal = _legacy_ready(chain, inputs)
        with chain.plans._unit_of_work() as work:
            rows = [row for row in work.daily.list(symbol=chain.plan.symbol, kind="EVALUATION")
                    if not row["id"].startswith("evaluation-head-")
                    and (row["payload"].get("quote") or {}).get("price_fen") == 3970
                    and row["payload"]["fact_revisions"]]
            assert rows
            old = [work.daily.save(row["id"], kind="EVALUATION", symbol=chain.plan.symbol,
                lineage=row["lineage"], payload={**row["payload"], "signals": [signal]},
                expected_revision=row["revision"]) for row in rows]
            work.commit()
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        assert result.duplicate
        (current,) = result.snapshot["signals"]
        assert current["executable_qty"] == 0 and current["state"] == "CONFIRMED"
        assert "REVIEWED_FACT_REQUIRED" in current["blockers"]
        with chain.plans._unit_of_work() as work:
            assert [work.daily.get(row["id"]) for row in old] == old


def test_old_kind_only_ready_cause_cannot_create_a_fresh_simulation(tmp_path):
    with _current(tmp_path) as (chain, inputs):
        signal = _legacy_ready(chain, inputs)
        before = _business(chain)
        response = chain.client.post(
            "/api/v1/simulated-trades",
            json=_command(chain, signal),
            headers={"Idempotency-Key": "fresh-old-kind-only-consumption"},
        )
        assert response.status_code == 409, response.text
        assert _business(chain) == before


def test_old_kind_only_ready_message_has_no_current_send_or_action_label(tmp_path):
    with _current(tmp_path) as (chain, inputs):
        signal = _legacy_ready(chain, inputs)
        event = _event(chain, signal)
        with chain.plans._unit_of_work() as work:
            assert not daily_delivery_allowed(work.daily.session, event, chain.now)
            assert not work.alerts.is_current_actionable(event, market_date=chain.now.date())
            assert work.alerts.get(event.event_id) == event


@pytest.mark.parametrize("mode", ["unique", "numeric-any"])
def test_unique_or_independently_numeric_any_signal_retains_current_full_execution(tmp_path, mode):
    with _current(tmp_path, mode) as (chain, inputs):
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        (signal,) = result.snapshot["signals"]
        assert signal["state"] == "READY" and signal["executable_qty"] == 100
        event = _event(chain, signal)
        with chain.plans._unit_of_work() as work:
            assert daily_delivery_allowed(work.daily.session, event, chain.now)
            assert work.alerts.is_current_actionable(event, market_date=chain.now.date())
        receipt = chain.post("simulated-trades", _command(chain, signal))
        assert receipt["side"] == "BUY" and receipt["quantity"] == 100
        assert receipt["inventory"]["totalQty"] == 200


def test_original_historical_fact_owner_preserves_independent_risk_despite_buy_only_failure(legacy):
    case = legacy(historical_fact_owner=True, buy_only_failure=True)
    identity, _ = _install_severe(case)
    with case.work() as work:
        owner = work.plans.get_version_details(case.fact_owner_id)
        assert owner.id != case.id and owner.status == "SUPERSEDED"
        basis = require_source_action_authority(work, case.id, cause_id=identity)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
        assert identity in {row["id"] for row in basis.risk_rows}


def test_completed_receipt_and_consumed_cause_cannot_reopen_after_a_new_bundle(tmp_path):
    with _current(tmp_path, "unique") as (chain, inputs):
        (signal,) = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs).snapshot["signals"]
        command = _command(chain, signal)
        first = chain.post("simulated-trades", command, key="completed-unique-fact")
        before = _business(chain)
        with chain.plans._unit_of_work() as work:
            store = SourceCoverageStore(work.daily.session)
            current = store.latest(chain.version["id"])
            store.append(
                chain.version["id"],
                current.assessment,
                inputs=current.inputs,
                expected_revision=current.revision,
                command_id="new-bundle-after-consumption",
                now=chain.now,
            )
            work.commit()
        assert chain.post("simulated-trades", command, key="completed-unique-fact") == first
        chain.post("simulated-trades", command, key="new-consumption-key", status=409)
        assert _business(chain) == before
        with chain.plans._unit_of_work() as work:
            saved = work.daily.get(signal["signal_id"])["payload"]
            assert saved["state"] == "SIMULATED" and saved["simulated_qty"] == 100
