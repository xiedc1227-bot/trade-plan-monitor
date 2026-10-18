"""Ordered source tranches consume each reviewed buy exactly once."""

from copy import deepcopy
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_repository import DailyRepository


def tranche_plan():
    raw = unified_payload()
    raw["activation"] = {"mode": "MANUAL"}
    raw["risk_branches"] = []
    first = raw["ordinary_rules"][0]
    first.update(
        rule_id="first-100", quantity=100, zone=None, validity={"mode": "PLAN_ACTIVE"},
        independent_signal={"mode": "ONCE_PER_RULE"},
        condition={"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
                   "comparator": "LT", "reference": {"mode": "FIXED", "value": "5000",
                   "unit": "FEN", "as_of": "2026-06-01", "source": "Synthetic threshold"}},
    )
    second = deepcopy(first)
    second.update(rule_id="second-100", independent_signal={
        "mode": "AFTER_RULE_COMPLETED", "prior_rule_id": first["rule_id"],
    })
    raw["ordinary_rules"] = [first, second]
    return UnifiedTradePlan.model_validate(raw)


def confirm(plan, index, *, day=1, previous=(), facts=()):
    series, _ = synthetic_series(count=day)
    sessions, _ = synthetic_series(count=6)
    return confirm_signal(
        plan, plan.ordinary_rules[index], series=series, facts=facts, previous=previous,
        session_dates=sessions.session_dates, plan_version_id="version-1", review_id="review-1",
    )


@pytest.mark.parametrize("state,simulated_qty", [
    (None, 0), ("CONFIRMED", 0), ("READY", 0), ("SIMULATED", 50),
    ("EXPIRED", 0), ("INVALIDATED", 0),
])
def test_second_tranche_requires_actual_full_first_tranche_completion(state, simulated_qty):
    plan = tranche_plan()
    first = confirm(plan, 0)
    assert first is not None
    previous = () if state is None else ({**first, "state": state,
                                         "simulated_qty": simulated_qty},)
    assert confirm(plan, 1, day=2, previous=previous) is None


def test_completed_first_tranche_allows_the_second_buy_despite_same_side_history():
    plan = tranche_plan()
    first = {**confirm(plan, 0), "state": "SIMULATED", "simulated_qty": 100}
    second = confirm(plan, 1, day=2, previous=(first,))

    assert second is not None
    assert second["side"] == first["side"] == "BUY"
    assert second["signal_id"] != first["signal_id"]
    assert second["rule_id"] == "second-100"
    assert second["planned_qty"] == 100
    at = datetime.combine(datetime.fromisoformat(second["execution_date"]).date(), time(10),
                          ZoneInfo("Asia/Shanghai"))
    ready = check_execution(
        plan, second, inventory={"known": True, "total_qty": 100}, quote_fen=3900,
        evaluated_at=at, tradable=True, risk_blocked=False, risk_known=True,
    )
    assert ready["state"] == "READY" and ready["executable_qty"] == 100


@pytest.mark.parametrize("state", ["CONFIRMED", "READY", "SIMULATED", "EXPIRED", "INVALIDATED"])
def test_once_only_tranches_do_not_issue_again_on_later_dates(state):
    plan = tranche_plan()
    first = {**confirm(plan, 0), "state": "SIMULATED", "simulated_qty": 100}
    second = confirm(plan, 1, day=2, previous=(first,))
    second = {**second, "state": state, "simulated_qty": 100 if state == "SIMULATED" else 0}

    assert confirm(plan, 0, day=3, previous=(first, second)) is None
    assert confirm(plan, 1, day=3, previous=(first, second)) is None


def test_an_unrelated_filled_rule_does_not_satisfy_the_predecessor():
    plan = tranche_plan()
    unrelated = {**confirm(plan, 0), "rule_id": "different-buy",
                 "state": "SIMULATED", "simulated_qty": 100}
    assert confirm(plan, 1, day=2, previous=(unrelated,)) is None


def test_completed_predecessor_does_not_unlock_a_confirmation_before_its_execution_day():
    plan = tranche_plan()
    first = {**confirm(plan, 0), "state": "SIMULATED", "simulated_qty": 100}
    # The first order executes on June 2. A replay of June 1's official close
    # cannot retrospectively establish the subsequent tranche's confirmation.
    assert first["execution_date"] == "2026-06-02"
    assert confirm(plan, 1, day=1, previous=(first,)) is None


def test_existing_independent_event_rules_still_require_a_new_verified_event():
    raw = tranche_plan().model_dump(mode="json")
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0]["independent_signal"] = {
        "mode": "REVIEWED_INDEPENDENT_EVENT", "evidence_requirement": "New technical structure",
    }
    plan = UnifiedTradePlan.model_validate(raw)
    first = confirm(plan, 0)
    assert confirm(plan, 0, day=2, previous=(first,)) is None
    filled = {**first, "state": "SIMULATED", "simulated_qty": 100}
    assert confirm(plan, 0, day=3, previous=(filled,)) is None
    second = confirm(plan, 0, day=3, previous=(filled,), facts=({
        "id": "new-structure", "kind": "INDEPENDENT_EVENT",
        "prior_signal_id": first["signal_id"], "trade_date": "2026-06-03", "verified": True,
    },))
    assert second is not None and second["signal_id"] != first["signal_id"]


def test_signal_history_projection_keeps_consumed_predecessor_of_same_side_tranche(monkeypatch):
    plan = tranche_plan()
    first = {**confirm(plan, 0), "state": "SIMULATED", "simulated_qty": 100}
    second = {**confirm(plan, 1, day=2, previous=(first,)),
              "state": "SIMULATED", "simulated_qty": 100}
    rows = tuple({"id": signal["signal_id"], "payload": signal,
                  "created_at": f"2026-06-0{index + 1}T16:00:00+08:00"}
                 for index, signal in enumerate((first, second)))
    repository = DailyRepository(None, clock=lambda: None, id_factory=lambda: None)
    monkeypatch.setattr(repository, "iter_records", lambda **kwargs: iter(rows))

    retained = repository.current_signals(symbol=plan.symbol)

    assert {row["payload"]["rule_id"] for row in retained} == {"first-100", "second-100"}
    previous = tuple(row["payload"] for row in retained)
    assert confirm(plan, 0, day=3, previous=previous) is None
    assert confirm(plan, 1, day=3, previous=previous) is None
