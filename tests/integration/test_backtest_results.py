from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.composition import create_backtest_composition
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.jobs import BacktestJobRepository
from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import (
    EquitySnapshot,
    ExecutionConfig,
    ExecutionOutcome,
    ExecutionSignal,
    ExecutionStatus,
    UnfilledReason,
)
from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    ResultConflictError,
    backtest_detail_set_hash,
    backtest_fill_set_hash,
)
from trade_plan_monitor.backtest.run_input import BacktestInitialLotInput, BacktestRunInput
from trade_plan_monitor.decision.models import ActionableSignalType
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_backtest_storage_domains_reject_aliases_and_live_tables(tmp_path) -> None:
    with pytest.raises(ValueError, match="another storage domain"):
        create_backtest_composition(
            config_path=tmp_path / "app.yaml",
            plan_snapshot_reader=None,
            cursor_key_path=tmp_path / "cursor.key",
            market_database=tmp_path / "same.sqlite3",
            results_database=tmp_path / "same.sqlite3",
        )

    market_path = tmp_path / "market.sqlite3"
    BacktestMarketStore(market_path)
    with pytest.raises(ValueError, match="another storage domain"):
        BacktestResultStore(market_path)

    results_path = tmp_path / "results.sqlite3"
    BacktestResultStore(results_path)
    with pytest.raises(ValueError, match="another storage domain"):
        BacktestMarketStore(results_path)

    live_path = tmp_path / "live.sqlite3"
    with closing(sqlite3.connect(live_path)) as connection:
        connection.execute("CREATE TABLE monitor_sequence (id INTEGER PRIMARY KEY)")
        connection.commit()
    with pytest.raises(ValueError, match="another storage domain"):
        BacktestMarketStore(live_path)
    with pytest.raises(ValueError, match="another storage domain"):
        BacktestResultStore(live_path)
    live_path.unlink()


@pytest.mark.parametrize("table_name", ["plan_activation_state", "plan_version_review"])
def test_backtest_stores_reject_each_plan_web_state_table(
    tmp_path: Path,
    table_name: str,
) -> None:
    live_path = tmp_path / f"{table_name}.sqlite3"
    with closing(sqlite3.connect(live_path)) as connection:
        connection.execute(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(ValueError, match="another storage domain"):
        BacktestMarketStore(live_path)
    with pytest.raises(ValueError, match="another storage domain"):
        BacktestResultStore(live_path)


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _summary(
    label: str,
    *,
    status: BacktestRunStatus = BacktestRunStatus.COMPLETED,
    completed_at: datetime = datetime(2026, 8, 25, 4, tzinfo=UTC),
    pinned: bool = False,
) -> BacktestRunSummary:
    return BacktestRunSummary(
        run_id=_hash(f"run:{label}"),
        plan_sha256=_hash("plan"),
        dataset_hash=_hash("dataset"),
        status=status,
        completed_at=completed_at,
        event_start=date(2026, 8, 20),
        event_end=date(2026, 8, 24),
        symbols=("600000.SH",),
        coverage={"minute_rows": 960, "gap_count": 0},
        assumptions={
            "corporate_actions": "NOT_MODELED",
            "event_risk": "NO_EVENT",
            "reportHash": _hash(f"report:{label}"),
        },
        formula_versions={
            "indicator": "ta-v1",
            "execution": "execution-model-v1",
        },
        final_metrics={"total_return": "0.0125", "total_cost_fen": 501},
        blockers=(),
        pinned=pinned,
    )


def _canonical_run_input() -> BacktestRunInput:
    plan = load_plan_yaml(_PLAN_PATH.read_text(encoding="utf-8"))
    start = date(2026, 8, 20)
    manifest = DatasetManifest(
        dataset_hash=_hash("canonical-input-dataset"),
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=start,
            end=date(2026, 8, 24),
            warmup_start=date(2025, 8, 20),
            historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        ),
        items=(),
    )
    return BacktestRunInput.create(
        plan=plan,
        manifest=manifest,
        initial_cash_fen=10_000_000,
        initial_lots=(
            BacktestInitialLotInput(
                lot_key="existing-tactical",
                bucket="TACTICAL",
                acquired_trade_date=start,
                quantity=100,
                cost_basis_fen=100_000,
            ),
        ),
        execution_config=ExecutionConfig(
            commission_rate=Decimal("0.0003"),
            minimum_commission_fen=500,
            stamp_duty_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            buy_slippage_bps=Decimal("2"),
            sell_slippage_bps=Decimal("2"),
        ),
        manual_event_risk=False,
    )


