"""Contract tests for strict, exact backtest-only API input values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from trade_plan_monitor.web.backtest_schemas import (
    MAX_SAFE_INTEGER,
    BacktestDatasetScopeInput,
    BacktestDatasetVerificationCommand,
    BacktestDataSyncCommand,
    BacktestExecutionConfigInput,
    BacktestInitialLotInput,
    BacktestRunCommand,
    DecimalText,
    FenText,
    ShanghaiDatetime,
)

_UUID = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"
_HASH = "a" * 64


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
