"""Verified online backups for the local SQLite WAL database.

Online backup semantics follow the Python and SQLite documentation:
https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup
https://www.sqlite.org/backup.html
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

_BACKUP_PREFIX = "monitor-backup-"
_BACKUP_SUFFIX = ".sqlite3"
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_OWNED_BACKUP_PATTERN = re.compile(
    r"monitor-backup-(?P<timestamp>\d{8}T\d{12}Z)-[A-Za-z0-9_-]{1,64}\.sqlite3"
)
SUCCESSFUL_BACKUP_RETENTION = 30

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class BackupError(RuntimeError):
    """Base for sanitized failures in the backup boundary."""

    code = "BACKUP_FAILED"


class BackupPathError(BackupError):
    """A configured backup source or destination path is unsafe."""

    code = "BACKUP_PATH_INVALID"


class BackupVerificationError(BackupError):
    """A candidate backup is not a readable, integral SQLite database."""

    code = "BACKUP_VERIFICATION_FAILED"


class BackupRetentionError(BackupError):
    """Verified backup retention could not complete safely."""

    code = "BACKUP_RETENTION_FAILED"


@dataclass(frozen=True, slots=True)
class BackupVerification:
    """Read-only verification facts for one SQLite backup file."""

    path: Path
    integrity_check: str
    size_bytes: int
    schema_object_count: int


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Published backup metadata and any retention removals."""

    path: Path
    created_at: datetime
    integrity_check: str
    size_bytes: int
    removed_paths: tuple[Path, ...]


class SQLiteBackupService:
    """Create one verified snapshot without directly copying an in-use WAL file."""

    def __init__(
        self,
        database_path: str | Path,
        backup_directory: str | Path,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self._database_path = _existing_file(database_path, "database_path")
        self._backup_directory = _directory_path(backup_directory)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def create(self) -> BackupResult:
        """Copy, verify, and atomically publish one online database snapshot."""

        created_at = _aware_datetime(self._clock(), "clock")
        backup_id = _backup_id(self._id_factory())
        timestamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        final_path = self._backup_directory / (
            f"{_BACKUP_PREFIX}{timestamp}-{backup_id}{_BACKUP_SUFFIX}"
        )
        temporary_path = self._backup_directory / f".{final_path.name}.tmp"
        self._prepare_destination(final_path, temporary_path)

        try:
            _copy_online(self._database_path, temporary_path)
            verification = verify_sqlite_backup(temporary_path)
            os.replace(temporary_path, final_path)
            removed_paths = _apply_retention(self._backup_directory)
        except BackupError:
            _remove_temporary(temporary_path, self._backup_directory)
            raise
        except OSError, sqlite3.Error:
            _remove_temporary(temporary_path, self._backup_directory)
            raise BackupError("SQLite online backup could not be completed") from None

        return BackupResult(
            path=final_path,
            created_at=created_at,
            integrity_check=verification.integrity_check,
            size_bytes=verification.size_bytes,
            removed_paths=removed_paths,
        )

    def _prepare_destination(self, final_path: Path, temporary_path: Path) -> None:
        try:
            self._backup_directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise BackupPathError("Backup directory could not be created") from None
        if not self._backup_directory.is_dir():
            raise BackupPathError("backup_directory must point to a directory")
        if final_path.exists() or temporary_path.exists():
            raise BackupPathError("Backup destination already exists")


def verify_sqlite_backup(backup_path: str | Path) -> BackupVerification:
    """Verify integrity and basic schema readability without modifying the file."""

    path = _existing_file(backup_path, "backup_path")
    try:
        with closing(sqlite3.connect(_read_only_uri(path), uri=True, timeout=5)) as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            schema_object_count = int(
                connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0]
            )
    except OSError, sqlite3.Error, TypeError, ValueError, IndexError:
        raise BackupVerificationError("SQLite backup verification failed") from None
    if integrity_rows != [("ok",)]:
        raise BackupVerificationError("SQLite backup integrity check failed")
    return BackupVerification(
        path=path,
        integrity_check="ok",
        size_bytes=path.stat().st_size,
        schema_object_count=schema_object_count,
    )


def _copy_online(source_path: Path, destination_path: Path) -> None:
    with (
        closing(sqlite3.connect(_read_only_uri(source_path), uri=True, timeout=5)) as source,
        closing(sqlite3.connect(destination_path, timeout=5)) as destination,
    ):
        source.backup(destination, pages=128, sleep=0.01)


def _existing_file(value: str | Path, name: str) -> Path:
    path = _path_value(value, name).resolve()
    if not path.is_file():
        raise BackupPathError(f"{name} must point to an existing file")
    return path


def _directory_path(value: str | Path) -> Path:
    path = _path_value(value, "backup_directory").resolve()
    if path.exists() and not path.is_dir():
        raise BackupPathError("backup_directory must point to a directory")
    return path


def _path_value(value: str | Path, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"{name} must be a string or Path")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{name} must not be empty")
    return Path(value).expanduser()


def _aware_datetime(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must return a timezone-aware datetime")
    return value


def _backup_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("id_factory must return a string")
    if _ID_PATTERN.fullmatch(value) is None:
        raise ValueError("id_factory must return a safe 1 to 64 character identifier")
    return value


def _read_only_uri(path: Path) -> str:
    return f"{path.as_uri()}?mode=ro"


def _remove_temporary(path: Path, backup_directory: Path) -> None:
    if path.parent.resolve() != backup_directory.resolve() or not path.name.startswith("."):
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _apply_retention(backup_directory: Path) -> tuple[Path, ...]:
    try:
        entries = tuple(backup_directory.iterdir())
    except OSError:
        raise BackupRetentionError("Backup directory could not be inspected") from None

    successful: list[tuple[str, Path]] = []
    for candidate in entries:
        match = _OWNED_BACKUP_PATTERN.fullmatch(candidate.name)
        if match is None or candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved.parent != backup_directory:
            continue
        try:
            verify_sqlite_backup(resolved)
        except BackupError:
            continue
        successful.append((match.group("timestamp"), resolved))

    successful.sort(key=lambda item: (item[0], item[1].name))
    removal_count = max(0, len(successful) - SUCCESSFUL_BACKUP_RETENTION)
    removed: list[Path] = []
    for _timestamp, candidate in successful[:removal_count]:
        if not _safe_retention_candidate(candidate, backup_directory):
            continue
        try:
            candidate.unlink()
        except OSError:
            raise BackupRetentionError("Verified backup could not be removed") from None
        removed.append(candidate)
    return tuple(removed)


def _safe_retention_candidate(candidate: Path, backup_directory: Path) -> bool:
    if candidate.is_symlink() or _OWNED_BACKUP_PATTERN.fullmatch(candidate.name) is None:
        return False
    resolved = candidate.resolve()
    if resolved.parent != backup_directory or not resolved.is_file():
        return False
    try:
        verify_sqlite_backup(resolved)
    except BackupError:
        return False
    return True


__all__ = [
    "BackupError",
    "BackupPathError",
    "BackupResult",
    "BackupRetentionError",
    "BackupVerification",
    "BackupVerificationError",
    "SQLiteBackupService",
    "SUCCESSFUL_BACKUP_RETENTION",
    "verify_sqlite_backup",
]
