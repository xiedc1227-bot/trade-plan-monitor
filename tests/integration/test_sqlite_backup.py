import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest

import trade_plan_monitor.state.backup as backup_module
from trade_plan_monitor.state.backup import (
    BackupPathError,
    BackupVerificationError,
    SQLiteBackupService,
    verify_sqlite_backup,
)
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database

_FIXED_NOW = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _create_live_database(database_path: Path) -> None:
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()

    with sqlite3.connect(database_path, isolation_level=None) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE backup_probe (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        connection.execute("INSERT INTO backup_probe(value) VALUES ('wal-sentinel')")


def test_online_backup_contains_uncheckpointed_wal_data_during_writes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    direct_copy_path = tmp_path / "unsafe-direct-copy.db"
    _create_live_database(database_path)
    stop_writer = Event()
    writer_started = Event()
    writer_errors: list[Exception] = []

    keeper = sqlite3.connect(database_path, isolation_level=None)
    keeper.execute("PRAGMA wal_autocheckpoint=0")
    assert keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    keeper.execute("INSERT INTO backup_probe(value) VALUES ('wal-only-sentinel')")
    shutil.copy2(database_path, direct_copy_path)
    with sqlite3.connect(direct_copy_path) as direct_copy:
        assert direct_copy.execute(
            "SELECT count(*) FROM backup_probe WHERE value = 'wal-only-sentinel'"
        ).fetchone() == (0,)

    def keep_writing() -> None:
        try:
            with sqlite3.connect(database_path, timeout=5, isolation_level=None) as connection:
                connection.execute("PRAGMA wal_autocheckpoint=0")
                sequence = 0
                while not stop_writer.is_set():
                    connection.execute(
                        "INSERT INTO backup_probe(value) VALUES (?)",
                        (f"concurrent-{sequence}",),
                    )
                    sequence += 1
                    writer_started.set()
        except Exception as error:  # pragma: no cover - asserted through writer_errors
            writer_errors.append(error)

    writer = Thread(target=keep_writing, name="sqlite-backup-test-writer")
    writer.start()
    assert writer_started.wait(timeout=5)

    try:
        result = SQLiteBackupService(
            database_path,
            backup_directory,
            clock=lambda: _FIXED_NOW,
            id_factory=lambda: "backup-one",
        ).create()
    finally:
        stop_writer.set()
        writer.join(timeout=5)
        keeper.close()

    assert not writer.is_alive()
    assert writer_errors == []
    assert Path(f"{database_path}-wal").stat().st_size > 0
    assert result.path.parent == backup_directory.resolve()
    assert result.path.suffix == ".sqlite3"
    assert result.created_at == _FIXED_NOW
    assert result.integrity_check == "ok"
    assert result.size_bytes == result.path.stat().st_size
    assert result.removed_paths == ()

    verification = verify_sqlite_backup(result.path)
    assert verification.integrity_check == "ok"
    with sqlite3.connect(result.path) as backup_connection:
        sentinel_count = backup_connection.execute(
            "SELECT count(*) FROM backup_probe WHERE value = 'wal-only-sentinel'"
        ).fetchone()
    assert sentinel_count == (1,)


def test_verified_backup_restores_to_a_readable_database(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    restore_path = tmp_path / "restored.db"
    _create_live_database(database_path)

    result = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: _FIXED_NOW,
        id_factory=lambda: "backup-two",
    ).create()
    shutil.copy2(result.path, restore_path)

    with sqlite3.connect(restore_path) as restored_connection:
        assert restored_connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert restored_connection.execute(
            "SELECT value FROM backup_probe ORDER BY id LIMIT 1"
        ).fetchone() == ("wal-sentinel",)


def test_failed_verification_preserves_existing_successful_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    _create_live_database(database_path)
    preserved = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: _FIXED_NOW,
        id_factory=lambda: "preserved",
    ).create()
    preserved_bytes = preserved.path.read_bytes()

    def reject_candidate(_path: str | Path) -> backup_module.BackupVerification:
        raise backup_module.BackupVerificationError("injected verification failure")

    monkeypatch.setattr(backup_module, "verify_sqlite_backup", reject_candidate)
    with pytest.raises(backup_module.BackupVerificationError):
        SQLiteBackupService(
            database_path,
            backup_directory,
            clock=lambda: _FIXED_NOW + timedelta(seconds=1),
            id_factory=lambda: "failed",
        ).create()

    assert preserved.path.read_bytes() == preserved_bytes
    assert sorted(backup_directory.glob("monitor-backup-*.sqlite3")) == [preserved.path]
    assert list(backup_directory.glob(".*.tmp")) == []


def test_retention_keeps_latest_thirty_verified_owned_backups_only(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    _create_live_database(database_path)
    backup_directory.mkdir()
    unrelated = backup_directory / "notes.txt"
    unrelated.write_text("not owned", encoding="utf-8")
    invalid_owned = backup_directory / "monitor-backup-20200101T000000000000Z-invalid.sqlite3"
    invalid_owned.write_bytes(b"not a sqlite database")
    times = iter(_FIXED_NOW + timedelta(seconds=index) for index in range(31))
    identifiers = iter(f"backup-{index:02d}" for index in range(31))
    service = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: next(times),
        id_factory=lambda: next(identifiers),
    )

    results = [service.create() for _ in range(31)]

    assert results[0].path.exists() is False
    assert all(result.path.exists() for result in results[1:])
    assert results[-1].removed_paths == (results[0].path,)
    assert invalid_owned.read_bytes() == b"not a sqlite database"
    assert unrelated.read_text(encoding="utf-8") == "not owned"
    assert len([result for result in results if result.path.exists()]) == 30


def test_destination_collision_never_overwrites_verified_backup(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    _create_live_database(database_path)
    service = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: _FIXED_NOW,
        id_factory=lambda: "same-name",
    )
    existing = service.create()
    existing_bytes = existing.path.read_bytes()

    with pytest.raises(BackupPathError, match="destination already exists"):
        service.create()

    assert existing.path.read_bytes() == existing_bytes
    assert list(backup_directory.glob(".*.tmp")) == []


def test_corrupt_backup_is_rejected_with_sanitized_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(BackupVerificationError) as failure:
        verify_sqlite_backup(corrupt)

    assert failure.value.code == "BACKUP_VERIFICATION_FAILED"
    assert failure.value.__cause__ is None
    assert str(corrupt) not in str(failure.value)


def test_unsafe_backup_identifier_is_rejected_before_writing(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    _create_live_database(database_path)
    service = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: _FIXED_NOW,
        id_factory=lambda: "../escape",
    )

    with pytest.raises(ValueError, match="safe 1 to 64 character identifier"):
        service.create()

    assert backup_directory.exists() is False
    assert list(tmp_path.glob("escape*")) == []
