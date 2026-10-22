"""Bounded observations preserve iterator and event-loop ownership."""

import asyncio
import time

import pytest

from trade_plan_monitor.diagnostics import read_tracing as tracing


@pytest.mark.parametrize("failure", [False, True])
def test_scan_counts_only_consumed_values_and_closes_on_failure(failure):
    closed = []

    def values():
        try:
            yield "private payload"
            if failure:
                raise ValueError("bad input")
            yield "second"
        finally:
            closed.append(True)

    window = tracing.ReadTraceWindow()
    source = values()
    with tracing.read_trace("monitor.read", window=window):
        scan = tracing.trace_scan(source)
        assert next(scan) == "private payload"
        if failure:
            with pytest.raises(ValueError, match="bad input"):
                next(scan)
        else:
            scan.close()
    assert closed == [True]
    span = window.records[0]["spans"][0]
    assert span["stage"] == "index.scan" and span["count"] == 1
    assert 0 <= span["activeNs"] <= span["endNs"] - span["startNs"]
    assert span["status"] == ("error" if failure else "cancelled")
    assert "private payload" not in str(list(window.records))


def test_disabled_scan_is_the_original_iterator():
    iterator = iter((1, 2))
    assert tracing.trace_scan(iterator) is iterator


@pytest.mark.parametrize("cancelled", [False, True])
def test_loop_lag_is_aggregated_and_timer_is_cancelled(cancelled, monkeypatch):
    async def scenario():
        window = tracing.ReadTraceWindow()
        loop = asyncio.get_running_loop()
        before = set(loop._scheduled)
        handles = []
        original = loop.call_later

        def capture_handle(*args, **kwargs):
            handle = original(*args, **kwargs)
            handles.append(handle)
            return handle

        monkeypatch.setattr(loop, "call_later", capture_handle)
        try:
            with tracing.read_trace("monitor.read", window=window):
                with tracing.observe_loop_lag():
                    time.sleep(0.06)
                    await asyncio.sleep(0)
                    if cancelled:
                        raise asyncio.CancelledError("original cancellation")
        except asyncio.CancelledError as error:
            assert cancelled and error.args == ("original cancellation",)
        assert all(h.cancelled() for h in set(loop._scheduled) - before)
        # A due callback can already be in the ready queue instead of _scheduled.
        assert handles and handles[-1].cancelled()
        spans = window.records[0]["spans"]
        assert len(spans) == 1 and spans[0]["stage"] == "monitor.loop_lag"
        assert spans[0]["endNs"] - spans[0]["startNs"] >= 5_000_000
    asyncio.run(scenario())


def test_failed_timer_admission_preserves_cancellation(monkeypatch):
    async def scenario():
        window = tracing.ReadTraceWindow()
        loop = asyncio.get_running_loop()

        def unavailable(*args, **kwargs):
            raise RuntimeError("diagnostic timer unavailable")

        monkeypatch.setattr(loop, "call_later", unavailable)
        with pytest.raises(asyncio.CancelledError, match="original cancellation"):
            with tracing.read_trace("monitor.read", window=window):
                with tracing.observe_loop_lag():
                    raise asyncio.CancelledError("original cancellation")
        assert window.active == 0
        assert window.records[0]["status"] == "cancelled"

    asyncio.run(scenario())
