"""SIMULATED bounded diagnostic persistence; no external provider calls."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from tests.unit.test_current_plan_extraction_security import current_output as _valid_output
from tests.unit.test_current_plan_extraction_security import extract as _extract

import trade_plan_monitor.web.ai_diagnostics as diagnostics


def test_simulated_sidecar_keeps_only_the_last_bounded_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "MAX_DIAGNOSTIC_RECORDS", 3)
    monkeypatch.setattr(diagnostics, "MAX_DIAGNOSTIC_FILE_BYTES", 4_096)
    database = tmp_path / "isolated/monitor.sqlite3"
    sidecar = diagnostics.diagnostic_path_for_database(database)
    diagnostics.ensure_diagnostic_sink(sidecar)
    assert sidecar.read_bytes() == b""
    result = _extract(_valid_output())
    ids = [uuid4() for _ in range(5)]
    for operation_id in ids:
        diagnostics.append_extraction_diagnostic(
            sidecar,
            result=result.model_copy(update={"request_id": operation_id}),
            configured_model="SIMULATED-v4",
            completed_at=datetime(2026, 9, 14, 10, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    records = [json.loads(line) for line in sidecar.read_text("utf-8").splitlines()]
    assert [record["operationId"] for record in records] == [str(item) for item in ids[-3:]]
    assert sidecar.stat().st_size <= diagnostics.MAX_DIAGNOSTIC_FILE_BYTES
    assert all(record["reason"] == "NONE" for record in records)