def test_result_v2_completed_only_persists_canonical_input_and_shanghai_domains(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "result-v2.sqlite3")
    run_input = _canonical_run_input()
    summary = _summary(
        "result-v2",
        completed_at=datetime(2026, 8, 24, 15, 30, tzinfo=_SHANGHAI),
    ).model_copy(
        update={
            "run_id": run_input.run_id,
            "plan_sha256": run_input.plan_sha256,
            "dataset_hash": run_input.dataset_hash,
            "event_start": run_input.start,
            "event_end": run_input.end,
            "symbols": (run_input.plan_snapshot.symbol,),
            "assumptions": {
                **_summary("result-v2").assumptions,
                "executionConfigHash": run_input.execution_config.config_hash,
                "manualEventRisk": run_input.manual_event_risk,
            },
            "formula_versions": {
                "execution": run_input.execution_config.formula_version,
                "indicator": run_input.indicator_formula_version,
                "runner": run_input.run_formula_version,
            },
        }
    )
    fill_payload = _fill_payload(summary)
    fill = BacktestFillRecord.from_value(fill_payload, version="v2")
    detail = _detail(summary, BacktestDetailKind.DECISION)

    assert store.record_run_input(run_input) is True
    assert store.record_run_input(run_input) is False
    assert store.record_verified_run(summary, run_input=run_input) is True
    assert store.record_fills(summary.run_id, (fill_payload,)) == 1
    assert store.record_details(summary.run_id, (detail,)) == 1
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert store.mark_run_materialized(
        summary.run_id,
        expected_fill_count=1,
        expected_detail_count=1,
        expected_report_hash=report_hash,
        expected_fill_set_hash=backtest_fill_set_hash((fill,), version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash((detail,), version="v2"),
    )
    assert store.get_run_input(run_input.run_id) == run_input
    verified = store.get_verified_run(run_input.run_id)
    assert verified == summary
    assert verified is not None and verified.completed_at.utcoffset() == timedelta(hours=8)
    assert store.list_fills(run_input.run_id)[0].filled_at.utcoffset() == timedelta(hours=8)
    assert store.list_details(run_input.run_id)[0].event_at.utcoffset() == timedelta(hours=8)

    with closing(sqlite3.connect(store.database_path)) as connection:
        run_row = connection.execute(
            "SELECT summary_domain, completed_at, publication_fill_set_domain, "
            "publication_detail_set_domain, stage_revision, summary_json "
            "FROM backtest_run WHERE run_id = ?",
            (run_input.run_id,),
        ).fetchone()
        fill_row = connection.execute(
            "SELECT content_domain, filled_at, payload_json FROM backtest_fill WHERE run_id = ?",
            (run_input.run_id,),
        ).fetchone()
        detail_row = connection.execute(
            "SELECT content_domain, event_at, payload_json, typeof(payload_json) "
            "FROM backtest_detail WHERE run_id = ?",
            (run_input.run_id,),
        ).fetchone()
        assert connection.execute("SELECT COUNT(*) FROM backtest_plan_snapshot").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM backtest_run_input").fetchone() == (1,)
    assert run_row[:4] == (
        "backtest-run-summary-v2",
        "2026-08-24T15:30:00.000000+08:00",
        "backtest-fill-set-v2",
        "backtest-detail-set-v2",
    )
    assert run_row[4] == 3
    assert fill_row[:2] == ("backtest-fill-record-v2", "2026-08-24T15:01:00.000000+08:00")
    assert detail_row[:2] == (
        "backtest-detail-record-v2",
        "2026-08-24T15:00:00.000000+08:00",
    )
    assert detail_row[3] == "blob"
    assert isinstance(detail_row[2], bytes)
    assert len(detail_row[2]) < len(detail.model_dump_json().encode("utf-8"))
    assert all(
        "+08:00" in str(row[-1]) and "+00:00" not in str(row[-1]) for row in (run_row, fill_row)
    )


def test_verified_input_staging_failure_and_fourteen_day_maintenance_leave_no_orphans(
    tmp_path: Path,
) -> None:
    database = tmp_path / "verified-input-orphans.sqlite3"
    repository = BacktestJobRepository(database)
    store = BacktestResultStore(database)
    run_input = _canonical_run_input()
    summary = _summary(
        "verified-input-orphans",
        completed_at=datetime(2026, 8, 24, 15, 30, tzinfo=_SHANGHAI),
    ).model_copy(
        update={
            "run_id": run_input.run_id,
            "plan_sha256": run_input.plan_sha256,
            "dataset_hash": run_input.dataset_hash,
            "event_start": run_input.start,
            "event_end": run_input.end,
            "symbols": (run_input.plan_snapshot.symbol,),
            "assumptions": {
                "executionConfigHash": run_input.execution_config.config_hash,
                "manualEventRisk": run_input.manual_event_risk,
                "reportHash": _hash("verified-input-orphans-report"),
            },
            "formula_versions": {
                "execution": run_input.execution_config.formula_version,
                "indicator": run_input.indicator_formula_version,
                "runner": run_input.run_formula_version,
            },
        }
    )

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_verified_summary_stage
            BEFORE INSERT ON backtest_run
            BEGIN SELECT RAISE(ABORT, 'injected summary stage failure'); END
            """
        )
        connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected summary stage failure"):
        store.record_verified_run(summary, run_input=run_input)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM backtest_run_input").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM backtest_plan_snapshot").fetchone() == (0,)
        connection.execute("DROP TRIGGER fail_verified_summary_stage")
        connection.commit()

    assert store.record_run_input(run_input) is True
    BacktestJobMaintenance(
        repository=repository,
        results=store,
    ).prune(
        as_of=datetime.now(_SHANGHAI) + timedelta(days=15),
        batch_size=1_000,
    )

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM backtest_run_input").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM backtest_plan_snapshot").fetchone() == (0,)


def test_legacy_v1_completed_row_is_compatibility_only_and_terminal_writes_fail(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "legacy-v1.sqlite3")
    summary = _summary("legacy-v1")
    _materialize(store, summary)

    assert store.get_run(summary.run_id) == summary
    assert store.get_verified_run(summary.run_id) is None
    assert store.get_run_input(summary.run_id) is None
    with pytest.raises(ValueError, match="completed-only"):
        store.record_run(_summary("failed", status=BacktestRunStatus.FAILED))
    with pytest.raises(ValueError, match="completed-only"):
        store.record_run(_summary("cancelled", status=BacktestRunStatus.CANCELLED))

    with closing(sqlite3.connect(store.database_path)) as connection:
        row = connection.execute(
            "SELECT summary_domain, completed_at FROM backtest_run WHERE run_id = ?",
            (summary.run_id,),
        ).fetchone()
    assert row == ("backtest-run-summary-v1", "2026-08-25T04:00:00.000000+00:00")


def _fill(
    summary: BacktestRunSummary,
    label: str = "fill",
    *,
    version: str = "v1",
) -> BacktestFillRecord:
    return BacktestFillRecord.from_value(_fill_payload(summary, label), version=version)


def _fill_payload(summary: BacktestRunSummary, label: str = "fill") -> dict[str, object]:
    return {
        "fill_id": _hash(f"{summary.run_id}:{label}"),
        "run_id": summary.run_id,
        "filled_at": datetime(2026, 8, 24, 7, 1, tzinfo=UTC),
        "symbol": "600000.SH",
        "quantity": 100,
        "price_fen": 1_012,
        "fees": {"commission_fen": 500, "transfer_fee_fen": 1},
    }


def _detail(
    summary: BacktestRunSummary,
    kind: BacktestDetailKind,
    label: str = "detail",
) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=_hash(f"{summary.run_id}:{kind}:{label}"),
        run_id=summary.run_id,
        kind=kind,
        event_at=datetime(2026, 8, 24, 7, tzinfo=UTC),
        payload={"identity": label, "result_hash": _hash(label)},
    )


def _materialize(
    store: BacktestResultStore,
    summary: BacktestRunSummary,
    *,
    fills: tuple[BacktestFillRecord, ...] = (),
    details: tuple[BacktestDetailRecord, ...] = (),
) -> None:
    assert store.record_run(summary) is True
    assert store.record_fills(summary.run_id, fills) == len(fills)
    assert store.record_details(summary.run_id, details) == len(details)
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert (
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=len(fills),
            expected_detail_count=len(details),
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash(fills),
            expected_detail_set_hash=backtest_detail_set_hash(details),
        )
        is True
    )


def test_result_store_is_wal_isolated_canonical_and_conflict_closed(tmp_path: Path) -> None:
    path = tmp_path / "backtest-results.sqlite3"
    store = BacktestResultStore(path)
    summary = _summary("stable")
    fill = _fill(summary)
    detail = _detail(summary, BacktestDetailKind.DECISION)

    assert store.record_run(summary) is True
    assert store.record_run(summary) is False
    assert store.record_fills(summary.run_id, (fill,)) == 1
    assert store.record_fills(summary.run_id, (fill,)) == 0
    assert store.record_details(summary.run_id, (detail,)) == 1
    assert store.record_details(summary.run_id, (detail,)) == 0

    assert store.get_run(summary.run_id) is None
    assert store.list_fills(summary.run_id) == ()
    assert store.list_details(summary.run_id) == ()
    assert store.statistics().model_dump() == {
        "run_count": 0,
        "fill_count": 0,
        "detail_count": 0,
    }
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert (
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=1,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash((fill,)),
            expected_detail_set_hash=backtest_detail_set_hash((detail,)),
        )
        is True
    )
    assert (
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=1,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash((fill,)),
            expected_detail_set_hash=backtest_detail_set_hash((detail,)),
        )
        is False
    )
    with pytest.raises(ResultConflictError, match="publication counts"):
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=0,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash((fill,)),
            expected_detail_set_hash=backtest_detail_set_hash((detail,)),
        )
    with pytest.raises(ResultConflictError, match="fill publication"):
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=1,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash="f" * 64,
            expected_detail_set_hash=backtest_detail_set_hash((detail,)),
        )
    with pytest.raises(ResultConflictError, match="detail publication"):
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=1,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash((fill,)),
            expected_detail_set_hash="f" * 64,
        )

    assert store.get_run(summary.run_id) == summary
    assert store.list_fills(summary.run_id) == (fill,)
    assert store.list_details(summary.run_id) == (detail,)
    assert store.statistics().model_dump() == {
        "run_count": 1,
        "fill_count": 1,
        "detail_count": 1,
    }

    conflicting = summary.model_copy(update={"final_metrics": {"total_return": "9"}})
    with pytest.raises(ResultConflictError, match="run_id"):
        store.record_run(conflicting)
    conflicting_fill = fill.model_copy(update={"payload": {**fill.payload, "quantity": 200}})
    with pytest.raises(ResultConflictError, match="fill_id"):
        store.record_fills(summary.run_id, (conflicting_fill,))
    conflicting_detail = detail.model_copy(update={"payload": {"identity": "changed"}})
    with pytest.raises(ResultConflictError, match="detail_id"):
        store.record_details(summary.run_id, (conflicting_detail,))
    with pytest.raises(ResultConflictError, match="cannot append fills"):
        store.record_fills(summary.run_id, (_fill(summary, "late"),))
    with pytest.raises(ResultConflictError, match="cannot append details"):
        store.record_details(
            summary.run_id,
            (_detail(summary, BacktestDetailKind.SIGNAL, "late"),),
        )

    reopened = BacktestResultStore(path)
    assert reopened.get_run(summary.run_id) == summary
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name"
            )
        }
        run_json = str(
            connection.execute(
                "SELECT summary_json FROM backtest_run WHERE run_id = ?", (summary.run_id,)
            ).fetchone()[0]
        )

    assert tables == {
        "backtest_detail",
        "backtest_fill",
        "backtest_plan_snapshot",
        "backtest_review_event",
        "backtest_run",
        "backtest_run_input",
    }
    assert all("minute" not in table and "market" not in table for table in tables)
    assert {
        "ix_backtest_run_retention",
        "ix_backtest_fill_run",
        "ix_backtest_detail_retention",
        "ix_backtest_detail_run_event",
    } <= indexes
    assert " " not in run_json
    assert run_json.index('"assumptions"') < run_json.index('"blockers"')


def test_result_store_creates_fill_verification_index_without_temporary_sort(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fill-verification-index.sqlite3"
    BacktestResultStore(path)
    with sqlite3.connect(path) as connection:
        index_columns = tuple(
            str(row[2])
            for row in connection.execute('PRAGMA index_xinfo("ix_backtest_fill_verification")')
            if int(row[5]) == 1
        )
        query_plan = tuple(
            str(row[3])
            for row in connection.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json
                FROM backtest_fill
                WHERE run_id = ?
                ORDER BY fill_id
                """,
                ("a" * 64,),
            )
        )

    assert index_columns == ("run_id", "fill_id")
    assert any("ix_backtest_fill_verification" in step for step in query_plan)
    assert all("TEMP B-TREE" not in step for step in query_plan)


