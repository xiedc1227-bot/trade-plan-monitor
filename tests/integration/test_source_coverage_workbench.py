"""A new run rechecks current workbench authority without rewriting old selections."""

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_workbench_selection_context import context, reviewed

from trade_plan_monitor.backtest.composition import _ProductionBacktestService
from trade_plan_monitor.backtest.jobs import BacktestJobKind, BacktestJobReceipt, BacktestJobStatus
from trade_plan_monitor.backtest.jobs.models import LoopInputReference
from trade_plan_monitor.backtest.jobs.repository import BacktestRunSubmissionReservation
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchPlanSelection,
    WorkbenchSelectionCommand,
    freeze_workbench_selection,
)
from trade_plan_monitor.state.repositories import PlanSaveBlockedError
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.web.backtest_schemas import WorkbenchBacktestRunCommand
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode


class _CurrentReader:
    def __init__(self, *, value=None, error=None):
        self.value, self.error, self.calls = value, error, []

    async def get_reviewed_backtest_plan(self, *, version_id):
        self.calls.append(version_id)
        if self.error is not None:
            raise self.error
        return self.value


class _Repository:
    def __init__(self):
        self.calls = []

    def finalize_run_submission(self, request, reservation, *, on_admitted):
        self.calls.append((request, reservation))
        on_admitted("new-workbench-run")
        return BacktestJobReceipt(
            job_id="new-workbench-run", kind=BacktestJobKind.BACKTEST_RUN,
            status=BacktestJobStatus.QUEUED, run_id=request.input_reference.run_id,
            dataset_hash=request.input_reference.dataset_hash, submitted_at=reservation.claimed_at,
        )


class _Service(_ProductionBacktestService):
    """Keep the actual application path and old codecs; replace all physical I/O."""

    def __init__(self, selected, reader):
        self.selected = WorkbenchPlanSelection.model_validate_json(selected.model_dump_json())
        self._plan_snapshot_reader = reader
        self._repository = _Repository()
        self.authorizations, self.freezes, self.operations = [], [], []
        self._coordinator = SimpleNamespace(authorize_new_job=self.authorizations.append)

    async def _selection_operation(self, operation, *args):
        self.operations.append((operation, args))
        if operation == "get":
            assert args == (self.selected.selection_id,)
        else:
            assert operation == "replay"
        return self.selected

    async def _run_sync(self, function, /, *args, **kwargs):
        return function(*args, **kwargs)

    def _freeze_prepared_input(self, prepared, command, reservation):
        self.freezes.append((prepared, command, reservation))
        return LoopInputReference(run_id="a" * 64, input_hash="b" * 64,
                                  dataset_hash="c" * 64, bundle_hash="d" * 64)


def _selected():
    return freeze_workbench_selection(
        reviewed(), context(), selection_id="pre-assurance-selection", confirmed_at=at(28, 10),
    )


def _command(selected):
    return WorkbenchBacktestRunCommand.model_validate({
        "schemaVersion": "workbench-loop-selection-v1", "selectionId": selected.selection_id,
        "selectionHash": selected.manifest_hash, "response": {"mode": "OBSERVE_ONLY"},
        "costs": {
            "commissionRate": "0.0003", "minimumCommissionFen": 500,
            "stampDutyRate": "0.0005", "transferFeeRate": "0.00001",
            "buySlippageFen": 1, "sellSlippageFen": 1,
        },
    })


def _submit(service):
    command = _command(service.selected)
    reservation = BacktestRunSubmissionReservation(
        idempotency_key="a-new-run-intent", intent_hash="e" * 64, claimed_at=at(28, 10),
    )
    return asyncio.run(service._submit_prepared_run(command, reservation, asyncio.Event()))


def _assert_not_frozen(service):
    assert service.freezes == []
    assert service._repository.calls == []
    assert service.authorizations == []


@pytest.mark.parametrize("reader", [None, SimpleNamespace()], ids=["no-reader", "no-capability"])
def test_new_workbench_run_without_current_reader_is_unavailable_before_freeze(reader):
    service = _Service(_selected(), reader)

    with pytest.raises(ApiError) as error:
        _submit(service)

    assert error.value.code == ApiErrorCode.SERVICE_UNAVAILABLE
    _assert_not_frozen(service)


