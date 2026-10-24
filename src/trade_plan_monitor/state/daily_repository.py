"""Session-bound daily records, all mutations fenced and audit-preserving."""

import json
from hashlib import sha256

from sqlalchemy import select, update

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AuditLog
from trade_plan_monitor.state.repositories import RevisionConflictError


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def daily_hash(domain: str, value) -> str:
    return sha256(domain.encode() + b"\x00" + canonical(value).encode()).hexdigest()


class DailyRepository:
    def __init__(self, session, *, clock, id_factory):
        self.session = session
        self.clock = clock
        self.id_factory = id_factory

    def lock_symbol(self, symbol):
        """Acquire SQLite's write transaction without touching shared actual inventory."""
        self.session.execute(
            update(DailyRecord)
            .where(DailyRecord.symbol == symbol)
            .values(revision=DailyRecord.revision)
        )

    def get(self, identity):
        row = self.session.get(DailyRecord, identity)
        return None if row is None else self._value(row)

    def list(self, *, symbol, kind, lineage=None, limit=500):
        """Read an internal history in bounded SQL pages without truncating evidence."""
        return tuple(self.iter_records(symbol=symbol, kind=kind, lineage=lineage, limit=limit))

    def iter_records(self, *, symbol, kind, lineage=None, limit=500):
        if not 1 <= limit <= 500:
            raise ValueError("daily read exceeds its bound")
        statement = select(DailyRecord).where(
            DailyRecord.symbol == symbol, DailyRecord.kind == kind
        )
        if lineage is not None:
            statement = statement.where(DailyRecord.lineage == lineage)
        offset = 0
        while True:
            rows = self.session.scalars(
                statement.order_by(DailyRecord.created_at, DailyRecord.id)
                .offset(offset)
                .limit(limit)
            ).all()
            for row in rows:
                yield self._value(row)
            if len(rows) < limit:
                return
            offset += limit

    def current_signals(self, *, symbol):
        """Project unresolved occurrences plus the last consumed occurrence per side.

        Full history remains immutable in the paged repository. Rearm needs the
        most recent prior occurrence even after hundreds of completed signals.
        """
        current = {}
        latest = {}
        for row in self.iter_records(symbol=symbol, kind="SIGNAL"):
            signal = row["payload"]
            key = (
                (signal["side"], signal["rule_id"])
                if signal.get("occurrence_mode")
                else signal["side"]
            )
            latest[key] = row
            if signal["state"] in {"CONFIRMED", "READY"}:
                current[row["id"]] = row
        current.update((row["id"], row) for row in latest.values())
        return tuple(sorted(current.values(), key=lambda r: (r["created_at"], r["id"])))

    def save(self, identity, *, kind, symbol, lineage, payload, expected_revision):
        from trade_plan_monitor.state.daily_state_models import validate_daily_payload

        validate_daily_payload(kind, payload)
        row = self.session.get(DailyRecord, identity)
        actual = 0 if row is None else row.revision
        if row is not None and kind in {"EXCEPTION_EVENT", "EXCEPTION_PREVIEW"}:
            raise ValueError("exception evidence is append-only")
        if actual != expected_revision:
            raise RevisionConflictError(actual)
        now = self.clock().isoformat()
        before = None if row is None else row.payload_json
        serialized = canonical(payload)
        if row is None:
            row = DailyRecord(
                id=identity,
                kind=kind,
                symbol=symbol,
                lineage=lineage,
                revision=1,
                payload_json=serialized,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
        else:
            if (row.kind, row.symbol, row.lineage) != (kind, symbol, lineage):
                raise ValueError("daily identity cannot change its semantic owner")
            row.revision += 1
            row.payload_json = serialized
            row.updated_at = now
        self.session.add(
            AuditLog(
                id=self.id_factory(),
                action="DAILY_" + kind + "_RECORDED",
                entity_type="DAILY_PLAN",
                entity_id=identity,
                before_hash=None if before is None else sha256(before.encode()).hexdigest(),
                after_hash=sha256(serialized.encode()).hexdigest(),
                details_json=canonical({"revision": row.revision}),
                created_at=now,
            )
        )
        self.session.flush()
        return self._value(row)

    def _value(self, row):
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("stored daily payload is invalid")
        from datetime import datetime

        from trade_plan_monitor.state.daily_state_models import validate_daily_payload

        validate_daily_payload(row.kind, payload)
        created, updated = (
            datetime.fromisoformat(row.created_at),
            datetime.fromisoformat(row.updated_at),
        )
        now = self.clock()
        if created.tzinfo is None or updated.tzinfo is None or not created <= updated <= now:
            raise ValueError("stored daily record timestamps are invalid or future")
        for key in ("available_at", "verified_at", "evaluated_at", "simulated_at"):
            if payload.get(key) is not None and datetime.fromisoformat(payload[key]) > now:
                raise ValueError("stored daily evidence is not yet available")
        return {
            "id": row.id,
            "kind": row.kind,
            "symbol": row.symbol,
            "lineage": row.lineage,
            "revision": row.revision,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "payload": payload,
        }
