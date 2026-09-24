"""Atomic bounded checkpoints for a single runtime's provider admission owner."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from os.path import normcase
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from trade_plan_monitor.runtime.clock import _canonical_shanghai
from trade_plan_monitor.state.models import ProviderRecoveryCheckpoint

_OPERATIONS = frozenset(
    {
        "probe_capabilities",
        "realtime_minutes",
        "current_day_minutes",
        "historical_minutes",
        "trading_calendar",
        "daily_limits",
        "daily_bars",
        "idx_mins",
        "rt_idx_min_daily",
        "index_daily",
    }
)
_REASONS = {"cooldown": "RATE_LIMITED", "permission": "BLOCKED_PERMISSION", "backoff": "TRANSIENT"}
_OWNERS: dict[tuple[str, str], object] = {}
_OWNER_LOCK = threading.Lock()


class RecoveryCheckpointError(RuntimeError):
    """Persisted admission facts are unavailable or invalid; never admit through this fault."""


@dataclass(frozen=True, slots=True)
class RecoveryCheckpoint:
    kind: str
    scope_key: str
    retry_at: datetime
    failures: int


def _validate(checkpoints: tuple[RecoveryCheckpoint, ...]) -> None:
    seen = set()
    counts = {"cooldown": 0, "permission": 0, "backoff": 0}
    for item in checkpoints:
        if not isinstance(item, RecoveryCheckpoint) or item.kind not in counts:
            raise ValueError
        identity = (item.kind, item.scope_key)
        if identity in seen:
            raise ValueError
        seen.add(identity)
        counts[item.kind] += 1
        _canonical_shanghai(item.retry_at)
        if type(item.failures) is not int:
            raise ValueError
        if item.kind == "backoff":
            if not re.fullmatch(r"[a-f0-9]{64}", item.scope_key) or not 1 <= item.failures <= 16:
                raise ValueError
        elif item.failures != 0:
            raise ValueError
        elif item.kind == "cooldown" and item.scope_key != "shared":
            raise ValueError
        elif item.kind == "permission" and item.scope_key not in _OPERATIONS:
            raise ValueError
    if counts["cooldown"] > 1 or counts["permission"] > len(_OPERATIONS) or counts["backoff"] > 64:
        raise ValueError


class ProviderRecoveryRepository:
    """One explicitly configured provider namespace, containing at most 75 rows.

    The identity is a digest of stable endpoint/profile settings, never of credentials.
    The runtime must join its old owner before replacing a bound controller.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        provider_identity: str,
    ) -> None:
        if type(provider_identity) is not str or not re.fullmatch(
            r"[a-f0-9]{64}", provider_identity
        ):
            raise ValueError("provider_identity must be a stable nonsecret SHA-256 digest")
        self._session_factory = session_factory
        self._provider_identity = provider_identity
        engine = session_factory.kw["bind"]
        database = engine.url.database
        database_key = (
            f"memory:{id(engine)}"
            if database in (None, "", ":memory:")
            else normcase(str(Path(database).resolve()))
        )
        self._owner_key = (database_key, provider_identity)

    def acquire_owner(self, owner: object) -> None:
        """Reject overlapping controllers in this single-process local runtime."""
        with _OWNER_LOCK:
            if self._owner_key in _OWNERS:
                raise RecoveryCheckpointError("provider recovery checkpoint is already owned")
            _OWNERS[self._owner_key] = owner

    def release_owner(self, owner: object) -> None:
        """Release only after controller admission and physical work have joined."""
        with _OWNER_LOCK:
            if _OWNERS.get(self._owner_key) is owner:
                del _OWNERS[self._owner_key]

    def load(self) -> tuple[RecoveryCheckpoint, ...]:
        try:
            with self._session_factory() as session:
                rows = session.scalars(
                    select(ProviderRecoveryCheckpoint)
                    .where(
                        ProviderRecoveryCheckpoint.provider_identity == self._provider_identity,
                    )
                    .limit(76)
                ).all()
                if any(
                    row.schema_version != 1 or row.reason_code != _REASONS.get(row.kind)
                    for row in rows
                ):
                    raise ValueError
                checkpoints = tuple(
                    RecoveryCheckpoint(
                        row.kind,
                        row.scope_key,
                        datetime.fromisoformat(row.retry_at),
                        row.failures,
                    )
                    for row in rows
                )
                _validate(checkpoints)
                return checkpoints
        except Exception:
            raise RecoveryCheckpointError("invalid provider recovery checkpoint") from None

    def assert_owner(self, owner: object) -> None:
        with _OWNER_LOCK:
            if _OWNERS.get(self._owner_key) is not owner:
                raise RecoveryCheckpointError(
                    "provider recovery checkpoint owner is no longer active"
                )

    def save(self, checkpoints: tuple[RecoveryCheckpoint, ...]) -> None:
        try:
            _validate(checkpoints)
            with self._session_factory.begin() as session:
                session.execute(
                    delete(ProviderRecoveryCheckpoint).where(
                        ProviderRecoveryCheckpoint.provider_identity == self._provider_identity,
                    )
                )
                session.add_all(
                    ProviderRecoveryCheckpoint(
                        provider_identity=self._provider_identity,
                        kind=item.kind,
                        scope_key=item.scope_key,
                        schema_version=1,
                        retry_at=_canonical_shanghai(item.retry_at).isoformat(),
                        failures=item.failures,
                        reason_code=_REASONS[item.kind],
                    )
                    for item in checkpoints
                )
        except Exception:
            raise RecoveryCheckpointError("invalid provider recovery checkpoint") from None
