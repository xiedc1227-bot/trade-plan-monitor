"""Actual API/runtime recovery and risk cause cutovers over a temporary ledger."""

from datetime import datetime, timedelta

from tests.integration.test_daily_plan_chain import (
    FRIDAY,
    SH,
    SYMBOL,
    TUESDAY,
    WEDNESDAY,
    official_proof,
    ready_chain,
)
from tests.integration.test_daily_plan_chain import chain as chain


def fact(chain, kind, day, suffix="new", signal=None):
    return chain.post(
        "daily-plan-facts",
        {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": suffix + "-" + kind,
            "kind": kind,
            "tradeDate": str(day),
            "signalId": signal,
            "expectedRevision": 0,
            "evidence": "Synthetic complete official technical evidence independently reviewed",
        },
    )


def complete_series(chain, pairs):
    latest = pairs[-1][0]
    base = chain.series(*pairs[-1])
    bars = tuple(
        chain.series(day, price).bars[0].model_copy(update={"adjustment_as_of": latest})
        for day, price in pairs
    )
    return base.model_copy(update={"bars": bars, "session_dates": tuple(day for day, _ in pairs)})


def test_successor_expires_old_ready_before_accepting_later_independent_event(chain):
    series, ready = ready_chain(chain)
    old = ready.snapshot["signals"][0]
    chain.activate(version=2, activation_revision=1, supplement_revision=1)
    successor = chain.evaluate(series=series, price=3970)
    assert successor.snapshot["signals"][0]["executable_qty"] == 0
    chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
    later = chain.series(TUESDAY)
    chain.evaluate(series=later, official=TUESDAY)
    for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
        fact(chain, kind, TUESDAY)
    result = chain.evaluate(series=later, official=TUESDAY)
    assert len(result.snapshot["signals"]) == 1
    assert result.snapshot["signals"][0]["state"] == "EXPIRED"
    fact(chain, "INDEPENDENT_EVENT", TUESDAY, signal=old["signal_id"])
    result = chain.evaluate(series=later, official=TUESDAY)
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=SYMBOL, kind="SIGNAL")) == 2
        history = work.daily.get(old["signal_id"])["payload"]
        assert history["state"] == "EXPIRED"
        assert history["executable_qty"] == 0
    assert result.snapshot["signals"][-1]["execution_date"] == str(WEDNESDAY)
    assert result.snapshot["signals"][0]["executable_qty"] == 0


