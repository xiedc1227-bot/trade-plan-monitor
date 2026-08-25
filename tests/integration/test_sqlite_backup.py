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


def test_verification_rejects_a_wal_header_without_creating_sidecars(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpointed-wal.db"
    connection = sqlite3.connect(database_path, isolation_level=None)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE verification_probe (value TEXT NOT NULL)")
        connection.execute("INSERT INTO verification_probe(value) VALUES ('checkpointed')")
        assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    finally:
        connection.close()
    sidecars = (Path(f"{database_path}-wal"), Path(f"{database_path}-shm"))
    assert all(not sidecar.exists() for sidecar in sidecars)

    with pytest.raises(BackupVerificationError, match="standalone"):
        verify_sqlite_backup(database_path)

    assert all(not sidecar.exists() for sidecar in sidecars)


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
        candidate = Path(_path)
        Path(f"{candidate}-wal").write_bytes(b"temporary wal")
        Path(f"{candidate}-shm").write_bytes(b"temporary shm")
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
    assert tuple(backup_directory.iterdir()) == (preserved.path,)


def test_retention_keeps_latest_thirty_verified_owned_backups_only(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    _create_live_database(database_path)
    backup_directory.mkdir()
    unrelated = backup_directory / "notes.txt"
    unrelated.write_text("not owned", encoding="utf-8")
    invalid_owned = backup_directory / "monitor-backup-20200101T000000000000Z-invalid.sqlite3"
    invalid_owned.write_bytes(b"not a sqlite database")
    legacy_owned = backup_directory / "monitor-backup-20200101T000001000000Z-legacy.sqlite3"
    legacy_connection = sqlite3.connect(legacy_owned, isolation_level=None)
    assert legacy_connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    legacy_connection.execute("CREATE TABLE legacy_probe (value TEXT NOT NULL)")
    legacy_connection.execute("PRAGMA wal_autocheckpoint=0")
    assert legacy_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    legacy_connection.execute("INSERT INTO legacy_probe(value) VALUES ('wal-only')")
    legacy_wal = Path(f"{legacy_owned}-wal")
    legacy_shm = Path(f"{legacy_owned}-shm")
    assert legacy_wal.stat().st_size > 0
    times = iter(_FIXED_NOW + timedelta(seconds=index) for index in range(31))
    identifiers = iter(f"backup-{index:02d}" for index in range(31))
    service = SQLiteBackupService(
        database_path,
        backup_directory,
        clock=lambda: next(times),
        id_factory=lambda: next(identifiers),
    )

    try:
        results = [service.create() for _ in range(31)]

        assert legacy_owned.is_file()
        assert legacy_wal.is_file()
        assert legacy_shm.is_file()
    finally:
        legacy_connection.close()

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


def test_dangling_temporary_symlink_cannot_escape_backup_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.db"
    backup_directory = tmp_path / "backups"
    escaped_path = tmp_path / "outside" / "escaped.sqlite3"
    _create_live_database(database_path)
    backup_directory.mkdir()
    temporary_path = backup_directory / (
        ".monitor-backup-20260821T173000000000Z-dangling-link.sqlite3.tmp"
    )
    temporary_path.symlink_to(escaped_path)
    assert temporary_path.is_symlink()
    assert temporary_path.exists() is False

    with pytest.raises(BackupPathError, match="destination already exists"):
        SQLiteBackupService(
            database_path,
            backup_directory,
            clock=lambda: _FIXED_NOW,
            id_factory=lambda: "dangling-link",
        ).create()

    assert escaped_path.exists() is False
    assert temporary_path.is_symlink()


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
