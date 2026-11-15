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


def buy_suspension_record_id(symbol, owner_plan_version_id):
    """Original server-resolved owner only; an ID conveys no activation authority."""
    return "buy-suspension-" + daily_hash(
        "buy-suspension-owner-v1", [symbol, owner_plan_version_id])


class DailyRepository:
    def __init__(self, session, *, clock, id_factory):
        self.session = session
        self.clock = clock
        self.id_factory = id_factory
        # Only a writable participant can own invalidation and its audit IDs.
        # Temporary read repositories must neither claim nor replace that owner.
        if callable(id_factory):
            session.info["buy_suspension_repository"] = self

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

    def get_buy_suspension(self, *, symbol, owner_plan_version_id):
        """Read actual private state/revision; never resolve or authorize an owner here."""
        identity = buy_suspension_record_id(symbol, owner_plan_version_id)
        row = self.session.scalar(select(DailyRecord).where(DailyRecord.id == identity)
                                  .execution_options(populate_existing=True))
        if row is None:
            return None
        if (row.kind, row.symbol, row.lineage) != (
                "BUY_SUSPENSION", symbol, owner_plan_version_id):
            raise ValueError("suspension lookup crosses its original owner")
        value = self._value(row)
        from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState

        state = DailyBuySuspensionState.model_validate(value["payload"])
        return value | {"state": state, "state_hash": state.state_hash}

    def invalidate_buy_suspension_market(self, *, start, end, symbol=None,
                                         exchange=None, factor=None):
        """Revoke affected compact prefixes under the same SQLite writer fence.

        A comparable prefix proved every source factor equal to its anchor;
        observing that same actual factor does not invalidate it endlessly.
        """
        from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState

        statement = select(DailyRecord).where(DailyRecord.kind == "BUY_SUSPENSION")
        if symbol is not None:
            self.lock_symbol(symbol)
            statement = statement.where(DailyRecord.symbol == symbol)
        else:
            self.session.execute(update(DailyRecord).where(
                DailyRecord.kind == "BUY_SUSPENSION").values(revision=DailyRecord.revision))
        offset = 0
        while True:
            rows = self.session.scalars(statement.order_by(DailyRecord.id).offset(offset)
                .limit(100).execution_options(populate_existing=True)).all()
            for row in rows:
                state = DailyBuySuspensionState.model_validate_json(row.payload_json)
                if exchange is not None and {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[
                        state.symbol[-2:]] != exchange:
                    continue
                if (state.trigger is not None or state.coverage is None
                        or end <= state.definition.effective_from or start > state.coverage.through
                        or factor is not None and factor == state.coverage.anchor_factor):
                    continue
                invalid = state.model_copy(update={"coverage": None, "blocker": "PROOF_INVALIDATED",
                    "evaluated_at": max(state.evaluated_at, self.clock())})
                self.save(row.id, kind=row.kind, symbol=row.symbol, lineage=row.lineage,
                    payload=invalid.model_dump(mode="json"), expected_revision=row.revision)
            if len(rows) < 100:
                return
            offset += len(rows)

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
        row = (self.session.scalar(select(DailyRecord).where(DailyRecord.id == identity)
                                   .execution_options(populate_existing=True))
               if kind == "BUY_SUSPENSION" else self.session.get(DailyRecord, identity))
        if kind == "BUY_SUSPENSION":
            self._validate_buy_suspension_owner(identity, symbol, lineage, payload)
            if type(expected_revision) is not int or expected_revision < 0:
                raise ValueError("suspension requires an exact expected revision")
            if row is not None:
                self._validate_buy_suspension_update(row.payload_json, payload)
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
        if row.kind == "BUY_SUSPENSION":
            self._validate_buy_suspension_owner(row.id, row.symbol, row.lineage, payload)
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

    @staticmethod
    def _validate_buy_suspension_owner(identity, symbol, lineage, payload):
        if (payload["symbol"] != symbol or payload["owner_plan_version_id"] != lineage
                or identity != buy_suspension_record_id(symbol, lineage)):
            raise ValueError("suspension record differs from its actual original owner")

    def retarget_buy_suspension_calendar(self, state, *, target, evaluated_at):
        """Reset only revoked proof whose former target date is now SQL-proven closed.

        This is not the reducer's ordinary observation transition. The original
        interval/owner remain intact and the replacement target has no coverage.
        """
        from datetime import datetime, time

        from trade_plan_monitor.state.models import TradingCalendar

        now = self.clock()
        if (state.trigger is not None or state.coverage is not None
                or state.blocker not in {"PROOF_INVALIDATED", "CALENDAR_UNVERIFIED"}
                or target >= state.target or evaluated_at < state.evaluated_at
                or evaluated_at > now):
            return None
        self.lock_symbol(state.symbol)
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[state.symbol[-2:]]
        rows = self.session.scalars(select(TradingCalendar).where(
            TradingCalendar.exchange == exchange,
            TradingCalendar.cal_date.in_({now.date(), state.target.date()})
        ).execution_options(populate_existing=True)).all()
        days = {day.cal_date: day for day in rows}
        former, today = days.get(state.target.date()), days.get(now.date())
        if (former is None or former.is_open or today is None
                or today.is_open and now.time() >= time(9, 30)):
            return None
        previous = self.session.scalar(select(TradingCalendar).where(
            TradingCalendar.exchange == exchange,
            TradingCalendar.cal_date == today.previous_trade_date
        ).execution_options(populate_existing=True))
        if (previous is None or not previous.is_open or target != datetime.combine(
                previous.cal_date, time(15), now.tzinfo)):
            return None
        return state.model_copy(update={"target": target, "evaluated_at": evaluated_at,
            "coverage": None, "blocker": "HISTORY_PENDING"})

    def _validate_buy_suspension_update(self, before_json, payload):
        from trade_plan_monitor.state.daily_state_models import DailyBuySuspensionState

        before = DailyBuySuspensionState.model_validate_json(before_json)
        after = DailyBuySuspensionState.model_validate(payload)
        for field in ("symbol", "owner_plan_version_id", "content_hash", "source_hash", "review_id",
                      "birth_activation_revision", "definition"):
            if getattr(before, field) != getattr(after, field):
                raise ValueError("suspension original owner and definition cannot change")
        if before.trigger is not None and before.trigger != after.trigger:
            raise ValueError("suspension latch evidence cannot be cleared or replaced")
        if before.evaluated_at > after.evaluated_at:
            raise ValueError("suspension observation cannot move backwards")
        if before.target > after.target and self.retarget_buy_suspension_calendar(
                before, target=after.target, evaluated_at=after.evaluated_at) != after:
            raise ValueError(
                "suspension target requires a revoked proof and actual revised calendar")