def test_materialization_cannot_be_bypassed_or_publish_tampered_staged_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "backtest-results.sqlite3"
    store = BacktestResultStore(path)
    with pytest.raises(ValueError, match="direct materialization"):
        store.record_run(_summary("direct-bypass"), materialized=True)

    tampered_summary = _summary("tampered-summary-sql")
    assert store.record_run(tampered_summary) is True
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backtest_run SET plan_sha256 = ? WHERE run_id = ?",
            ("f" * 64, tampered_summary.run_id),
        )
        connection.commit()
    tampered_report_hash = tampered_summary.assumptions["reportHash"]
    assert isinstance(tampered_report_hash, str)
    with pytest.raises(RuntimeError, match="summary SQL identity"):
        store.mark_run_materialized(
            tampered_summary.run_id,
            expected_fill_count=0,
            expected_detail_count=0,
            expected_report_hash=tampered_report_hash,
            expected_fill_set_hash=backtest_fill_set_hash(()),
            expected_detail_set_hash=backtest_detail_set_hash(()),
        )
    assert store.get_run(tampered_summary.run_id) is None

    summary = _summary("tampered-stage")
    detail = _detail(summary, BacktestDetailKind.DECISION)
    assert store.record_run(summary) is True
    assert store.record_details(summary.run_id, (detail,)) == 1
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backtest_detail SET event_at = ? WHERE detail_id = ?",
            (datetime(2026, 8, 24, 8, tzinfo=UTC).isoformat(), detail.detail_id),
        )
        connection.commit()

    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    with pytest.raises(ResultConflictError, match="identity is invalid"):
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=0,
            expected_detail_count=1,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash(()),
            expected_detail_set_hash=backtest_detail_set_hash((detail,)),
        )
    assert store.get_run(summary.run_id) is None
    assert store.list_details(summary.run_id) == ()


