"""ML-T30: inert lifecycle values and bounded on-demand defaults."""

from dataclasses import FrozenInstanceError

import pytest

from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
from trade_plan_monitor.backtest.service_contract import (
    BacktestCapability,
    BacktestServiceSnapshot,
    BacktestServiceState,
)


def test_unused_snapshot_has_no_capability_or_authorized_jobs() -> None:
    snapshot = BacktestServiceSnapshot()
    assert snapshot.state is BacktestServiceState.NOT_INITIALIZED
    assert not snapshot.allows(BacktestCapability.METADATA)
    assert not snapshot.allows(BacktestCapability.EXECUTION)
    assert snapshot.authorized_job_ids == frozenset()
    assert snapshot.physically_drained


def test_history_readiness_does_not_authorize_execution() -> None:
    snapshot = BacktestServiceSnapshot(state=BacktestServiceState.READ_READY)
    assert snapshot.allows(BacktestCapability.METADATA)
    assert not snapshot.allows(BacktestCapability.EXECUTION)
    assert snapshot.authorized_job_ids == frozenset()


def test_ready_does_not_grant_authority_to_historical_backlog() -> None:
    snapshot = BacktestServiceSnapshot(state=BacktestServiceState.READY)
    assert snapshot.allows(BacktestCapability.EXECUTION)
    assert snapshot.authorized_job_ids == frozenset()


def test_degraded_physical_work_prevents_safe_replacement() -> None:
    snapshot = BacktestServiceSnapshot(
        state=BacktestServiceState.DEGRADED, outstanding_work=1,
    )
    assert not snapshot.physically_drained
    assert not snapshot.allows(BacktestCapability.EXECUTION)
    with pytest.raises(FrozenInstanceError):
        snapshot.outstanding_work = 0


@pytest.mark.parametrize("state", [
    BacktestServiceState.DEGRADED,
    BacktestServiceState.STOPPING,
    BacktestServiceState.STOPPED,
])
def test_retained_metadata_is_available_only_before_shutdown(state: BacktestServiceState) -> None:
    snapshot = BacktestServiceSnapshot(state=state, read_capability_available=True)
    assert snapshot.allows(BacktestCapability.METADATA) is (state is BacktestServiceState.DEGRADED)
    assert not snapshot.allows(BacktestCapability.EXECUTION)


def test_timing_defaults_are_observation_budgets_not_thread_termination() -> None:
    config = BacktestServiceConfig()
    assert config.request_wait_seconds == 1
    assert config.initialization_watchdog_seconds == 5
    assert config.shutdown_wait_seconds == 5
    assert config.max_resume_jobs == 1
    assert config.recovery_delays_seconds == (1, 5, 15)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_unbounded_or_invalid_wait_is_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        BacktestServiceConfig(request_wait_seconds=value)


def test_negative_outstanding_work_is_rejected() -> None:
    with pytest.raises(ValueError):
        BacktestServiceSnapshot(outstanding_work=-1)


@pytest.mark.parametrize("value", [0, 2, 100, True])
def test_multi_job_recovery_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        BacktestServiceConfig(max_resume_jobs=value)
