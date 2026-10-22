"""Physical proof attribution never substitutes for verification or authority."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from trade_plan_monitor.diagnostics.read_tracing import ReadTraceWindow, read_trace
from trade_plan_monitor.state.index_evidence import RawIndexCandidate
from trade_plan_monitor.state.index_evidence_flights import IndexEvidenceFlights
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


@pytest.mark.parametrize("invalid", [False, True])
def test_shared_observers_link_one_physical_proof(invalid):
    window, flights = ReadTraceWindow(), IndexEvidenceFlights()
    entered, release = Event(), Event()
    row = RawIndexCandidate(("head",), ("private payload",), False)

    def verify(values):
        entered.set()
        assert release.wait(3)
        if invalid:
            raise ValueError("invalid evidence")
        return tuple(values)

    def read():
        with read_trace("monitor.read", window=window):
            return flights.run(("scope",), lambda: iter((row,)), verify)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(read)
        assert entered.wait(3)
        second = pool.submit(read)
        try:
            with flights._condition:
                assert flights._condition.wait_for(
                    lambda: flights.snapshot()["joins"] >= 1, timeout=3,
                )
        finally:
            release.set()
        for future in (first, second):
            if invalid:
                with pytest.raises(ValueError, match="invalid evidence"):
                    future.result()
            else:
                assert future.result() == (row,)
    proofs = [r for r in window.records if r["entry"] == "index.physical"]
    assert len(proofs) == 1
    assert {s["stage"] for s in proofs[0]["spans"]} >= {
        "index.collect", "index.validate", "index.input",
    }
    links = [s for r in window.records for s in r["spans"] if s["stage"] == "index.join"]
    assert len(links) == 1 and links[0]["physicalId"] == proofs[0]["traceId"]
    assert flights.snapshot()["retained_bytes"] == 0
    assert "private payload" not in str(list(window.records))


def test_real_authority_keeps_independent_checks_with_subspans(tmp_path):
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf8")
    composition = create_monitor_composition(
        config_path=config, database_path=tmp_path / "monitor.sqlite3",
        monitor_contract_version=2,
    )
    window = ReadTraceWindow()

    async def scenario():
        await composition.start()
        try:
            with read_trace("http.monitor", window=window):
                health = await composition.read_service.get_health()
            assert health.runtime_generation == composition._runtime.runtime_generation
            assert composition.read_service.outstanding_work == 0
        finally:
            await composition.stop()
    asyncio.run(scenario())
    spans = [s for r in window.records if r["entry"] == "monitor.read" for s in r["spans"]]
    stages = [s["stage"] for s in spans]
    assert stages.count("monitor.authority_before") == stages.count("monitor.authority_after") == 1
    for name in (
        "authority.health", "authority.delivery", "authority.configuration", "authority.progress",
    ):
        assert stages.count(name) >= 2
    assert stages.count("monitor.loop_lag") == 1