@pytest.mark.parametrize("surface", ["summary", "fill", "detail"])
def test_materialized_reads_reject_tampered_sql_identity_columns(
    tmp_path: Path,
    surface: str,
) -> None:
    path = tmp_path / f"{surface}.sqlite3"
    store = BacktestResultStore(path)
    summary = _summary(f"materialized-{surface}")
    fill = _fill(summary)
    detail = _detail(summary, BacktestDetailKind.DECISION)
    _materialize(store, summary, fills=(fill,), details=(detail,))

    with sqlite3.connect(path) as connection:
        if surface == "summary":
            connection.execute(
                "UPDATE backtest_run SET plan_sha256 = ? WHERE run_id = ?",
                ("f" * 64, summary.run_id),
            )
        elif surface == "fill":
            connection.execute(
                "UPDATE backtest_fill SET filled_at = ? WHERE fill_id = ?",
                (datetime(2026, 8, 24, 8, tzinfo=UTC).isoformat(), fill.fill_id),
            )
        else:
            connection.execute(
                "UPDATE backtest_detail SET kind = 'SIGNAL' WHERE detail_id = ?",
                (detail.detail_id,),
            )
        connection.commit()

    with pytest.raises(RuntimeError, match="SQL identity"):
        if surface == "summary":
            store.get_run(summary.run_id)
        elif surface == "fill":
            store.list_fills(summary.run_id)
        else:
            store.list_details(summary.run_id, kind=BacktestDetailKind.DECISION)


