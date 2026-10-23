"""Full-proof and physical-cleanup contracts for the isolated failure boundary."""

import gc
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_bounded_c_producer as contracts
from scripts.experiments import c_validator, failure_boundary

from trade_plan_monitor.state.projections import ProjectionError, ProjectionMissingDependencyError


def test_failure_does_not_retain_graph(monkeypatch):
    class Payload:
        pass

    refs = []

    def fail(*args, **kwargs):
        payload = Payload()
        refs.append(weakref.ref(payload))
        payload.cycle = payload
        raise ProjectionError("private input") from ValueError("private cause")

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    held = []
    enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(2):
            with pytest.raises(ProjectionError) as error:
                failure_boundary.latest(iter(()), ())
            held.append(error.value)
            # The candidate must release cycles before delivery; a test-side
            # collection would hide a missing physical-cleanup step.
            assert all(ref() is None for ref in refs)
    finally:
        if enabled:
            gc.enable()
    assert held[0] is not held[1]
    assert all(e.__cause__ is None and e.__context__ is None for e in held)
    assert all("private" not in str(e) for e in held)


@pytest.mark.parametrize("kind", [ProjectionMissingDependencyError, RuntimeError])
def test_missing_and_unexpected_failures(monkeypatch, kind):
    def fail(*args, **kwargs):
        raise kind("failure")

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    with pytest.raises(kind):
        failure_boundary.latest(iter(()), ())


def test_cleanup_failure_propagates():
    class Rows:
        def __iter__(self):
            return iter(())

        def close(self):
            raise RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        failure_boundary.latest(Rows(), ())


def test_unknown_projection_subclass_is_not_sanitized(monkeypatch):
    class UnknownFailure(ProjectionError):
        pass

    original = UnknownFailure("unknown cleanup semantics")

    def fail(*args, **kwargs):
        raise original

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    with pytest.raises(UnknownFailure) as caught:
        failure_boundary.latest(iter(()), ())
    assert caught.value is original


def test_concurrent_failure_delivery_is_independent(monkeypatch):
    def fail(*args, **kwargs):
        raise ProjectionError("invalid") from ValueError("source")

    def read():
        try:
            failure_boundary.latest(iter(()), ())
        except ProjectionError as error:
            return error
        raise AssertionError("invalid proof accepted")

    monkeypatch.setattr(failure_boundary, "_verify", fail)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = [pool.submit(read) for _ in range(8)]
        errors = [future.result(timeout=5) for future in pending]
    assert len({id(error) for error in errors}) == 8
    assert all(error.__cause__ is None and error.__context__ is None for error in errors)


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr(c_validator, "latest", failure_boundary.latest)


@pytest.mark.parametrize("field", range(19))
def test_raw_fields(candidate, field):
    contracts.test_every_raw_field_differential(field)


@pytest.mark.parametrize("field", ["bar_set_hash", "request_set_hash", "formula_definition_hash"])
def test_domains(candidate, field):
    contracts.test_rehashed_root_cannot_hide_domain_tamper(field)


@pytest.mark.parametrize(
    "name",
    [
        "test_parallel_producers_do_not_share_context",
        "test_cancel_mid_production_releases_current_buffer",
        "test_cleanup_debt_prevents_new_production",
        "test_invalidated_size_fences_and_retains_debt",
        "test_storage_stop_prevents_next_encoding_unit",
    ],
)
def test_lifecycle(candidate, name):
    getattr(contracts, name)()
