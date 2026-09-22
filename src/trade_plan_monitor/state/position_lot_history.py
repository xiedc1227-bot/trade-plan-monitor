"""Bounded durable proof of one lot's history, without replay or send authority."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import LargeBinary, String, case, cast, func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.state.events import (
    MAX_PUBLIC_SEQUENCE,
    MonitorEventPayload,
    MonitorEventType,
    _canonical_json,
    monitor_event_id,
)
from trade_plan_monitor.state.models import AuditLog, MonitorSequence, PositionLot
from trade_plan_monitor.state.models import MonitorEvent as MonitorRow
from trade_plan_monitor.state.position_lot_evidence import (
    UnknownLotMutation,
    ValidatedLotMutation,
    _identifier,
    _require,
    _snapshot,
    _timestamp,
    decode_position_lot_mutation,
)
from trade_plan_monitor.state.recovery_read_session import require_owned_recovery_session
from trade_plan_monitor.state.repositories import PositionLotRecord, _position_lot_hash


class LotHistoryUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    HISTORY_LIMIT = "HISTORY_LIMIT"


@dataclass(frozen=True)
class UnknownLotHistory:
    reason: LotHistoryUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True)
class ProvenLotHistory:
    current_lot: PositionLotRecord
    mutations: tuple[ValidatedLotMutation, ...]
    publication_sequences: tuple[int, ...]
    high_water_sequence: int
    status: Literal["PROVEN"] = field(default="PROVEN", init=False)


class _MissingEvidence(ValueError):
    pass


# Text limits are UTF-8 bytes; identifier validators separately enforce characters.
_LOT = {
    "id": 512, "symbol": 9, "bucket": 16, "quantity": None, "remaining_qty": None,
    "acquired_trade_date": 10, "cost_fen": None, "related_alert_id": 144, "closed_at": 40,
}
_AUDIT = {
    "id": 512, "action": 64, "entity_type": 64, "entity_id": 512,
    "before_hash": 64, "after_hash": 64, "details_json": 16384, "created_at": 40,
}
_EVENT = {
    "id": 36, "sequence": None, "event_type": 64, "schema_version": None,
    "aggregate_id": 512, "payload_json": 4096, "occurred_at": 40,
}


def _bounded_query(model, fields):
    """Cap every stored value before fetching, including mistyped numeric cells."""
    columns = []
    for name, maximum in fields.items():
        column = getattr(model, name)
        if maximum is None:
            value = case((func.typeof(column) == "integer", column), else_=None)
        else:
            # Cast Date to String to prevent ORM coercion of a noncanonical stored date.
            value = func.substr(cast(cast(column, String), LargeBinary), 1, maximum + 1)
            columns.extend((
                func.length(cast(column, LargeBinary)).label(name + "_bytes"),
                func.instr(column, func.char(0)).label(name + "_nul"),
            ))
        columns.extend((value.label(name), func.typeof(column).label(name + "_type")))
    return select(*columns)


def _raw(row, fields, nullable=()):
    result = {}
    for name, maximum in fields.items():
        value, kind = row[name], row[name + "_type"]
        if kind == "null":
            _require(name in nullable)
        elif maximum is None:
            _require(kind == "integer" and type(value) is int)
        else:
            _require(kind == "text" and type(value) is bytes and row[name + "_nul"] == 0)
            _require(row[name + "_bytes"] == len(value) <= maximum)
            value = value.decode("utf-8")
        result[name] = value
    return result


def _highwater(session):
    fields = {"singleton_id": None, "last_sequence": None}
    rows = session.execute(_bounded_query(MonitorSequence, fields).limit(2)).mappings().all()
    if not rows:
        raise _MissingEvidence()
    _require(len(rows) == 1)
    row = _raw(rows[0], fields)
    highwater = row["last_sequence"]
    _require(row["singleton_id"] == 1 and 0 <= highwater <= MAX_PUBLIC_SEQUENCE)
    # Use the sequence index for the global maximum, not an aggregate over all rows.
    fields = {"sequence": None}
    maximum = session.execute(
        _bounded_query(MonitorRow, fields).order_by(MonitorRow.sequence.desc()).limit(1)
    ).mappings().one_or_none()
    if maximum is not None:
        _require(0 < _raw(maximum, fields)["sequence"] <= highwater)
    return highwater


def _chain(mutations):
    by_before = {}
    after_hashes = set()
    for mutation in mutations:
        _require(mutation.before_hash not in by_before)
        _require(mutation.after_hash not in after_hashes)
        by_before[mutation.before_hash] = mutation
        after_hashes.add(mutation.after_hash)
    _require(None in by_before)
    ordered = []
    previous = None
    while previous in by_before:
        mutation = by_before.pop(previous)
        ordered.append(mutation)
        previous = mutation.after_hash
    _require(not by_before)
    return tuple(ordered)


def _publications(rows, mutations, highwater):
    if not rows:
        raise _MissingEvidence()
    _require(len(rows) == len(mutations))
    sequences = []
    for row, mutation in zip(rows, mutations, strict=True):
        raw = _raw(row, _EVENT)
        after = mutation.after
        expected_payload = MonitorEventPayload(
            entity_id=after.id, symbol=after.symbol,
            status="CLOSED" if after.remaining_qty == 0 else "OPEN",
        ).model_dump(mode="json", by_alias=True, exclude_none=True)
        occurred = _timestamp(raw["occurred_at"])
        _require(
            raw["id"] == str(monitor_event_id(
                MonitorEventType.POSITION_UPDATED, after.id, str(after.remaining_qty),
            ))
            and raw["aggregate_id"] == after.id
            and raw["event_type"] == MonitorEventType.POSITION_UPDATED.value
            and raw["schema_version"] == 1
            and raw["payload_json"] == _canonical_json(expected_payload)
            and raw["occurred_at"] == occurred.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
            and occurred == mutation.created_at
            and (sequences[-1] if sequences else 0) < raw["sequence"] <= highwater
        )
        sequences.append(raw["sequence"])
    return tuple(sequences)


class PositionLotHistoryReader:
    """Own a fresh state.database configured SQLite session and explicit-BEGIN snapshot.

    The factory must bind every queried model to one application SQLite Engine,
    using its transaction hooks; externally owned Connection binds are rejected. No
    flush, commit, mutation, provider call, replay or notification is performed.
    Invalid stored evidence returns UNKNOWN; SQL and infrastructure errors propagate.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def read(
        self, lot_id: str, *, max_mutations: int = 256,
    ) -> ProvenLotHistory | UnknownLotHistory:
        _identifier(lot_id, 128)
        _require("\x00" not in lot_id)
        if type(max_mutations) is not int or not 1 <= max_mutations <= 1000:
            raise ValueError("max_mutations must be an integer between 1 and 1000")
        session = self._session_factory()
        require_owned_recovery_session(
            session, (MonitorSequence, MonitorRow, AuditLog, PositionLot),
        )
        with session, session.no_autoflush:
            try:
                return self._read(session, lot_id, max_mutations)
            except _MissingEvidence:
                return UnknownLotHistory(LotHistoryUnknownReason.MISSING_EVIDENCE)
            except ValueError, TypeError, RecursionError, OverflowError:
                return UnknownLotHistory(LotHistoryUnknownReason.INVALID_EVIDENCE)

    @staticmethod
    def _read(session, lot_id, maximum):
        highwater = _highwater(session)
        audits = session.execute(
            _bounded_query(AuditLog, _AUDIT).where(
                AuditLog.entity_type == "POSITION_LOT", AuditLog.entity_id == lot_id,
            ).limit(maximum + 1)
        ).mappings().all()
        events = session.execute(
            _bounded_query(MonitorRow, _EVENT).where(MonitorRow.aggregate_id == lot_id)
            .order_by(MonitorRow.sequence).limit(maximum + 1)
        ).mappings().all()
        if max(len(audits), len(events)) > maximum:
            return UnknownLotHistory(LotHistoryUnknownReason.HISTORY_LIMIT)
        current = session.execute(
            _bounded_query(PositionLot, _LOT).where(PositionLot.id == lot_id).limit(1)
        ).mappings().one_or_none()
        if current is None or not audits:
            raise _MissingEvidence()
        current_lot = _snapshot(_raw(current, _LOT, ("related_alert_id", "closed_at")))
        mutations = []
        for row in audits:
            raw = _raw(row, _AUDIT, ("before_hash", "after_hash"))
            _identifier(raw.pop("id"), 128)
            mutation = decode_position_lot_mutation(**raw)
            if isinstance(mutation, UnknownLotMutation):
                return UnknownLotHistory(LotHistoryUnknownReason(mutation.reason.value))
            mutations.append(mutation)
        ordered = _chain(mutations)
        _require(ordered[-1].after_hash == _position_lot_hash(current_lot))
        sequences = _publications(events, ordered, highwater)
        return ProvenLotHistory(current_lot, ordered, sequences, highwater)
