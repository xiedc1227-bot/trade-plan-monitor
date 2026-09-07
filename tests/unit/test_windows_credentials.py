"""Windows Credential Manager adapter contracts."""

from __future__ import annotations

import pytest

from trade_plan_monitor.windows_credentials import (
    WindowsCredentialError,
    read_windows_generic_credential,
    write_windows_generic_credential,
)


def test_read_returns_an_independent_mutable_copy() -> None:
    native_blob = bytearray(b"secret-value")

    result = read_windows_generic_credential(
        "trade-plan-monitor/tushare-live",
        native_reader=lambda _target: native_blob,
    )

    assert result == bytearray(b"secret-value")
    assert result is not native_blob
    assert native_blob == bytearray(len(native_blob))


@pytest.mark.parametrize(
    "target",
    ("", " leading", "trailing ", "contains\x00nul", "x" * 257),
)
def test_credential_target_is_strictly_validated(target: str) -> None:
    with pytest.raises(ValueError, match="credential target"):
        read_windows_generic_credential(target, native_reader=lambda _target: bytearray(b"x"))


def test_empty_credential_is_rejected_and_zeroed() -> None:
    native_blob = bytearray()

    with pytest.raises(WindowsCredentialError, match="credential is empty"):
        read_windows_generic_credential(
            "trade-plan-monitor/tushare-live",
            native_reader=lambda _target: native_blob,
        )


def test_write_copies_then_zeroes_the_temporary_native_buffer() -> None:
    observed: list[bytes] = []
    secret = bytearray(b"secret-value")

    write_windows_generic_credential(
        "trade-plan-monitor/tushare-live",
        secret,
        native_writer=lambda _target, value: observed.append(bytes(value)),
    )

    assert observed == [b"secret-value"]
    assert secret == bytearray(b"secret-value")