@pytest.mark.parametrize("failure", [
    PlanSaveBlockedError("SOURCE_COVERAGE_REQUIRED"),
    PlanSaveBlockedError("SOURCE_COVERAGE_STALE"),
    SourceCoverageAuthorityError("SOURCE_COVERAGE_REQUIRED"),
    SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE"),
], ids=["missing-proof", "stale-proof", "authority-missing", "authority-stale"])
def test_new_run_rejects_current_reader_coverage_failure_before_any_freeze(failure):
    reader = _CurrentReader(error=failure)
    service = _Service(_selected(), reader)

    with pytest.raises(ApiError) as error:
        _submit(service)

    assert error.value.code == ApiErrorCode.CONFLICT
    assert reader.calls == [str(service.selected.reviewed.reference.plan_version_id)]
    _assert_not_frozen(service)


def test_new_run_rejects_missing_current_plan_before_any_freeze():
    reader = _CurrentReader(value=None)
    service = _Service(_selected(), reader)

    with pytest.raises(ApiError) as error:
        _submit(service)

    assert error.value.code == ApiErrorCode.NOT_FOUND
    assert reader.calls == [str(service.selected.reviewed.reference.plan_version_id)]
    _assert_not_frozen(service)


@pytest.mark.parametrize("updates", [
    {"review_id": UUID("99999999-9999-4999-8999-999999999999")},
    {"review_revision": 2},
])
def test_new_run_rejects_a_different_current_review_reference_even_with_identical_policy(updates):
    selected = _selected()
    current = selected.reviewed.model_copy(update={
        "reference": selected.reviewed.reference.model_copy(update=updates),
    })
    assert current.version == selected.reviewed.version
    assert current.reference != selected.reviewed.reference
    reader = _CurrentReader(value=current)
    service = _Service(selected, reader)

    with pytest.raises(ApiError) as error:
        _submit(service)

    assert error.value.code == ApiErrorCode.CONFLICT
    assert reader.calls == [str(selected.reviewed.reference.plan_version_id)]
    _assert_not_frozen(service)


def test_exact_current_review_allows_new_run_freeze_without_changing_the_legacy_selection():
    selected = _selected()
    original_bytes = selected.model_dump_json()
    reader = _CurrentReader(value=selected.reviewed)
    service = _Service(selected, reader)

    receipt = _submit(service)

    assert reader.calls == [str(selected.reviewed.reference.plan_version_id)]
    assert receipt.kind == BacktestJobKind.BACKTEST_RUN
    assert len(service.freezes) == len(service._repository.calls) == 1
    assert service.freezes[0][0] == selected
    assert service.authorizations == [receipt.job_id]
    assert selected.model_dump_json() == original_bytes
    assert service.selected.model_dump_json() == original_bytes


def test_reading_an_existing_selection_does_not_consult_current_reader():
    selected = _selected()
    reader = _CurrentReader(error=AssertionError("historical selection read acquired authority"))
    service = _Service(selected, reader)

    value = asyncio.run(service.get_plan_selection(selection_id=selected.selection_id))

    assert value.frozen == selected
    assert value.selection_hash == selected.manifest_hash
    assert reader.calls == []
    _assert_not_frozen(service)


def test_same_key_completed_selection_receipt_replay_does_not_consult_current_reader():
    selected = _selected()
    reader = _CurrentReader(error=AssertionError("selection receipt replay acquired authority"))
    service = _Service(selected, reader)
    command = WorkbenchSelectionCommand(
        schema_version="workbench-loop-selection-v1", plan=selected.reviewed.reference,
        context=selected.context,
    )

    value = asyncio.run(service.create_plan_selection(
        command=command, context=SimpleNamespace(idempotency_key="old-selection-intent"),
    ))

    assert value.frozen == selected
    assert service.operations[0][0] == "replay"
    assert reader.calls == []
    _assert_not_frozen(service)