def test_reassessment_cutover_prevents_replaying_consumed_official_close_and_facts(chain):
    series, _ = ready_chain(chain)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        fact(chain, kind, FRIDAY, suffix="severe")
    confirmed = chain.evaluate(series=series, price=3970)
    risk = next(r for r in confirmed.snapshot["risks"] if r["kind"] == "SEVERE_TECHNICAL")
    assert risk["status"] == "CONFIRMED"
    chain.now += timedelta(minutes=1)
    branch = next(b for b in chain.plan.risk_branches if b.kind == "SEVERE_TECHNICAL")
    chain.post(
        "daily-risk-reassessments",
        {
            "symbol": SYMBOL,
            "riskId": risk["risk_id"],
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "expectedRevision": risk["revision"],
            "removalEvidence": official_proof(chain),
            "targetCoreQty": branch.target_core_qty,
            "targetTacticalQty": branch.target_tactical_qty,
            "involvesCore": branch.involves_core,
            "scopeEvidence": branch.scope_evidence,
        },
    )
    current = chain.client.get(f"/api/v1/daily-plan-runtime/{SYMBOL}").json()["snapshot"]
    assert next(r for r in current["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"] == "CLEAR"
    replay = chain.evaluate(series=series, price=3970)
    cleared = next(r for r in replay.snapshot["risks"] if r["kind"] == "SEVERE_TECHNICAL")
    assert cleared["status"] == "CLEAR"
    assert cleared["reassessment_id"]
    assert len(cleared["consumed_evidence_ids"]) == 2


def test_complete_missed_session_series_recovers_original_confirmation_date(chain):
    chain.evaluate(series=chain.series(FRIDAY, 3800), official=FRIDAY)
    chain.now = datetime(2026, 9, 23, 16, tzinfo=SH)
    series = complete_series(chain, [(FRIDAY, 3800), (TUESDAY, 3810), (WEDNESDAY, 3900)])
    result = chain.evaluate(series=series, official=WEDNESDAY)
    risk = next(r for r in result.snapshot["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
    assert risk["status"] == "CONFIRMED"
    assert risk["confirmed_trade_date"] == str(TUESDAY)
    assert risk["earliest_execution_date"] == str(WEDNESDAY)
    assert "NEXT_OFFICIAL_CLOSE_UNVERIFIED" not in risk["blockers"]


def test_new_activation_does_not_replay_preactivation_warmup_risk_under_new_scope(chain):
    chain.now = datetime(2026, 9, 23, 16, tzinfo=SH)
    chain.activate(version=2, activation_revision=1, supplement_revision=1)
    series = complete_series(chain, [(FRIDAY, 3800), (TUESDAY, 3810), (WEDNESDAY, 3970)])
    result = chain.evaluate(series=series, official=WEDNESDAY)
    assert all(r["status"] == "CLEAR" for r in result.snapshot["risks"])
    assert not result.snapshot["signals"]


def test_first_offline_close_recovers_only_current_next_session_ordinary_window(chain):
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.evaluate(series=chain.series())
    chain.facts()
    chain.position()
    result = chain.evaluate(series=chain.series(), price=3970)
    signal = result.snapshot["signals"][0]
    assert (signal["confirmed_trade_date"], signal["execution_date"], signal["executable_qty"]) == (
        str(FRIDAY),
        str(TUESDAY),
        100,
    )
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    result = chain.evaluate(series=chain.series(), price=3970)
    assert result.snapshot["signals"][0]["state"] == "EXPIRED"
    assert result.snapshot["signals"][0]["executable_qty"] == 0


def test_simulated_exit_fulfills_risk_allows_independent_buy_and_later_new_cause(chain):
    series, ready = ready_chain(chain)
    old_signal = ready.snapshot["signals"][0]["signal_id"]
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        fact(chain, kind, FRIDAY, suffix="exit")
    view = chain.client.get(f"/api/v1/daily-plan-runtime/{SYMBOL}").json()["snapshot"]
    assert (
        next(r for r in view["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"] == "CONFIRMED"
    )
    action = chain.evaluate(series=series, price=3970).snapshot["risk_action"]
    chain.simulate(action, 100)
    view = chain.client.get(f"/api/v1/daily-plan-runtime/{SYMBOL}").json()["snapshot"]
    assert (
        next(r for r in view["risks"] if r["kind"] == "SEVERE_TECHNICAL")["status"] == "FULFILLED"
    )
    assert view["riskAction"]["status"] == "NONE"
    chain.now += timedelta(seconds=1)
    same_window = chain.evaluate(series=series, price=3970).snapshot
    assert same_window["signals"][0]["signal_id"] == old_signal
    assert same_window["signals"][0]["risk_invalidated"] is True
    assert same_window["signals"][0]["executable_qty"] == 0
    chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
    chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
    for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
        fact(chain, kind, TUESDAY, suffix="after-exit")
    fact(chain, "INDEPENDENT_EVENT", TUESDAY, suffix="after-exit", signal=old_signal)
    result = chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
    assert result.snapshot["signals"][-1]["signal_id"] != old_signal
    assert result.snapshot["signals"][-1]["execution_date"] == str(WEDNESDAY)
    assert "HIGHER_PRIORITY_RISK" not in result.snapshot["signals"][-1]["blockers"]
    chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    new_signal = chain.evaluate(series=chain.series(TUESDAY), price=3970).snapshot["signals"][-1]
    chain.simulate(new_signal)
    chain.now = datetime(2026, 9, 23, 16, tzinfo=SH)
    chain.evaluate(series=chain.series(WEDNESDAY), official=WEDNESDAY)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        fact(chain, kind, WEDNESDAY, suffix="later-new-cause")
    result = chain.evaluate(series=chain.series(WEDNESDAY), official=WEDNESDAY)
    risk = next(r for r in result.snapshot["risks"] if r["kind"] == "SEVERE_TECHNICAL")
    assert risk["status"] == "CONFIRMED"
    assert risk["confirmed_trade_date"] == str(WEDNESDAY)


def test_reassessment_allows_same_day_new_close_with_distinct_outbox_cause(chain):
    test_reassessment_cutover_prevents_replaying_consumed_official_close_and_facts(chain)
    chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
    chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        fact(chain, kind, TUESDAY, suffix="same-day-new-cause")
    new = chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY).snapshot
    risk = next(r for r in new["risks"] if r["kind"] == "SEVERE_TECHNICAL")
    assert risk["status"] == "CONFIRMED"
    assert risk["confirmed_trade_date"] == str(TUESDAY)
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    result = chain.evaluate(series=chain.series(TUESDAY), price=3970)
    assert result.event_ids
    with chain.plans._unit_of_work() as work:
        events, _ = work.alerts.list_events(
            symbol=SYMBOL,
            signal_type=None,
            acknowledged=None,
            start_at=None,
            end_at=None,
            offset=0,
            limit=100,
        )
    risk_events = [e for e in events if e.signal_type == "RISK_EXIT"]
    assert len(risk_events) == 2
    assert len({e.dedup_key for e in risk_events}) == 2
