"""Typed adapters from durable claims to blocking backtest operations."""

from __future__ import annotations

import json
from typing import Protocol

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import (
    BacktestProgressCallback,
    CancellationToken,
    validate_operation_controls,
)
from trade_plan_monitor.backtest.jobs.models import (
    BacktestDatasetScopeRequest,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
    BacktestJobClaim,
    BacktestJobKind,
    BacktestJobRequest,
    BacktestJobResult,
    BacktestRunJobRequest,
    BacktestRunJobResult,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput


class BacktestJobOperation(Protocol):
    """One synchronous operation sharing cancellation and progress controls."""

    def __call__(
        self,
        request: BacktestJobRequest,
        *,
        cancellation_token: CancellationToken,
        progress_callback: BacktestProgressCallback,
    ) -> BacktestJobResult: ...


class BacktestJobOperations:
    """Validate persisted request bytes and dispatch one closed job kind."""

    def __init__(
        self,
        *,
        data_sync: BacktestJobOperation,
        dataset_verify: BacktestJobOperation,
        backtest_run: BacktestJobOperation,
    ) -> None:
        operations = {
            BacktestJobKind.DATA_SYNC: data_sync,
            BacktestJobKind.DATASET_VERIFY: dataset_verify,
            BacktestJobKind.BACKTEST_RUN: backtest_run,
        }
        if any(not callable(operation) for operation in operations.values()):
            raise TypeError("every backtest job operation must be callable")
        self._operations = operations

    def execute(
        self,
        claim: BacktestJobClaim,
        *,
        cancellation_token: CancellationToken,
        progress_callback: BacktestProgressCallback,
    ) -> BacktestJobResult:
        if not isinstance(claim, BacktestJobClaim):
            raise TypeError("claim must be a BacktestJobClaim")
        validate_operation_controls(cancellation_token, progress_callback)
        if cancellation_token is None or progress_callback is None:  # pragma: no cover
            raise TypeError("worker controls are required")
        request = _request_from_claim(claim)
        result = self._operations[claim.kind](
            request,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )
        expected_type = _RESULT_TYPES[claim.kind]
        if not isinstance(result, expected_type):
            raise TypeError(f"{claim.kind.value} operation returned an invalid result")
        return result


_RESULT_TYPES: dict[BacktestJobKind, type[BacktestJobResult]] = {
    BacktestJobKind.DATA_SYNC: BacktestDataSyncJobResult,
    BacktestJobKind.DATASET_VERIFY: BacktestDatasetVerificationJobResult,
    BacktestJobKind.BACKTEST_RUN: BacktestRunJobResult,
}


def _request_from_claim(claim: BacktestJobClaim) -> BacktestJobRequest:
    request_json = claim.canonical_request_json.get_secret_value()
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        raise ValueError("persisted job request is invalid") from None
    if type(payload) is not dict or payload.get("kind") != claim.kind.value:
        raise ValueError("persisted job request kind does not match its claim")

    if claim.kind in {BacktestJobKind.DATA_SYNC, BacktestJobKind.DATASET_VERIFY}:
        expected_keys = {"kind", "scope"}
        if claim.kind is BacktestJobKind.DATA_SYNC:
            expected_keys.update({"refresh", "allowNetwork"})
        if set(payload) != expected_keys or type(payload.get("scope")) is not dict:
            raise ValueError("persisted data job request has an invalid shape")
        scope_payload = payload["scope"]
        if set(scope_payload) != {
            "symbols",
            "start",
            "end",
            "warmupStart",
            "historicalProfile",
            "adjustmentPolicy",
        }:
            raise ValueError("persisted dataset scope has an invalid shape")
        normalized_scope = {
            "symbols": scope_payload["symbols"],
            "start": scope_payload["start"],
            "end": scope_payload["end"],
            "warmup_start": scope_payload["warmupStart"],
            "historical_profile": scope_payload["historicalProfile"],
            "adjustment_policy": scope_payload["adjustmentPolicy"],
        }
        scope = BacktestDatasetScopeRequest.model_validate_json(canonical_json(normalized_scope))
        if claim.kind is BacktestJobKind.DATA_SYNC:
            return DataSyncJobRequest.model_validate_json(
                canonical_json(
                    {
                        "kind": payload["kind"],
                        "scope": scope.model_dump(mode="json", round_trip=True),
                        "refresh": payload["refresh"],
                        "allow_network": payload["allowNetwork"],
                    }
                )
            )
        return DatasetVerifyJobRequest.model_validate_json(
            canonical_json(
                {
                    "kind": payload["kind"],
                    "scope": scope.model_dump(mode="json", round_trip=True),
                }
            )
        )

    if claim.kind is BacktestJobKind.BACKTEST_RUN:
        if set(payload) != {"kind", "runInput"} or type(payload.get("runInput")) is not dict:
            raise ValueError("persisted run job request has an invalid shape")
        run_input = BacktestRunInput.model_validate_json(canonical_json(payload["runInput"]))
        request = BacktestRunJobRequest(run_input=run_input)
        if request.run_input.run_id != claim.run_id:
            raise ValueError("persisted run input does not match its claim")
        if request.run_input.dataset_hash != claim.dataset_hash:
            raise ValueError("persisted dataset identity does not match its claim")
        return request
    raise AssertionError(f"unhandled job kind: {claim.kind!r}")


BacktestOperationAdapters = BacktestJobOperations

__all__ = [
    "BacktestJobOperation",
    "BacktestJobOperations",
    "BacktestOperationAdapters",
]