def test_retention_boundedly_removes_abandoned_staged_rows_only(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "backtest-results.sqlite3")
    as_of = datetime(2026, 8, 25, 12, tzinfo=UTC)
    staged = _summary("abandoned-stage")
    staged_fill = _fill(staged)
    staged_detail = _detail(staged, BacktestDetailKind.DECISION)
    assert (
        store.record_run(
            staged,
            retention_at=as_of - timedelta(days=15),
        )
        is True
    )
    assert store.record_fills(staged.run_id, (staged_fill,)) == 1
    assert store.record_details(staged.run_id, (staged_detail,)) == 1
    retained = _summary("retained-materialized")
    retained_detail = _detail(retained, BacktestDetailKind.DECISION)
    _materialize(store, retained, details=(retained_detail,))

    deleted = 0
    while True:
        result = store.prune_details(as_of=as_of, batch_size=1)
        deleted += result.deleted_count
        if not result.has_more:
            break

    assert deleted == 3
    assert store.get_run(staged.run_id, include_unmaterialized=True) is None
    assert store.get_run(retained.run_id) == retained
    assert store.list_details(retained.run_id) == (retained_detail,)


def test_detail_retention_combines_age_count_debug_and_pin_rules(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "backtest-results.sqlite3")
    as_of = datetime(2026, 8, 25, 12, tzinfo=UTC)
    expected_kept: set[str] = set()

    # All completed runs, including pinned ones, share the latest-30 total cap.
    for index in range(102):
        summary = _summary(
            f"recent-{index:03d}",
            completed_at=as_of - timedelta(days=30, hours=102 - index),
        )
        detail = _detail(summary, BacktestDetailKind.DECISION)
        _materialize(store, summary, fills=(_fill(summary),), details=(detail,))
        if index >= 73:
            expected_kept.add(detail.detail_id)

    old_success = _summary("old-success", completed_at=as_of - timedelta(days=91))
    old_success_detail = _detail(old_success, BacktestDetailKind.DAILY_EQUITY)
    _materialize(
        store,
        old_success,
        fills=(_fill(old_success),),
        details=(old_success_detail,),
    )

    debug_success = _summary("debug-success", completed_at=as_of - timedelta(days=20))
    debug_detail = _detail(debug_success, BacktestDetailKind.DEBUG_TRACE)
    decision_detail = _detail(debug_success, BacktestDetailKind.SIGNAL, "signal")
    _materialize(store, debug_success, details=(debug_detail, decision_detail))
    expected_kept.add(decision_detail.detail_id)

    pinned = _summary(
        "pinned",
        completed_at=as_of - timedelta(days=500),
        pinned=True,
    )
    pinned_detail = _detail(pinned, BacktestDetailKind.DEBUG_TRACE)
    _materialize(
        store,
        pinned,
        fills=(_fill(pinned),),
        details=(pinned_detail,),
    )

    deleted = 0
    while True:
        result = store.prune_details(as_of=as_of, batch_size=2)
        assert result.deleted_count <= 2
        deleted += result.deleted_count
        if not result.has_more:
            break

    assert deleted == 226
    kept_ids: set[str] = set()
    for summary in store.list_runs(limit=200):
        kept_ids.update(item.detail_id for item in store.list_details(summary.run_id))
    assert kept_ids == expected_kept

    statistics = store.statistics()
    assert statistics.run_count == 30
    assert statistics.fill_count == 29
    assert statistics.detail_count == len(expected_kept)
    assert store.get_run(old_success.run_id) is None
    assert store.list_fills(old_success.run_id) == ()
    assert store.get_run(pinned.run_id) is None
    with pytest.raises(KeyError, match="unknown run_id"):
        store.record_details(old_success.run_id, (old_success_detail,))


