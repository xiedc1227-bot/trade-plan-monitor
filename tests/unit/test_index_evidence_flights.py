"""Physical evidence ownership must outlive observers and never cache results."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest

from trade_plan_monitor.state.index_evidence import RawIndexCandidate
from trade_plan_monitor.state.index_evidence_flights import (
    EvidenceUnavailable,
    IndexEvidenceFlights,
)


def wait_for(flights, field, value):
    with flights._condition:
        return flights._condition.wait_for(lambda: flights.snapshot()[field] >= value, timeout=3)


def raw(value="original"):
    return RawIndexCandidate(("head",), (value,), False)


def test_identical_inflight_bytes_share_but_later_reads_verify_again():
    flights = IndexEvidenceFlights()
    entered, release, joined = Event(), Event(), Event()
    rows, calls = (raw(),), []

    def verify(values):
        calls.append(tuple(values))
        entered.set()
        assert release.wait(3)
        return "verified"

    def scan():
        joined.set()
        return iter(rows)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("scope",), lambda: iter(rows), verify)
        assert entered.wait(3)
        second = pool.submit(flights.run, ("scope",), scan, verify)
        assert joined.wait(3)
        # Wait on a coordinator condition, not a timing guess, before releasing the leader.
        assert wait_for(flights, "joins", 1)
        release.set()
        assert first.result() == second.result() == "verified"
    assert flights.run(("scope",), lambda: iter(rows), verify) == "verified"
    assert len(calls) == 2
    assert flights.snapshot()["retained_bytes"] == 0


@pytest.mark.parametrize("change", [raw("changed"), raw(1), raw(True)])
def test_content_or_type_mismatch_is_independently_verified(change):
    flights = IndexEvidenceFlights()
    entered, release = Event(), Event()
    calls = []

    def verify(values):
        rows = tuple(values)
        calls.append(rows)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
        return rows

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("scope",), lambda: iter((raw(1),)), verify)
        assert entered.wait(3)
        other = pool.submit(flights.run, ("scope",), lambda: iter((change,)), verify)
        if type(change.payload[0]) is int:
            assert wait_for(flights, "joins", 1)
        else:
            assert wait_for(flights, "queued_owners", 1)
        release.set()
        first.result()
        assert other.result() == (change,)
    assert len(calls) == (1 if type(change.payload[0]) is int else 2)


def test_byte_budget_falls_back_to_complete_streaming_verification():
    flights = IndexEvidenceFlights(max_bytes=1)
    rows = (raw("a" * 100), raw("b" * 100))
    assert flights.run(("scope",), lambda: iter(rows), tuple) == rows
    assert flights.snapshot()["budget_fallbacks"] == 1
    assert flights.snapshot()["retained_bytes"] == 0


def test_shutdown_timeout_does_not_release_a_held_physical_validator():
    flights = IndexEvidenceFlights()
    entered, release = Event(), Event()

    def verify(values):
        entered.set()
        assert release.wait(3)
        return tuple(values)

    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(flights.run, ("scope",), lambda: iter((raw(),)), verify)
        assert entered.wait(3)
        flights.begin_shutdown()
        with pytest.raises(TimeoutError):
            flights.drain(timeout=0.01)
        assert flights.snapshot()["retained_bytes"] > 0
        with pytest.raises(EvidenceUnavailable):
            flights.run(("scope",), lambda: iter((raw(),)), verify)
        release.set()
        assert work.result() == (raw(),)
    flights.drain(timeout=1)
    assert flights.snapshot()["retained_bytes"] == 0


def test_follower_cancellation_keeps_leader_and_input_owned():
    flights = IndexEvidenceFlights()
    entered, release, cancelled = Event(), Event(), Event()

    def verify(values):
        entered.set()
        assert release.wait(3)
        return tuple(values)

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(flights.run, ("s",), lambda: iter((raw(),)), verify)
        assert entered.wait(3)
        follower = pool.submit(
            flights.run, ("s",), lambda: iter((raw(),)), verify, cancelled=cancelled,
        )
        assert wait_for(flights, "joins", 1)
        cancelled.set()
        with pytest.raises(EvidenceUnavailable):
            follower.result(timeout=1)
        assert not leader.done()
        assert flights.snapshot()["retained_bytes"] > 0
        release.set()
        assert leader.result() == (raw(),)
    assert flights.snapshot()["physical_validations"] == 1


def test_cancelled_leader_observer_cannot_cancel_follower_proof():
    flights = IndexEvidenceFlights()
    entered, release, cancelled = Event(), Event(), Event()

    def verify(values):
        entered.set()
        assert release.wait(3)
        return tuple(values)

    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(
            flights.run, ("s",), lambda: iter((raw(),)), verify, cancelled=cancelled,
        )
        assert entered.wait(3)
        follower = pool.submit(flights.run, ("s",), lambda: iter((raw(),)), verify)
        assert wait_for(flights, "joins", 1)
        cancelled.set()
        assert flights.snapshot()["active_calls"] == 2
        release.set()
        assert leader.result() == follower.result() == (raw(),)


def test_completion_during_comparison_forces_new_full_validation(monkeypatch):
    flights = IndexEvidenceFlights()
    entered, release = Event(), Event()
    calls = []
    original = RawIndexCandidate.exact

    def verify(values):
        calls.append(tuple(values))
        entered.set()
        assert release.wait(3)
        return "verified"

    def compare(self, other):
        with flights._condition:
            flight = flights._active
            release.set()
            assert flights._condition.wait_for(lambda: flight.future.done(), timeout=3)
        return original(self, other)

    monkeypatch.setattr(RawIndexCandidate, "exact", compare)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("s",), lambda: iter((raw(),)), verify)
        assert entered.wait(3)
        second = pool.submit(flights.run, ("s",), lambda: iter((raw(),)), verify)
        assert first.result() == second.result() == "verified"
    assert len(calls) == 2
    assert flights.snapshot()["retained_bytes"] == 0


def test_missing_suffix_and_hash_collision_never_share(monkeypatch):
    monkeypatch.setattr(RawIndexCandidate, "__hash__", lambda self: 0)
    flights = IndexEvidenceFlights()
    entered, release = Event(), Event()
    first_rows, second_rows = (raw(),), (raw(), raw("missing-before"))
    assert hash(first_rows[0]) == hash(second_rows[1])

    def verify(values):
        rows = tuple(values)
        entered.set()
        assert release.wait(3)
        return rows

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("s",), lambda: iter(first_rows), verify)
        assert entered.wait(3)
        second = pool.submit(flights.run, ("s",), lambda: iter(second_rows), verify)
        assert wait_for(flights, "queued_owners", 1)
        release.set()
        assert first.result() == first_rows
        assert second.result() == second_rows
    assert flights.snapshot()["physical_validations"] == 2


def test_failed_scan_releases_admission_and_has_no_completed_error_cache():
    flights = IndexEvidenceFlights()

    def broken():
        raise ValueError("stored input damaged")

    with pytest.raises(ValueError, match="damaged"):
        flights.run(("s",), broken, tuple)
    assert flights.run(("s",), lambda: iter((raw(),)), tuple) == (raw(),)
    assert flights.snapshot()["active_calls"] == 0


def test_distinct_queue_is_bounded_and_cancelled_queue_never_validates():
    flights = IndexEvidenceFlights()
    entered, release, cancelled = Event(), Event(), Event()
    calls = []

    def verify(values):
        calls.append(tuple(values))
        entered.set()
        assert release.wait(3)
        return "valid"

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("a",), lambda: iter((raw(),)), verify)
        assert entered.wait(3)
        queued = pool.submit(
            flights.run, ("b",), lambda: iter((raw(),)), verify, cancelled=cancelled,
        )
        assert wait_for(flights, "queued_owners", 1)
        with pytest.raises(EvidenceUnavailable, match="queue is full"):
            flights.run(("c",), lambda: iter((raw(),)), verify)
        cancelled.set()
        with pytest.raises(EvidenceUnavailable):
            queued.result(timeout=1)
        release.set()
        assert first.result() == "valid"
    assert len(calls) == 1


def test_deadline_is_not_renewed_when_waiting_for_distinct_work():
    flights = IndexEvidenceFlights()
    entered, release = Event(), Event()

    def verify(values):
        entered.set()
        assert release.wait(3)
        return tuple(values)

    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(flights.run, ("one",), lambda: iter((raw(),)), verify)
        assert entered.wait(3)
        with pytest.raises(EvidenceUnavailable, match="deadline"):
            flights.run(
                ("two",), lambda: iter((raw(),)), verify, deadline=monotonic() + 0.01,
            )
        assert flights.snapshot()["queued_owners"] == 0
        release.set()
        first.result()


def test_collection_waiters_confirm_inputs_before_cpu_validation():
    flights = IndexEvidenceFlights()
    collecting, finish_collection = Event(), Event()
    entered, release = Event(), Event()

    def scan():
        collecting.set()
        assert finish_collection.wait(3)
        yield raw()

    def verify(values):
        entered.set()
        assert release.wait(3)
        return tuple(values)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(flights.run, ("s",), scan, verify)
        assert collecting.wait(3)
        second = pool.submit(flights.run, ("s",), lambda: iter((raw(),)), verify)
        with flights._condition:
            assert flights._condition.wait_for(lambda: flights._collect_waiters == 1, timeout=3)
        finish_collection.set()
        assert entered.wait(3)
        assert flights.snapshot()["joins"] == 1
        release.set()
        assert first.result() == second.result() == (raw(),)
    assert flights.snapshot()["physical_validations"] == 1
