"""Linked evidence survives real SQLite reopen; changed evidence fails closed."""

import json

import pytest
from tests.integration import test_market_linkage_runtime as linkage_fixture
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_market_linkage_runtime import linked_inputs

from trade_plan_monitor.decision.market_linkage import MarketLinkageDecision
from trade_plan_monitor.state.daily_state_models import DailySignalState

linked_chain = linkage_fixture.linked_chain

def test_reopen_preserves_signal_quantity_evidence_and_identity(linked_chain, tmp_path):
    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    signal = first.snapshot["signals"][0]
    reopened = Chain(tmp_path)
    reopened.plan, reopened.now = chain.plan, chain.now
    with reopened.client:
        with reopened.plans._unit_of_work() as work:
            stored = work.daily.get(signal["signal_id"])["payload"]
            assert stored["planned_qty"] == 300
            assert stored["market_linkage"] == signal["market_linkage"]
            assert work.plans.get_active(chain.plan.symbol).plan_version_id == chain.version["id"]
        again = reopened.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
        assert again.duplicate
        assert again.snapshot["signals"][0]["signal_id"] == signal["signal_id"]


@pytest.mark.parametrize("field", ["content_hash", "consumed_hash", "evidence_cutoff"])
def test_persisted_evidence_cannot_be_changed_without_digest(linked_chain, field):
    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    raw = first.snapshot["signals"][0]["market_linkage"]
    changed = {
        **raw,
        field: "2026-09-18T17:00:00+08:00" if field == "evidence_cutoff" else "f" * 64,
    }
    with pytest.raises(ValueError, match="hash mismatch"):
        MarketLinkageDecision.model_validate_json(json.dumps(changed))


def test_frozen_calculation_rejects_quantity_override(linked_chain):
    chain = linked_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=linked_inputs(chain))
    signal = first.snapshot["signals"][0]
    with pytest.raises(ValueError, match="frozen calculation"):
        DailySignalState.model_validate_json(json.dumps({**signal, "planned_qty": 100}))
    evidence = signal["market_linkage"]
    changed = {**evidence, "calculation": {**evidence["calculation"], "authorized_quantity": 100}}
    with pytest.raises(ValueError, match="calculation hash mismatch"):
        MarketLinkageDecision.model_validate_json(json.dumps(changed))
