"""A late simulation failure cannot commit any ledger or replay authority."""

import sqlite3
from uuid import uuid4

import pytest
from tests.integration.test_unified_runtime import current_chain, minute_inputs

from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.web import daily_service

# Pytest discovers the shared current public-workflow fixture through this import.
__all__ = ["current_chain"]


def ledger_dump(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.iterdump())


@pytest.mark.parametrize("failure_point", ["receipt", "idempotency"])
def test_late_failure_rolls_back_inventory_signal_audit_and_replay(
    current_chain, tmp_path, monkeypatch, failure_point
):
    chain = current_chain
    result = chain.runtime.run_inputs(
        plan=chain.plan, inputs=minute_inputs(chain, series=chain.series())
    )
    signal = result.snapshot["signals"][0]
    assert signal["executable_qty"] == 100
    with chain.plans._unit_of_work() as work:
        inventory_revision = work.daily.get("simulation-position-601021.SH")["revision"]
    command = {
        "planVersionId": chain.version["id"],
        "causeId": signal["signal_id"],
        "expectedCauseRevision": signal["revision"],
        "expectedInventoryRevision": inventory_revision,
        "quantity": 100,
    }
    key = uuid4().hex
    before = ledger_dump(tmp_path / "daily.sqlite")
    original_save = DailyRepository.save
    original_replay = daily_service.complete_replay

    def fail_receipt(self, identity, **kwargs):
        if kwargs["kind"] == "SIMULATION":
            # Accounting and signal writes have already occurred in this transaction.
            raise RuntimeError("injected late simulation failure")
        return original_save(self, identity, **kwargs)

    def fail_replay(*args, **kwargs):
        # The receipt, inventory, signal and audit rows exist but are uncommitted.
        raise RuntimeError("injected late simulation failure")

    if failure_point == "receipt":
        monkeypatch.setattr(DailyRepository, "save", fail_receipt)
    else:
        monkeypatch.setattr(daily_service, "complete_replay", fail_replay)
    with pytest.raises(RuntimeError, match="injected late simulation failure"):
        chain.post("simulated-trades", command, key=key)
    assert ledger_dump(tmp_path / "daily.sqlite") == before

    monkeypatch.setattr(DailyRepository, "save", original_save)
    monkeypatch.setattr(daily_service, "complete_replay", original_replay)
    receipt = chain.post("simulated-trades", command, key=key)
    assert receipt["inventory"]["totalQty"] == 200
    assert receipt["quantity"] == 100
    assert chain.post("simulated-trades", command, key=key) == receipt