def test_result_batches_are_bounded_and_result_writes_are_completed_only(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "backtest-results.sqlite3")
    completed = _summary("completed")
    store.record_run(completed)
    for status in (BacktestRunStatus.FAILED, BacktestRunStatus.CANCELLED):
        with pytest.raises(ValueError, match="completed-only"):
            store.record_run(_summary(status.value.lower(), status=status))

    fills = tuple(_fill(completed, str(index)) for index in range(1_001))
    with pytest.raises(ValueError, match="at most 1000"):
        store.record_fills(completed.run_id, fills)
    details = tuple(
        _detail(completed, BacktestDetailKind.DECISION, str(index)) for index in range(1_001)
    )
    with pytest.raises(ValueError, match="at most 1000"):
        store.record_details(completed.run_id, details)
    with pytest.raises(ValueError, match="COMPLETED"):
        store.record_details(
            completed.run_id,
            (_detail(completed, BacktestDetailKind.DIAGNOSTIC),),
        )
    with pytest.raises(ValueError, match="batch_size"):
        store.prune_details(
            as_of=datetime(2026, 8, 25, tzinfo=UTC),
            batch_size=1_001,
        )


def test_pinning_is_explicit_metadata_and_does_not_change_immutable_summary(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "backtest-results.sqlite3")
    summary = _summary("pin-toggle")
    _materialize(store, summary)

    assert store.set_pinned(summary.run_id, True) is True
    assert store.set_pinned(summary.run_id, True) is False
    assert store.get_run(summary.run_id) == summary.model_copy(update={"pinned": True})
    assert store.set_pinned(summary.run_id, False) is True
    assert store.get_run(summary.run_id) == summary
    with pytest.raises(KeyError, match="unknown run_id"):
        store.set_pinned(_hash("missing"), True)


