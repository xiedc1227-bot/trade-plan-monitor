"""Contract tests for strict, exact backtest-only API input values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from trade_plan_monitor.web.backtest_schemas import (
    MAX_SAFE_INTEGER,
    BacktestAssumptionsView,
    BacktestAuthoritativeDecisionView,
    BacktestDataHealthView,
    BacktestDatasetCoverageView,
    BacktestDatasetFiltersView,
    BacktestDatasetPage,
    BacktestDatasetScopeInput,
    BacktestDatasetScopeView,
    BacktestDatasetVerificationCommand,
    BacktestDatasetVerificationJobResultView,
    BacktestDatasetView,
    BacktestDataSyncCommand,
    BacktestDataSyncJobResultView,
    BacktestDecisionEvidenceView,
    BacktestDecisionView,
    BacktestDetailPage,
    BacktestEquityPointView,
    BacktestEquitySeries,
    BacktestEvidenceFactView,
    BacktestExecutionConfigInput,
    BacktestExecutionConfigView,
    BacktestExecutionOutcomeView,
    BacktestFeeBreakdownView,
    BacktestFillPage,
    BacktestFillView,
    BacktestFormulaVersionsView,
    BacktestInitialLotInput,
    BacktestJobFiltersView,
    BacktestJobPage,
    BacktestJobProgressView,
    BacktestJobReceipt,
    BacktestJobView,
    BacktestMetricsView,
    BacktestNextStepView,
    BacktestPositionSummaryView,
    BacktestResultAvailabilityView,
    BacktestRunCommand,
    BacktestRunJobResultView,
    BacktestRunPage,
    BacktestRunSummaryView,
    BacktestRunView,
    BacktestSignalView,
    DecimalText,
    FenText,
    ShanghaiDatetime,
)
from trade_plan_monitor.web.routers.dashboard import (
    AuthoritativeDecisionView,
    DataHealthView,
    DecisionEvidenceView,
    EvidenceFactView,
    NextStepView,
    PositionSummaryView,
)

_UUID = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"
_HASH = "a" * 64
_RUN_HASH = "b" * 64
_REPORT_HASH = "c" * 64
_TIME = "2026-08-28T09:30:00+08:00"
_FIXED_TIME = "2026-08-28T09:30:00.000000+08:00"


def _scope_payload() -> dict[str, object]:
    return {
        "symbols": ["000001.SZ", "600000.SH"],
        "start": "2024-01-02",
        "end": "2026-08-28",
        "warmupStart": "2023-01-02",
        "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }


def _execution_payload() -> dict[str, object]:
    return {
        "commissionRate": "0.0003",
        "minimumCommissionFen": 500,
        "stampDutyRate": "0.0005",
        "transferFeeRate": "0.00001",
        "buySlippageBps": "1.25",
        "sellSlippageBps": "2",
    }


def _lot_payload(
    lot_key: str,
    *,
    bucket: str = "CORE",
    acquired: str = "2023-12-29",
    quantity: int = 100,
    cost_basis_fen: int = 10_000,
) -> dict[str, object]:
    return {
        "lotKey": lot_key,
        "bucket": bucket,
        "acquiredTradeDate": acquired,
        "quantity": quantity,
        "costBasisFen": cost_basis_fen,
    }


def _run_payload(*, lots: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "planVersionId": _UUID,
        "datasetHash": _HASH,
        "initialCashFen": 1_000_000,
        "initialLots": [] if lots is None else lots,
        "executionConfig": _execution_payload(),
        "eventRiskAssumption": "NO_EVENT_RISK",
    }


def test_primitive_fen_text_is_exact_and_rejects_noncanonical_values() -> None:
    adapter = TypeAdapter(FenText)

    assert adapter.validate_python("0") == "0"
    assert adapter.validate_python("-12345678901234567890") == "-12345678901234567890"
    for value in (0, 1.0, "+1", "01", "-0", "1.0", " 1", "1 "):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


def test_primitive_decimal_text_is_canonical_without_binary_float_conversion() -> None:
    adapter = TypeAdapter(DecimalText)

    value = adapter.validate_python("1.23")
    assert value == Decimal("1.23")
    assert adapter.dump_python(value, mode="json") == "1.23"
    for invalid in (
        0.1,
        "001.2300",
        "1.0",
        "-0",
        "1e-3",
        "+1",
        "NaN",
        "Infinity",
        " 1",
        "",
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


@pytest.mark.parametrize("exact_type", (FenText, DecimalText), ids=("fen", "decimal"))
def test_primitive_exact_text_types_have_explicit_safe_length_bounds(
    exact_type: object,
) -> None:
    maximum_length = 4_096

    adapter = TypeAdapter(exact_type)
    assert adapter.json_schema().get("maxLength") == maximum_length
    assert adapter.validate_python("9" * maximum_length)
    with pytest.raises(ValidationError):
        adapter.validate_python("9" * (maximum_length + 1))


def test_primitive_safe_integer_and_identity_inputs_fail_closed() -> None:
    payload = _run_payload()
    assert BacktestRunCommand.model_validate(payload).initial_cash_fen == 1_000_000

    for invalid in (True, 1.0, "1", MAX_SAFE_INTEGER + 1, 0):
        with pytest.raises(ValidationError):
            BacktestRunCommand.model_validate(payload | {"initialCashFen": invalid})
    for field, invalid in (
        ("planVersionId", "not-a-uuid"),
        ("datasetHash", "A" * 64),
        ("datasetHash", "a" * 63),
    ):
        with pytest.raises(ValidationError):
            BacktestRunCommand.model_validate(payload | {field: invalid})


def test_primitive_uuid_normalizes_canonical_text_and_rejects_loose_forms() -> None:
    payload = _run_payload() | {"planVersionId": _UUID.upper()}

    command = BacktestRunCommand.model_validate(payload)

    assert command.plan_version_id == UUID(_UUID)
    assert command.canonical_payload()["planVersionId"] == _UUID
    for invalid in (_UUID.replace("-", ""), "{" + _UUID + "}"):
        with pytest.raises(ValidationError):
            BacktestRunCommand.model_validate(_run_payload() | {"planVersionId": invalid})


def test_shanghai_datetime_accepts_zero_to_six_digits_and_emits_fixed_six() -> None:
    adapter = TypeAdapter(ShanghaiDatetime)

    for raw, expected in (
        ("2026-08-28T09:30:00+08:00", "2026-08-28T09:30:00.000000+08:00"),
        ("2026-08-28T09:30:00.1+08:00", "2026-08-28T09:30:00.100000+08:00"),
        ("2026-08-28T09:30:00.123456+08:00", "2026-08-28T09:30:00.123456+08:00"),
    ):
        parsed = adapter.validate_python(raw)
        assert adapter.dump_python(parsed, mode="json") == expected


@pytest.mark.parametrize(
    "raw",
    (
        "2026-08-28T09:30:00Z",
        "2026-08-28T09:30:00",
        "2026-08-28T01:30:00+00:00",
        "2026-08-28T09:30:00+08:30",
        "2026-08-28T09:30:00.1234567+08:00",
        "2026-02-30T09:30:00+08:00",
    ),
)
def test_shanghai_datetime_rejects_alternate_or_invalid_forms(raw: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ShanghaiDatetime).validate_python(raw)


def test_shanghai_datetime_rejects_historical_non_eight_hour_zone() -> None:
    with pytest.raises(ValidationError, match="historical offset"):
        TypeAdapter(ShanghaiDatetime).validate_python("1800-01-01T00:00:00+08:00")


def test_input_dataset_scope_is_closed_canonical_and_bounded() -> None:
    scope = BacktestDatasetScopeInput.model_validate(
        _scope_payload() | {"symbols": ["600000.SH", "000001.SZ"]}
    )

    assert scope.symbols == ("000001.SZ", "600000.SH")
    assert scope.canonical_payload() == _scope_payload()
    assert scope.model_dump(mode="json") == _scope_payload()
    with pytest.raises(ValidationError):
        BacktestDatasetScopeInput.model_validate(_scope_payload() | {"unexpected": True})
    with pytest.raises(ValidationError):
        BacktestDatasetScopeInput.model_validate(_scope_payload() | {"warmup_start": "2023-01-02"})


def test_input_dataset_scope_uses_an_injected_authoritative_today() -> None:
    scope = BacktestDatasetScopeInput.model_validate(_scope_payload())

    assert scope.validate_authoritative_today(today=date(2026, 8, 29)) is scope
    with pytest.raises(ValueError, match="today"):
        scope.validate_authoritative_today(today=date(2026, 8, 28))
    with pytest.raises(TypeError):
        scope.validate_authoritative_today(today="2026-08-29")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "update",
    (
        {"symbols": []},
        {"symbols": ["000001.SZ", "000001.SZ"]},
        {"symbols": ["430001.BJ"]},
        {"symbols": ["AAPL"]},
        {"start": "2026-01-02", "end": "2025-01-02"},
        {"start": "2020-01-01", "end": "2025-01-02"},
        {"warmupStart": "2026-01-03"},
        {"start": "2025-01-02", "warmupStart": "2023-01-01"},
        {"historicalProfile": "UNVERIFIED"},
        {"adjustmentPolicy": "QFQ"},
    ),
)
def test_input_dataset_scope_rejects_invalid_ranges_and_labels(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BacktestDatasetScopeInput.model_validate(_scope_payload() | update)


def test_input_dataset_commands_are_strict_and_explicit_about_network() -> None:
    scope = _scope_payload()
    sync = BacktestDataSyncCommand.model_validate(
        {"scope": scope, "refresh": False, "allowNetwork": True}
    )
    verification = BacktestDatasetVerificationCommand.model_validate({"scope": scope})

    assert sync.allow_network is True
    assert verification.scope == sync.scope
    for invalid in (False, 1, "true"):
        with pytest.raises(ValidationError):
            BacktestDataSyncCommand.model_validate(
                {"scope": scope, "refresh": False, "allowNetwork": invalid}
            )


def test_input_execution_assumptions_canonicalize_decimal_text() -> None:
    config = BacktestExecutionConfigInput.model_validate(_execution_payload())

    assert config.commission_rate == Decimal("0.0003")
    assert config.model_dump(mode="json") == {
        "commissionRate": "0.0003",
        "minimumCommissionFen": 500,
        "stampDutyRate": "0.0005",
        "transferFeeRate": "0.00001",
        "buySlippageBps": "1.25",
        "sellSlippageBps": "2",
    }
    for field, invalid in (
        ("commissionRate", 0.0003),
        ("commissionRate", "1.0001"),
        ("stampDutyRate", "-0.1"),
        ("buySlippageBps", "10000"),
        ("minimumCommissionFen", MAX_SAFE_INTEGER + 1),
    ):
        with pytest.raises(ValidationError):
            BacktestExecutionConfigInput.model_validate(_execution_payload() | {field: invalid})


def test_input_initial_lots_are_sorted_and_checked_before_canonical_use() -> None:
    command = BacktestRunCommand.model_validate(
        _run_payload(
            lots=[
                _lot_payload("tactical", bucket="TACTICAL", acquired="2023-12-28"),
                _lot_payload("core-b", acquired="2023-12-29"),
                _lot_payload("core-a", acquired="2023-12-28"),
            ]
        )
    )

    assert tuple(lot.lot_key for lot in command.initial_lots) == (
        "core-a",
        "core-b",
        "tactical",
    )
    assert [lot["lotKey"] for lot in command.canonical_payload()["initialLots"]] == [
        "core-a",
        "core-b",
        "tactical",
    ]
    assert command.plan_version_id.hex == "4c623c8cca264cd88cb208cd5e61be93"


@pytest.mark.parametrize(
    "update",
    (
        {"lotKey": ""},
        {"lotKey": "bad key"},
        {"bucket": "OTHER"},
        {"acquiredTradeDate": "2026-02-30"},
        {"quantity": 0},
        {"quantity": 101},
        {"quantity": True},
        {"costBasisFen": 0},
        {"costBasisFen": MAX_SAFE_INTEGER + 1},
        {"unexpected": "value"},
    ),
)
def test_input_initial_lot_rejects_invalid_shape(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BacktestInitialLotInput.model_validate(_lot_payload("lot-1") | update)


def test_input_run_rejects_duplicates_count_and_unsafe_total_value() -> None:
    for lots, cash in (
        ([_lot_payload("duplicate"), _lot_payload("duplicate")], 1_000_000),
        ([_lot_payload(f"lot-{index:03d}") for index in range(201)], 1_000_000),
        ([_lot_payload("expensive", cost_basis_fen=MAX_SAFE_INTEGER)], 1),
    ):
        with pytest.raises(ValidationError):
            BacktestRunCommand.model_validate(_run_payload(lots=lots) | {"initialCashFen": cash})


def test_input_run_accepts_exactly_two_hundred_initial_lots() -> None:
    lots = [_lot_payload(f"lot-{index:03d}", cost_basis_fen=1) for index in reversed(range(200))]

    command = BacktestRunCommand.model_validate(_run_payload(lots=lots))

    assert len(command.initial_lots) == 200
    assert command.initial_lots[0].lot_key == "lot-000"
    assert command.initial_lots[-1].lot_key == "lot-199"


def test_input_run_requires_every_exact_field_and_stays_frozen() -> None:
    payload = _run_payload()
    for field in payload:
        with pytest.raises(ValidationError):
            BacktestRunCommand.model_validate(
                {key: value for key, value in payload.items() if key != field}
            )

    command = BacktestRunCommand.model_validate(payload)
    with pytest.raises(ValidationError):
        command.initial_cash_fen = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        command.model_copy(update={"initialCashFen": 0})


def test_input_json_schema_keeps_exact_decimals_string_only() -> None:
    schema = BacktestRunCommand.model_json_schema()
    execution_schema = schema["$defs"]["BacktestExecutionConfigInput"]

    assert "initialLots" in schema["required"]
    assert schema["additionalProperties"] is False
    assert BacktestDataSyncCommand.model_json_schema()["properties"]["allowNetwork"] == {
        "const": True,
        "title": "Allownetwork",
        "type": "boolean",
    }
    for field in (
        "commissionRate",
        "stampDutyRate",
        "transferFeeRate",
        "buySlippageBps",
        "sellSlippageBps",
    ):
        assert execution_schema["properties"][field]["type"] == "string"


def test_input_run_enforces_authoritative_date_and_position_caps() -> None:
    command = BacktestRunCommand.model_validate(
        _run_payload(
            lots=[
                _lot_payload("core", quantity=200),
                _lot_payload("tactical", bucket="TACTICAL", quantity=100),
            ]
        )
    )

    assert (
        command.validate_initial_lot_limits(
            dataset_start=date(2024, 1, 2),
            core_target_qty=200,
            tactical_target_qty=100,
            max_qty=300,
        )
        is command
    )
    for kwargs, message in (
        ({"dataset_start": date(2023, 12, 28)}, "dataset start"),
        ({"core_target_qty": 100}, "CORE"),
        ({"tactical_target_qty": 0}, "TACTICAL"),
        ({"max_qty": 200}, "maximum"),
    ):
        limits = {
            "dataset_start": date(2024, 1, 2),
            "core_target_qty": 200,
            "tactical_target_qty": 100,
            "max_qty": 300,
        }
        limits.update(kwargs)
        with pytest.raises(ValueError, match=message):
            command.validate_initial_lot_limits(**limits)


def _coverage_payload(*, blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "symbolCount": 2,
        "tradingDayCount": 5,
        "calendarRowCount": 7,
        "minuteDayCount": 10,
        "minuteBarCount": 2_400,
        "dailyLimitRowCount": 10,
        "dailyBarRowCount": 10,
        "blockers": [] if blockers is None else blockers,
    }


def _dataset_view_payload(
    *,
    dataset_hash: str = _HASH,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    return {
        "datasetHash": dataset_hash,
        "schemaVersion": "backtest-dataset-v1",
        "scope": _scope_payload(),
        "coverage": _coverage_payload(blockers=blockers),
        "createdAt": _TIME,
        "verifiedAt": "2026-08-28T09:31:00.123+08:00",
    }


def _progress_payload(
    *,
    phase: str = "QUEUED",
    completed_units: int = 0,
    total_units: int | None = None,
    unit: str = "ITEMS",
) -> dict[str, object]:
    return {
        "phase": phase,
        "completedUnits": completed_units,
        "totalUnits": total_units,
        "unit": unit,
        "updatedAt": _TIME,
    }


def _run_result_payload(*, run_id: str = _RUN_HASH) -> dict[str, object]:
    return {
        "kind": "BACKTEST_RUN",
        "runId": run_id,
        "reportHash": _REPORT_HASH,
        "reused": False,
    }


def _job_view_payload() -> dict[str, object]:
    return {
        "jobId": "job-001",
        "kind": "BACKTEST_RUN",
        "status": "COMPLETED",
        "requestHash": _HASH,
        "runId": _RUN_HASH,
        "datasetHash": _HASH,
        "progress": _progress_payload(
            phase="TERMINAL",
            completed_units=10,
            total_units=10,
            unit="EVENTS",
        ),
        "result": _run_result_payload(),
        "attempt": 1,
        "revision": 4,
        "createdAt": "2026-08-28T09:29:00+08:00",
        "startedAt": _TIME,
        "updatedAt": "2026-08-28T09:31:00+08:00",
        "finishedAt": "2026-08-28T09:31:00+08:00",
        "cancelRequestedAt": None,
        "reused": False,
        "errorCode": None,
        "errorMessage": None,
    }


def test_job_receipt_is_closed_and_canonicalizes_shanghai_time() -> None:
    receipt = BacktestJobReceipt.model_validate(
        {
            "jobId": "job-001",
            "kind": "BACKTEST_RUN",
            "status": "QUEUED",
            "runId": _RUN_HASH,
            "datasetHash": _HASH,
            "attempt": 0,
            "revision": 0,
            "reused": False,
            "submittedAt": _TIME,
        }
    )

    assert receipt.model_dump(mode="json")["submittedAt"] == _FIXED_TIME
    assert set(receipt.model_dump(mode="json")) == {
        "jobId",
        "kind",
        "status",
        "runId",
        "datasetHash",
        "attempt",
        "revision",
        "reused",
        "submittedAt",
    }
    with pytest.raises(ValidationError):
        BacktestJobReceipt.model_validate(receipt.canonical_payload() | {"claimToken": "secret"})


@pytest.mark.parametrize(
    "update",
    (
        {"kind": "DATA_SYNC"},
        {"runId": None},
        {"datasetHash": None},
        {"attempt": 1},
        {"revision": MAX_SAFE_INTEGER + 1},
        {"submittedAt": "2026-08-28T01:30:00Z"},
    ),
)
def test_job_receipt_rejects_contradictory_or_unsafe_values(
    update: dict[str, object],
) -> None:
    payload = {
        "jobId": "job-reused",
        "kind": "BACKTEST_RUN",
        "status": "COMPLETED",
        "runId": _RUN_HASH,
        "datasetHash": _HASH,
        "attempt": 0,
        "revision": 0,
        "reused": True,
        "submittedAt": _TIME,
    }
    with pytest.raises(ValidationError):
        BacktestJobReceipt.model_validate(payload | update)


def test_job_progress_is_bounded_and_uses_fixed_six_digit_time() -> None:
    progress = BacktestJobProgressView.model_validate(
        _progress_payload(completed_units=3, total_units=10)
    )

    assert progress.model_dump(mode="json")["updatedAt"] == _FIXED_TIME
    for update in (
        {"completedUnits": 11, "totalUnits": 10},
        {"completedUnits": -1},
        {"completedUnits": MAX_SAFE_INTEGER + 1},
        {"unit": "BYTES"},
        {"phase": "UNKNOWN"},
        {"updatedAt": "2026-08-28T09:30:00.1234567+08:00"},
    ):
        with pytest.raises(ValidationError):
            BacktestJobProgressView.model_validate(_progress_payload() | update)


def test_job_result_union_accepts_only_exact_discriminator_variants() -> None:
    sync = BacktestDataSyncJobResultView.model_validate(
        {
            "kind": "DATA_SYNC",
            "calendarRows": 5,
            "minuteDays": 10,
            "dailyLimitRows": 10,
            "dailyBarRows": 10,
            "networkCalls": 2,
        }
    )
    verification = BacktestDatasetVerificationJobResultView.model_validate(
        {
            "kind": "DATASET_VERIFY",
            "ready": True,
            "datasetHash": _HASH,
            "coverage": _coverage_payload(),
            "blockers": [],
        }
    )
    run = BacktestRunJobResultView.model_validate(_run_result_payload())

    assert (sync.kind, verification.kind, run.kind) == (
        "DATA_SYNC",
        "DATASET_VERIFY",
        "BACKTEST_RUN",
    )
    for model, payload in (
        (BacktestDataSyncJobResultView, sync.canonical_payload() | {"databasePath": "x"}),
        (
            BacktestDatasetVerificationJobResultView,
            verification.canonical_payload() | {"providerPayload": {}},
        ),
        (BacktestRunJobResultView, run.canonical_payload() | {"kind": "DATA_SYNC"}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize(
    "update",
    (
        {"ready": True, "datasetHash": None},
        {"ready": False, "datasetHash": _HASH},
        {"ready": False, "datasetHash": None, "blockers": []},
        {"ready": True, "datasetHash": _HASH, "blockers": ["MISSING_DAILY_BAR"]},
        {
            "ready": False,
            "datasetHash": None,
            "blockers": ["MISSING_DAILY_BAR"],
            "coverage": _coverage_payload(),
        },
    ),
)
def test_dataset_verification_job_result_rejects_readiness_conflicts(
    update: dict[str, object],
) -> None:
    payload = {
        "kind": "DATASET_VERIFY",
        "ready": True,
        "datasetHash": _HASH,
        "coverage": _coverage_payload(),
        "blockers": [],
    }
    with pytest.raises(ValidationError):
        BacktestDatasetVerificationJobResultView.model_validate(payload | update)


def test_job_view_serializes_one_valid_completed_run_union() -> None:
    view = BacktestJobView.model_validate(_job_view_payload())
    dumped = view.model_dump(mode="json")

    assert dumped["kind"] == dumped["result"]["kind"] == "BACKTEST_RUN"
    assert dumped["runId"] == dumped["result"]["runId"] == _RUN_HASH
    assert dumped["createdAt"] == "2026-08-28T09:29:00.000000+08:00"
    assert dumped["finishedAt"] == "2026-08-28T09:31:00.000000+08:00"
    assert "claimToken" not in BacktestJobView.model_fields
    assert "canonicalRequestJson" not in BacktestJobView.model_fields


@pytest.mark.parametrize(
    "update",
    (
        {"result": None},
        {"status": "RUNNING", "finishedAt": None},
        {"progress": _progress_payload(phase="FINALIZING")},
        {"finishedAt": None},
        {"kind": "DATA_SYNC"},
        {"runId": None},
        {"datasetHash": None},
        {"result": _run_result_payload(run_id="d" * 64)},
        {"reused": True},
        {"errorCode": "FAILED", "errorMessage": "sanitized"},
        {"createdAt": "2026-08-28T01:29:00Z"},
        {"rawDiagnostics": {"trace": "internal"}},
    ),
)
def test_job_view_rejects_every_contradictory_completed_projection(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BacktestJobView.model_validate(_job_view_payload() | update)


@pytest.mark.parametrize("status", ("FAILED", "CANCELLED"))
def test_job_terminal_failure_or_cancellation_requires_sanitized_error(
    status: str,
) -> None:
    payload = _job_view_payload() | {
        "kind": "DATA_SYNC",
        "status": status,
        "runId": None,
        "datasetHash": None,
        "result": None,
        "attempt": 1 if status == "FAILED" else 0,
        "startedAt": _TIME if status == "FAILED" else None,
        "cancelRequestedAt": _TIME if status == "CANCELLED" else None,
        "errorCode": "JOB_CANCELLED" if status == "CANCELLED" else "JOB_FAILED",
        "errorMessage": "The job was cancelled." if status == "CANCELLED" else "The job failed.",
    }
    view = BacktestJobView.model_validate(payload)
    assert view.status == status

    other_status_message = "The job failed." if status == "CANCELLED" else "The job was cancelled."
    with pytest.raises(ValidationError, match="stable public status message"):
        BacktestJobView.model_validate(payload | {"errorMessage": other_status_message})

    if status == "CANCELLED":
        with pytest.raises(ValidationError):
            BacktestJobView.model_validate(payload | {"startedAt": _TIME})

    for update in (
        {"errorCode": None},
        {"errorMessage": None},
        {"errorCode": "bad-code"},
        {"errorMessage": "line one\nline two"},
        {"errorMessage": "x" * 513},
    ):
        with pytest.raises(ValidationError):
            BacktestJobView.model_validate(payload | update)


@pytest.mark.parametrize(
    "unsafe_message",
    (
        "TUSHARE_TOKEN=synthetic-value",
        "raw provider payload",
        r"database path C:\Users\sample\trade.db",
        "report path /var/lib/trade/report.json",
        "provider URL https://example.invalid/error",
        "Authorization Bearer synthetic-value",
        "access key abcdefghijklmnop",
        "client key abcdefghijklmnop",
        "database path private.db",
        "opaque value " + "a" * 32,
    ),
)
def test_job_view_rejects_credentials_provider_text_and_local_paths(
    unsafe_message: str,
) -> None:
    payload = _job_view_payload() | {
        "kind": "DATA_SYNC",
        "status": "FAILED",
        "runId": None,
        "datasetHash": None,
        "result": None,
        "attempt": 1,
        "startedAt": _TIME,
        "cancelRequestedAt": None,
        "errorCode": "JOB_FAILED",
        "errorMessage": unsafe_message,
    }

    with pytest.raises(ValidationError, match="sanitized public text"):
        BacktestJobView.model_validate(payload)


def test_job_view_rejects_nonterminal_and_cancellation_state_conflicts() -> None:
    queued = _job_view_payload() | {
        "kind": "DATA_SYNC",
        "status": "QUEUED",
        "runId": None,
        "datasetHash": None,
        "progress": _progress_payload(),
        "result": None,
        "attempt": 0,
        "startedAt": None,
        "finishedAt": None,
        "errorCode": None,
        "errorMessage": None,
    }
    assert BacktestJobView.model_validate(queued).status == "QUEUED"

    for update in (
        {"attempt": 1},
        {"startedAt": _TIME},
        {"finishedAt": _TIME},
        {"progress": _progress_payload(phase="TERMINAL")},
        {"cancelRequestedAt": _TIME},
        {"reused": True},
    ):
        with pytest.raises(ValidationError):
            BacktestJobView.model_validate(queued | update)

    running = _job_view_payload() | {
        "status": "RUNNING",
        "progress": _progress_payload(phase="REPLAYING"),
        "result": None,
        "finishedAt": None,
    }
    assert BacktestJobView.model_validate(running).status == "RUNNING"
    with pytest.raises(ValidationError):
        BacktestJobView.model_validate(running | {"progress": _progress_payload(phase="QUEUED")})


@pytest.mark.parametrize(
    "update",
    (
        {"updatedAt": "2026-08-28T09:28:00+08:00"},
        {"startedAt": "2026-08-28T09:28:00+08:00"},
        {"finishedAt": "2026-08-28T09:30:30+08:00"},
        {
            "progress": _progress_payload(
                phase="TERMINAL", completed_units=10, total_units=10, unit="EVENTS"
            )
            | {"updatedAt": "2026-08-28T09:28:00+08:00"}
        },
    ),
)
def test_job_view_rejects_contradictory_lifecycle_chronology(
    update: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="chronology"):
        BacktestJobView.model_validate(_job_view_payload() | update)


def test_job_view_rejects_cancel_request_before_claim_start() -> None:
    payload = _job_view_payload() | {
        "status": "CANCEL_REQUESTED",
        "progress": _progress_payload(phase="REPLAYING"),
        "result": None,
        "finishedAt": None,
        "cancelRequestedAt": "2026-08-28T09:29:30+08:00",
    }

    with pytest.raises(ValidationError, match="chronology"):
        BacktestJobView.model_validate(payload)


def test_dataset_scope_and_coverage_views_are_bounded_and_closed() -> None:
    scope = BacktestDatasetScopeView.model_validate(_scope_payload())
    coverage = BacktestDatasetCoverageView.model_validate(
        _coverage_payload(blockers=["MISSING_DAILY_BAR", "MISSING_MINUTE_DAY"])
    )

    assert scope.symbols == ("000001.SZ", "600000.SH")
    assert coverage.blockers == ("MISSING_DAILY_BAR", "MISSING_MINUTE_DAY")
    for payload in (
        _coverage_payload(blockers=["MISSING", "MISSING"]),
        _coverage_payload(blockers=["lower_case"]),
        _coverage_payload(blockers=["X" * 129]),
        _coverage_payload(blockers=[f"BLOCKER_{index:03d}" for index in range(101)]),
        _coverage_payload() | {"minuteBarCount": MAX_SAFE_INTEGER + 1},
        _coverage_payload() | {"membershipRows": []},
    ):
        with pytest.raises(ValidationError):
            BacktestDatasetCoverageView.model_validate(payload)


def test_dataset_view_exposes_only_bounded_projection_and_fixed_times() -> None:
    view = BacktestDatasetView.model_validate(_dataset_view_payload())
    dumped = view.model_dump(mode="json")

    assert dumped["createdAt"] == _FIXED_TIME
    assert dumped["verifiedAt"] == "2026-08-28T09:31:00.123000+08:00"
    assert set(dumped) == {
        "datasetHash",
        "schemaVersion",
        "scope",
        "coverage",
        "createdAt",
        "verifiedAt",
    }
    for forbidden in ("membershipRows", "artifacts", "providerPayload", "databasePath"):
        with pytest.raises(ValidationError):
            BacktestDatasetView.model_validate(_dataset_view_payload() | {forbidden: []})


@pytest.mark.parametrize("contradiction", ("symbol_count", "timestamp"))
def test_dataset_view_rejects_scope_count_and_timestamp_contradictions(
    contradiction: str,
) -> None:
    payload = _dataset_view_payload()
    expected_message = "symbolCount"
    if contradiction == "symbol_count":
        payload["coverage"] = payload["coverage"] | {"symbolCount": 1}
    else:
        payload |= {
            "createdAt": "2026-08-28T09:32:00+08:00",
            "verifiedAt": "2026-08-28T09:31:00+08:00",
        }
        expected_message = "verifiedAt"

    with pytest.raises(ValidationError, match=expected_message):
        BacktestDatasetView.model_validate(payload)


def test_dataset_page_is_bounded_and_has_closed_normalized_filters() -> None:
    items = [_dataset_view_payload(dataset_hash=f"{index:064x}") for index in reversed(range(100))]
    filters = {
        "symbol": "000001.SZ",
        "startOnOrAfter": "2024-01-01",
        "endOnOrBefore": "2026-08-28",
        "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        "adjustmentPolicy": "NONE",
    }
    page = BacktestDatasetPage.model_validate(
        {
            "filters": filters,
            "items": items,
            "limit": 100,
            "nextCursor": "next.token",
            "hasMore": True,
            "highWatermark": "high.water",
        }
    )

    assert len(page.items) == 100
    assert page.filters == BacktestDatasetFiltersView.model_validate(filters)
    assert page.model_dump(mode="json")["items"][0]["datasetHash"] == f"{99:064x}"


@pytest.mark.parametrize(
    "update",
    (
        {"items": [_dataset_view_payload()] * 101},
        {"limit": 0},
        {"limit": 101},
        {"items": [_dataset_view_payload()] * 2, "limit": 1},
        {"items": [_dataset_view_payload()] * 2},
        {"hasMore": True, "nextCursor": None},
        {"hasMore": False, "nextCursor": "next.token"},
        {"nextCursor": "not-a-signed-token"},
        {"highWatermark": ""},
        {"membershipRevision": 1},
        {
            "filters": {
                "symbol": "600001.SH",
                "startOnOrAfter": None,
                "endOnOrBefore": None,
                "historicalProfile": None,
                "adjustmentPolicy": None,
            }
        },
    ),
)
def test_dataset_page_rejects_unbounded_or_contradictory_projection(
    update: dict[str, object],
) -> None:
    payload = {
        "filters": {
            "symbol": None,
            "startOnOrAfter": None,
            "endOnOrBefore": None,
            "historicalProfile": None,
            "adjustmentPolicy": None,
        },
        "items": [_dataset_view_payload()],
        "limit": 20,
        "nextCursor": None,
        "hasMore": False,
        "highWatermark": "high.water",
    }
    with pytest.raises(ValidationError):
        BacktestDatasetPage.model_validate(payload | update)


def _result_availability_payload() -> dict[str, object]:
    return {
        "decisionDetails": "AVAILABLE",
        "signalDetails": "AVAILABLE",
        "executionOutcomeDetails": "EXPIRED",
        "equitySeries": "AVAILABLE",
    }


def _metrics_view_payload() -> dict[str, object]:
    return {
        "initialCashFen": "1000000",
        "initialEquityFen": "1000000",
        "finalCashFen": "899998",
        "finalEquityFen": "1019998",
        "totalReturn": "0.019998",
        "maximumDrawdown": "0.01",
        "tradeCount": 1,
        "winningSellCount": 0,
        "winRate": "0",
        "turnoverFen": "100000",
        "totalCostFen": "2",
        "realizedPnlFen": "0",
        "unrealizedPnlFen": "20000",
        "blockedCount": 0,
        "skippedCount": 1,
    }


def _execution_config_view_payload() -> dict[str, object]:
    return {
        "commissionRate": "0.0003",
        "minimumCommissionFen": "500",
        "stampDutyRate": "0.0005",
        "transferFeeRate": "0.00001",
        "buySlippageBps": "2.5",
        "sellSlippageBps": "3",
    }


def _run_summary_payload(*, run_id: str = _RUN_HASH) -> dict[str, object]:
    return {
        "runId": run_id,
        "reportHash": _REPORT_HASH,
        "planVersionId": _UUID,
        "planHash": _HASH,
        "datasetHash": "d" * 64,
        "symbol": "000001.SZ",
        "status": "COMPLETED",
        "eventStart": "2024-01-02",
        "eventEnd": "2024-01-05",
        "completedAt": _TIME,
        "pinned": False,
        "revision": 2,
        "fillCount": 1,
        "metrics": _metrics_view_payload(),
        "availability": _result_availability_payload(),
    }


def _run_view_payload() -> dict[str, object]:
    return _run_summary_payload() | {
        "initialCashFen": "1000000",
        "coverage": {
            "eventStart": "2024-01-02",
            "eventEnd": "2024-01-05",
            "tradingDayCount": 4,
            "decisionCount": 4,
            "signalCount": 1,
            "orderCount": 1,
            "fillCount": 1,
            "outcomeCount": 1,
            "equityPointCount": 4,
        },
        "assumptions": {
            "eventRiskAssumption": "NO_EVENT_RISK",
            "executionConfig": _execution_config_view_payload(),
            "executionConfigHash": "e" * 64,
            "priceAdjustmentPolicy": "NONE",
            "historicalProfile": "TUSHARE_STK_MINS_241_END_V1",
        },
        "formulaVersions": {
            "runFormulaVersion": "backtest-run-v1",
            "reportSchemaVersion": "backtest-report-v1",
            "executionFormulaVersion": "execution-model-v1",
            "metricFormulaVersion": "backtest-metrics-v1",
        },
        "limitations": ["DAILY_EQUITY_DRAWDOWN_SAMPLING", "NO_INTRADAY_EVENT_RISK"],
    }


def _fees_view_payload() -> dict[str, object]:
    return {
        "commissionFen": "1",
        "stampDutyFen": "0",
        "transferFeeFen": "1",
        "totalFen": "2",
    }


def _fill_view_payload() -> dict[str, object]:
    return {
        "fillId": "fill-001",
        "orderId": "order-001",
        "signalId": "signal-001",
        "runId": _RUN_HASH,
        "planHash": _HASH,
        "datasetHash": "d" * 64,
        "resultHash": _REPORT_HASH,
        "configHash": "e" * 64,
        "sourceBarId": "bar-001",
        "side": "BUY",
        "symbol": "000001.SZ",
        "bucket": "CORE",
        "targetLotId": None,
        "filledAt": _TIME,
        "requestedQuantity": 100,
        "quantity": 100,
        "priceFen": "1000",
        "notionalFen": "100000",
        "fees": _fees_view_payload(),
        "cashDeltaFen": "-100002",
        "costBasisReleasedFen": "0",
        "realizedPnlFen": None,
    }


def _decision_payload() -> dict[str, object]:
    return {
        "symbol": "000001.SZ",
        "resultHash": _REPORT_HASH,
        "planId": "sample-plan",
        "planVersion": 3,
        "planHash": _HASH,
        "evaluatedAt": _TIME,
        "marketDataAt": "2026-08-28T09:29:00+08:00",
        "dataAgeSeconds": 60,
        "priceFen": "1234",
        "zone": "LOW_BUY",
        "signalType": "BUY_CORE_READY",
        "position": {
            "coreQuantity": 1000,
            "tacticalQuantity": 0,
            "totalQuantity": 1000,
            "sellableCoreQuantity": 1000,
            "sellableTacticalQuantity": 0,
        },
        "episodeStatus": "ALERTED",
        "episodeLowFen": "1220",
        "riskStatus": "CLEAR",
        "riskBreachTradeDate": None,
        "dataHealth": {
            "status": "LIVE",
            "latestBarEnd": "2026-08-28T09:29:00+08:00",
            "dataAgeSeconds": 60,
            "requiredDataComplete": True,
            "fresh": True,
        },
        "evidence": [
            {
                "kind": "RULE",
                "code": "BUY_CONDITION",
                "outcome": "SATISFIED",
                "facts": [{"key": "price_fen", "value": 1234, "unit": "FEN"}],
                "missingInputs": [],
                "children": [],
            }
        ],
        "nextStep": {
            "code": "RECORD_CONFIRMED_FILL",
            "notBefore": None,
            "requiredInputs": [],
        },
    }


def _decision_view_payload() -> dict[str, object]:
    return {
        "kind": "DECISION",
        "detailId": "decision-001",
        "runId": _RUN_HASH,
        "eventAt": _TIME,
        "resultHash": _REPORT_HASH,
        "decision": _decision_payload(),
    }


def _signal_view_payload() -> dict[str, object]:
    return {
        "kind": "SIGNAL",
        "detailId": "signal-detail-001",
        "runId": _RUN_HASH,
        "eventAt": _TIME,
        "signalId": "signal-001",
        "resultHash": _REPORT_HASH,
        "signalType": "BUY_CORE_READY",
        "symbol": "000001.SZ",
        "quantity": 100,
        "bucket": "CORE",
        "targetLotId": None,
        "causeId": "decision-001",
    }


def _outcome_view_payload() -> dict[str, object]:
    return {
        "kind": "EXECUTION_OUTCOME",
        "detailId": "outcome-detail-001",
        "runId": _RUN_HASH,
        "eventAt": _TIME,
        "outcomeId": "outcome-001",
        "signalId": "signal-001",
        "orderId": "order-001",
        "sourceBarId": "bar-001",
        "status": "FILLED",
        "reason": None,
        "fillId": "fill-001",
    }


def _equity_point_payload(*, snapshot_id: str = "snapshot-001") -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "runId": _RUN_HASH,
        "symbol": "000001.SZ",
        "markedAt": _TIME,
        "markPriceFen": "1200",
        "cashFen": "899998",
        "positionQuantity": 100,
        "marketValueFen": "120000",
        "costBasisFen": "100002",
        "realizedPnlFen": "0",
        "unrealizedPnlFen": "19998",
        "totalCostFen": "2",
        "equityFen": "1019998",
    }


def test_run_summary_and_view_are_completed_only_closed_contracts() -> None:
    summary = BacktestRunSummaryView.model_validate(_run_summary_payload())
    view = BacktestRunView.model_validate(_run_view_payload())

    assert summary.status == view.status == "COMPLETED"
    assert summary.model_dump(mode="json")["completedAt"] == _FIXED_TIME
    assert view.model_dump(mode="json")["initialCashFen"] == "1000000"
    assert set(BacktestRunView.model_fields) == set(BacktestRunSummaryView.model_fields) | {
        "initial_cash_fen",
        "coverage",
        "assumptions",
        "formula_versions",
        "limitations",
    }
    for update in (
        {"status": "FAILED"},
        {"status": "STAGED"},
        {"eventEnd": "2024-01-01"},
        {"metrics": _metrics_view_payload() | {"initialCashFen": 1000000}},
        {"providerPayload": {}},
    ):
        with pytest.raises(ValidationError):
            BacktestRunSummaryView.model_validate(_run_summary_payload() | update)


@pytest.mark.parametrize(
    "update",
    (
        {"initialCashFen": "999999"},
        {"coverage": _run_view_payload()["coverage"] | {"fillCount": 2}},
        {"coverage": _run_view_payload()["coverage"] | {"decisionCount": 0}},
        {"availability": _result_availability_payload() | {"signalDetails": "NOT_RECORDED"}},
        {"coverage": _run_view_payload()["coverage"] | {"outcomeCount": 0}},
        {"limitations": ["NO_INTRADAY_EVENT_RISK", "NO_INTRADAY_EVENT_RISK"]},
        {"limitations": ["z-last", "a-first"]},
        {"limitations": ["X" * 129]},
        {"assumptions": _run_view_payload()["assumptions"] | {"executionConfigHash": "x"}},
    ),
)
def test_run_view_rejects_cross_projection_conflicts(update: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BacktestRunView.model_validate(_run_view_payload() | update)


def test_run_view_rejects_an_item_larger_than_32_kib() -> None:
    maximum_fen = "9" * 4_096
    oversized_metrics = _metrics_view_payload() | {
        "initialCashFen": maximum_fen,
        "initialEquityFen": maximum_fen,
        "finalCashFen": maximum_fen,
        "finalEquityFen": maximum_fen,
        "totalReturn": "0",
        "turnoverFen": maximum_fen,
        "totalCostFen": maximum_fen,
        "realizedPnlFen": maximum_fen,
        "unrealizedPnlFen": maximum_fen,
    }
    with pytest.raises(ValidationError, match="32 KiB"):
        BacktestRunView.model_validate(
            _run_view_payload() | {"initialCashFen": maximum_fen, "metrics": oversized_metrics}
        )


def test_metrics_assumptions_and_formula_versions_are_exact_value_views() -> None:
    metrics = BacktestMetricsView.model_validate(_metrics_view_payload())
    config = BacktestExecutionConfigView.model_validate(_execution_config_view_payload())
    assumptions = BacktestAssumptionsView.model_validate(_run_view_payload()["assumptions"])
    versions = BacktestFormulaVersionsView.model_validate(_run_view_payload()["formulaVersions"])

    assert metrics.total_return == Decimal("0.019998")
    assert config.commission_rate == Decimal("0.0003")
    assert assumptions.event_risk_assumption == "NO_EVENT_RISK"
    assert versions.report_schema_version == "backtest-report-v1"
    for update in (
        {"totalReturn": "0.02"},
        {"maximumDrawdown": "1.01"},
        {"winRate": "-0.01"},
        {"totalReturn": "-1.01"},
        {"winningSellCount": 2},
        {"turnoverFen": "-1"},
    ):
        with pytest.raises(ValidationError):
            BacktestMetricsView.model_validate(_metrics_view_payload() | update)


def test_fill_view_uses_fen_text_and_rejects_arithmetic_or_secret_fields() -> None:
    fill = BacktestFillView.model_validate(_fill_view_payload())
    fees = BacktestFeeBreakdownView.model_validate(_fees_view_payload())
    dumped = fill.model_dump(mode="json")

    assert dumped["priceFen"] == "1000"
    assert dumped["filledAt"] == _FIXED_TIME
    assert fees.total_fen == "2"
    for update in (
        {"priceFen": 1000},
        {"notionalFen": "99999"},
        {"cashDeltaFen": "-1"},
        {"costBasisReleasedFen": "1"},
        {"realizedPnlFen": "0"},
        {"providerPayload": {"token": "secret"}},
    ):
        with pytest.raises(ValidationError):
            BacktestFillView.model_validate(_fill_view_payload() | update)


def test_backtest_decision_preserves_live_field_parity_but_serializes_fen_text() -> None:
    decision = BacktestAuthoritativeDecisionView.model_validate(_decision_payload())
    detail = BacktestDecisionView.model_validate(_decision_view_payload())
    dumped = detail.model_dump(mode="json")

    assert decision.price_fen == "1234"
    assert set(BacktestAuthoritativeDecisionView.model_fields) == set(
        AuthoritativeDecisionView.model_fields
    )
    for backtest_model, live_model in (
        (BacktestEvidenceFactView, EvidenceFactView),
        (BacktestDecisionEvidenceView, DecisionEvidenceView),
        (BacktestPositionSummaryView, PositionSummaryView),
        (BacktestDataHealthView, DataHealthView),
        (BacktestNextStepView, NextStepView),
    ):
        assert set(backtest_model.model_fields) == set(live_model.model_fields)
    assert dumped["decision"]["priceFen"] == "1234"
    assert dumped["decision"]["episodeLowFen"] == "1220"
    assert dumped["eventAt"] == _FIXED_TIME
    assert len(detail.model_dump_json().encode("utf-8")) <= 32 * 1024
    with pytest.raises(ValidationError):
        BacktestAuthoritativeDecisionView.model_validate(_decision_payload() | {"priceFen": 1234})
    for update in (
        {"resultHash": "f" * 64},
        {"eventAt": "2026-08-28T09:31:00+08:00"},
    ):
        with pytest.raises(ValidationError):
            BacktestDecisionView.model_validate(_decision_view_payload() | update)


def test_decision_item_rejects_oversized_evidence_without_truncation() -> None:
    facts = [
        {"key": f"fact_{index:03d}", "value": "X" * 64, "unit": "CODE"} for index in range(512)
    ]
    evidence = _decision_payload()["evidence"][0] | {"facts": facts}
    decision = _decision_payload() | {"evidence": [evidence]}
    with pytest.raises(ValidationError, match="32 KiB"):
        BacktestDecisionView.model_validate(_decision_view_payload() | {"decision": decision})


def test_signal_and_outcome_detail_discriminators_reject_contradictory_shapes() -> None:
    signal = BacktestSignalView.model_validate(_signal_view_payload())
    outcome = BacktestExecutionOutcomeView.model_validate(_outcome_view_payload())
    assert (signal.kind, outcome.kind) == ("SIGNAL", "EXECUTION_OUTCOME")

    for model, payload in (
        (BacktestSignalView, _signal_view_payload() | {"kind": "DIAGNOSTIC"}),
        (BacktestSignalView, _signal_view_payload() | {"targetLotId": "lot-001"}),
        (BacktestExecutionOutcomeView, _outcome_view_payload() | {"fillId": None}),
        (
            BacktestExecutionOutcomeView,
            _outcome_view_payload() | {"status": "UNFILLED", "reason": None},
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_equity_point_and_availability_series_are_bounded_and_consistent() -> None:
    point = BacktestEquityPointView.model_validate(_equity_point_payload())
    available = BacktestEquitySeries.model_validate(
        {"availability": "AVAILABLE", "items": [_equity_point_payload()]}
    )
    unavailable = BacktestEquitySeries.model_validate({"availability": "EXPIRED", "items": []})
    assert point.equity_fen == "1019998"
    assert len(available.items) == 1
    assert unavailable.items == ()

    for payload in (
        {"availability": "EXPIRED", "items": [_equity_point_payload()]},
        {"availability": "AVAILABLE", "items": []},
        {"availability": "UNKNOWN", "items": []},
        {"availability": "AVAILABLE", "items": [_equity_point_payload()] * 2001},
        {
            "availability": "AVAILABLE",
            "items": [
                _equity_point_payload(snapshot_id="snapshot-002"),
                _equity_point_payload(snapshot_id="snapshot-001"),
            ],
        },
    ):
        with pytest.raises(ValidationError):
            BacktestEquitySeries.model_validate(payload)


def test_equity_series_rejects_a_complete_response_at_or_above_four_mib() -> None:
    mark_price_fen = "9" * 1_000
    market_value_fen = str(int(mark_price_fen) * 100)
    items = [
        _equity_point_payload(snapshot_id=f"snapshot-{index:04d}")
        | {
            "markPriceFen": mark_price_fen,
            "cashFen": "0",
            "positionQuantity": 100,
            "marketValueFen": market_value_fen,
            "costBasisFen": "0",
            "realizedPnlFen": "0",
            "unrealizedPnlFen": market_value_fen,
            "totalCostFen": "0",
            "equityFen": market_value_fen,
        }
        for index in range(2_000)
    ]

    with pytest.raises(ValidationError, match="4 MiB"):
        BacktestEquitySeries.model_validate({"availability": "AVAILABLE", "items": items})


def test_result_availability_is_closed_and_exact() -> None:
    availability = BacktestResultAvailabilityView.model_validate(_result_availability_payload())
    assert set(availability.model_dump(mode="json")) == {
        "decisionDetails",
        "signalDetails",
        "executionOutcomeDetails",
        "equitySeries",
    }
    with pytest.raises(ValidationError):
        BacktestResultAvailabilityView.model_validate(
            _result_availability_payload() | {"debugTrace": "AVAILABLE"}
        )


def test_job_filters_normalize_repeated_enums_as_sorted_unique_sets() -> None:
    filters = BacktestJobFiltersView.model_validate(
        {
            "kind": ["DATA_SYNC", "BACKTEST_RUN", "DATA_SYNC"],
            "status": ["FAILED", "COMPLETED", "FAILED"],
            "runId": None,
            "datasetHash": None,
            "createdFrom": None,
            "createdTo": None,
        }
    )

    assert filters.kind == ("BACKTEST_RUN", "DATA_SYNC")
    assert filters.status == ("COMPLETED", "FAILED")


def test_job_run_and_fill_pages_are_closed_bounded_and_ordered() -> None:
    job_page = BacktestJobPage.model_validate(
        {
            "filters": {
                "kind": ["BACKTEST_RUN"],
                "status": ["COMPLETED"],
                "runId": _RUN_HASH,
                "datasetHash": _HASH,
                "createdFrom": None,
                "createdTo": None,
            },
            "items": [_job_view_payload()],
            "limit": 20,
            "nextCursor": None,
            "hasMore": False,
            "highWatermark": "high.water",
        }
    )
    run_page = BacktestRunPage.model_validate(
        {
            "filters": {
                "symbol": "000001.SZ",
                "planVersionId": _UUID,
                "datasetHash": "d" * 64,
                "completedFrom": None,
                "completedTo": None,
                "pinned": False,
            },
            "items": [_run_summary_payload()],
            "limit": 20,
            "nextCursor": None,
            "hasMore": False,
            "highWatermark": "high.water",
        }
    )
    fill_page = BacktestFillPage.model_validate(
        {
            "filters": {},
            "items": [_fill_view_payload()],
            "limit": 20,
            "nextCursor": None,
            "hasMore": False,
            "highWatermark": "high.water",
        }
    )
    assert len(job_page.items) == len(run_page.items) == len(fill_page.items) == 1
    assert len(run_page.model_dump_json().encode("utf-8")) < 4 * 1024 * 1024
    for page_model, page in (
        (BacktestJobPage, job_page),
        (BacktestRunPage, run_page),
        (BacktestFillPage, fill_page),
    ):
        item = page.model_dump(mode="json")["items"][0]
        with pytest.raises(ValidationError):
            page_model.model_validate(page.model_dump(mode="json") | {"items": [item, item]})
    with pytest.raises(ValidationError):
        BacktestJobPage.model_validate(
            job_page.model_dump(mode="json")
            | {"filters": job_page.filters.canonical_payload() | {"status": "RUNNING"}}
        )
    with pytest.raises(ValidationError):
        BacktestRunPage.model_validate(
            run_page.model_dump(mode="json")
            | {"filters": run_page.filters.canonical_payload() | {"pinned": True}}
        )


def test_detail_page_binds_kind_availability_and_item_discriminator() -> None:
    page = BacktestDetailPage.model_validate(
        {
            "kind": "SIGNAL",
            "availability": "AVAILABLE",
            "filters": {"kind": "SIGNAL"},
            "items": [_signal_view_payload()],
            "limit": 20,
            "nextCursor": None,
            "hasMore": False,
            "highWatermark": "high.water",
        }
    )
    assert page.items[0].kind == "SIGNAL"
    with pytest.raises(ValidationError):
        BacktestDetailPage.model_validate(
            page.model_dump(mode="json")
            | {"items": [_signal_view_payload(), _signal_view_payload()]}
        )

    base = page.model_dump(mode="json")
    for update in (
        {"kind": "DECISION"},
        {"filters": {"kind": "DECISION"}},
        {"items": [_outcome_view_payload()]},
        {"items": []},
        {"availability": "EXPIRED"},
        {"kind": "DIAGNOSTIC", "filters": {"kind": "DIAGNOSTIC"}, "items": []},
    ):
        with pytest.raises(ValidationError):
            BacktestDetailPage.model_validate(base | update)

    expired = BacktestDetailPage.model_validate(
        base
        | {
            "availability": "EXPIRED",
            "items": [],
            "nextCursor": None,
            "hasMore": False,
        }
    )
    assert expired.items == ()
