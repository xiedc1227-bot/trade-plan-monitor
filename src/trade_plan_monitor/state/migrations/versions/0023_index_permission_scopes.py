"""Split the legacy index-minute permission reservation into endpoint scopes.

The existing checkpoint table stays unchanged. This data migration validates every
provider namespace before replacing a legacy reservation with both new scopes.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0023_index_permission_scopes"
down_revision = "0022_runtime_liveness"
branch_labels = None
depends_on = None

_LEGACY = "index_minutes"
_NEW = ("idx_mins", "rt_idx_min_daily")
_PERMISSIONS = frozenset(
    {
        "probe_capabilities",
        "realtime_minutes",
        "current_day_minutes",
        "historical_minutes",
        "trading_calendar",
        "daily_limits",
        "daily_bars",
        "index_daily",
        _LEGACY,
        *_NEW,
    }
)
_REASONS = {"cooldown": "RATE_LIMITED", "permission": "BLOCKED_PERMISSION", "backoff": "TRANSIENT"}
_DIGEST = re.compile(r"[a-f0-9]{64}")


def _read_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError("invalid provider recovery checkpoint")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise RuntimeError("invalid provider recovery checkpoint") from error
    if parsed.utcoffset() != timedelta(hours=8) or parsed.isoformat() != value:
        raise RuntimeError("invalid provider recovery checkpoint")
    return parsed


def _validated_rows(rows, provider_identity: str):
    if not _DIGEST.fullmatch(provider_identity) or len(rows) > 76:
        raise RuntimeError("invalid provider recovery checkpoint")
    counts = {"cooldown": 0, "permission": 0, "backoff": 0}
    permissions = {}
    for kind, scope, version, retry_at, failures, reason in rows:
        if kind not in counts or version != 1 or reason != _REASONS[kind]:
            raise RuntimeError("invalid provider recovery checkpoint")
        if type(failures) is not int or not 0 <= failures <= 16:
            raise RuntimeError("invalid provider recovery checkpoint")
        parsed = _read_timestamp(retry_at)
        counts[kind] += 1
        if kind == "cooldown":
            if scope != "shared" or failures != 0:
                raise RuntimeError("invalid provider recovery checkpoint")
        elif kind == "permission":
            if scope not in _PERMISSIONS or failures != 0:
                raise RuntimeError("invalid provider recovery checkpoint")
            permissions[scope] = (parsed, retry_at)
        elif not isinstance(scope, str) or not _DIGEST.fullmatch(scope) or failures < 1:
            raise RuntimeError("invalid provider recovery checkpoint")
    maximum = 76 if _LEGACY in permissions else 75
    if (
        len(rows) > maximum
        or counts["cooldown"] > 1
        or counts["permission"] > (11 if _LEGACY in permissions else 10)
        or counts["backoff"] > 64
    ):
        raise RuntimeError("invalid provider recovery checkpoint")
    return permissions


def upgrade() -> None:
    connection = op.get_bind()
    identities = (
        connection.execute(
            sa.text("SELECT DISTINCT provider_identity FROM provider_recovery_checkpoint")
        )
        .scalars()
        .all()
    )
    plans = []
    for identity in identities:
        rows = connection.execute(
            sa.text(
                "SELECT kind, scope_key, schema_version, retry_at, failures, reason_code "
                "FROM provider_recovery_checkpoint WHERE provider_identity=:identity LIMIT 77"
            ),
            {"identity": identity},
        ).all()
        permissions = _validated_rows(rows, identity)
        legacy = permissions.get(_LEGACY)
        if legacy is not None:
            plans.append((identity, legacy, permissions))

    for identity, legacy, permissions in plans:
        for scope in _NEW:
            existing = permissions.get(scope)
            if existing is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO provider_recovery_checkpoint "
                        "(provider_identity, kind, scope_key, schema_version, retry_at, failures, "
                        "reason_code) VALUES (:identity, 'permission', :scope, 1, :retry, 0, "
                        "'BLOCKED_PERMISSION')"
                    ),
                    {"identity": identity, "scope": scope, "retry": legacy[1]},
                )
            elif existing[0] < legacy[0]:
                connection.execute(
                    sa.text(
                        "UPDATE provider_recovery_checkpoint SET retry_at=:retry "
                        "WHERE provider_identity=:identity AND kind='permission' "
                        "AND scope_key=:scope"
                    ),
                    {"identity": identity, "scope": scope, "retry": legacy[1]},
                )
        connection.execute(
            sa.text(
                "DELETE FROM provider_recovery_checkpoint WHERE provider_identity=:identity "
                "AND kind='permission' AND scope_key=:scope"
            ),
            {"identity": identity, "scope": _LEGACY},
        )


def downgrade() -> None:
    present = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM provider_recovery_checkpoint "
                "WHERE scope_key IN ('idx_mins', 'rt_idx_min_daily') LIMIT 1"
            )
        )
        .scalar_one_or_none()
    )
    if present is not None:
        raise RuntimeError("0023_index_permission_scopes refuses to discard new permission state")