def test_detail_adapter_accepts_execution_signal_outcome_and_equity_models(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "backtest-results.sqlite3")
    summary = _summary("execution-model-adapters")
    store.record_run(summary)
    event_at = datetime(2026, 8, 24, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
    signal = ExecutionSignal.create(
        run_id=summary.run_id,
        plan_hash=summary.plan_sha256,
        dataset_hash=summary.dataset_hash,
        result_hash=_hash("result"),
        signal_type=ActionableSignalType.RISK_BREACH,
        symbol="600000.SH",
        signal_at=event_at,
        trading_date=event_at.date(),
        cause_id=_hash("cause"),
        quantity=None,
        bucket=None,
        target_lot_id=None,
    )
    outcome = ExecutionOutcome.create(
        signal_id=signal.signal_id,
        order_id=None,
        resolved_at=event_at,
        source_bar_id=None,
        status=ExecutionStatus.IGNORED,
        reason=UnfilledReason.NON_EXECUTABLE_SIGNAL,
        fill_id=None,
    )
    equity = EquitySnapshot.create(
        run_id=summary.run_id,
        symbol="600000.SH",
        marked_at=event_at,
        mark_price_fen=1_000,
        cash_fen=90_000,
        position_quantity=100,
        cost_basis_fen=100_000,
        realized_pnl_fen=0,
        total_cost_fen=500,
    )

    details = (
        BacktestDetailRecord.from_value(BacktestDetailKind.SIGNAL, signal),
        BacktestDetailRecord.from_value(
            BacktestDetailKind.EXECUTION_OUTCOME,
            outcome,
            run_id=summary.run_id,
        ),
        BacktestDetailRecord.from_value(BacktestDetailKind.DAILY_EQUITY, equity),
    )
    assert store.record_details(summary.run_id, details) == 3
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert (
        store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=0,
            expected_detail_count=3,
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash(()),
            expected_detail_set_hash=backtest_detail_set_hash(details),
        )
        is True
    )
    assert {item.detail_id for item in store.list_details(summary.run_id)} == {
        signal.signal_id,
        outcome.outcome_id,
        equity.snapshot_id,
    }
    persisted_outcome = next(
        item
        for item in store.list_details(
            summary.run_id,
            kind=BacktestDetailKind.EXECUTION_OUTCOME,
        )
    )
    assert persisted_outcome.event_at == event_at.astimezone(UTC)
    assert persisted_outcome.payload["resolved_at"] == event_at.astimezone(UTC).isoformat(
        timespec="microseconds"
    )
    assert persisted_outcome.payload["source_bar_id"] is None
