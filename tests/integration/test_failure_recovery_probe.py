"""A counterexample prevents treating scope exit as a generic physical drain."""

import argparse
import gc
import json
import subprocess
import weakref

import pytest
from scripts.experiments import failure_boundary, failure_recovery_probe
from scripts.experiments.failure_recovery_probe import scope_diagnostic

from trade_plan_monitor.state.projections import ProjectionError, ProjectionMissingDependencyError


def test_scope_only_capture_retains_cycle_debt(monkeypatch):
    class Payload:
        pass

    refs = []

    def fail(*args, **kwargs):
        payload = Payload()
        payload.cycle = payload
        refs.append(weakref.ref(payload))
        raise ProjectionError("invalid")

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    enabled = gc.isenabled()
    gc.disable()
    try:
        outcome = failure_boundary._capture(iter(()), (), lambda *a: None, {})
        assert isinstance(outcome, failure_boundary.Failure)
        assert refs[0]() is not None  # Not physically drained, even after capture returns.
        gc.collect()
        assert refs[0]() is None
    finally:
        if enabled:
            gc.enable()


@pytest.mark.parametrize("kind", [ProjectionError, ProjectionMissingDependencyError, RuntimeError])
def test_diagnostic_delivery_preserves_categories(monkeypatch, kind):
    original = kind("original")

    def fail(*args, **kwargs):
        raise original

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    with pytest.raises(kind) as error:
        scope_diagnostic(iter(()), ())
    if kind is RuntimeError:
        assert error.value is original
    else:
        assert error.value is not original
        assert error.value.__context__ is None


@pytest.mark.parametrize(
    "error", [subprocess.TimeoutExpired(["child"], 90), subprocess.CalledProcessError(1, ["child"])]
)
def test_interrupted_measurement_preserves_finished_attempt(tmp_path, monkeypatch, error):
    attempts = iter([subprocess.CompletedProcess([], 0, '{"totalCpu": 1}'), error])

    def run_child(*args, **kwargs):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(failure_recovery_probe.subprocess, "run", run_child)
    output = tmp_path / "output"
    with pytest.raises(type(error)):
        failure_recovery_probe.run(argparse.Namespace(output=output, fixtures=tmp_path))
    report = json.loads((output / "measurements.json").read_text())
    assert len(report["attempts"]) == 1
    assert report["attempts"][0]["totalCpu"] == 1
    assert report["failure"]["kind"] == type(error).__name__
    assert report["qualification"] == "DIAGNOSTIC_ONLY"
