"""Tracing cannot share caller authority or suppress an evidence rejection."""

import asyncio
from dataclasses import replace

import pytest
from test_monitor_evidence_sharing import seed
from test_persistent_monitor_read_service import _NOW, _setup

from trade_plan_monitor.diagnostics.read_tracing import ReadTraceWindow, read_trace
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.mark.parametrize('budget', [1, 64])
def test_independent_authority_survives_trace_exhaustion_and_owner_change(tmp_path, budget):
    engine, _, _, health = _setup(tmp_path)
    sessions = create_session_factory(engine)
    seed(sessions, _NOW)
    authority = RuntimeReadAuthority(
        token='private-authority-token', lifecycle='STOPPED', progress=None,
        health=health, owner_absent=True,
    )
    calls = []
    changed = False

    def current():
        calls.append(1)
        return replace(authority, token=str(len(calls))) if changed else authority

    reader = RuntimeStatusReadService(sessions, current, clock=lambda: _NOW)
    window = ReadTraceWindow(max_traces=budget)

    async def scenario():
        nonlocal changed
        try:
            with read_trace('http.monitor', window=window):
                a = await reader.get_dashboard()
            with read_trace('http.monitor', window=window):
                b = await reader.get_dashboard()
            assert a == b
            assert len(calls) == 4  # Every request has its own before/after check.
            changed = True
            with read_trace('http.monitor', window=window):
                with pytest.raises(ApiError):
                    await reader.get_dashboard()
            assert len(calls) == 8  # Original 2-attempt failure budget remains intact.
        finally:
            await reader.stop()
    try:
        asyncio.run(scenario())
        assert 'private-authority-token' not in str(list(window.records))
        if budget > 1:
            monitor = [r for r in window.records if r['entry'] == 'monitor.read']
            assert len(monitor) == 3
            assert monitor[-1]['status'] == 'error'
            assert {s['stage'] for s in monitor[0]['spans']} >= {
                'monitor.authority_before', 'monitor.authority_after',
                'monitor.snapshot', 'monitor.activation_reread',
            }
    finally:
        engine.dispose()
