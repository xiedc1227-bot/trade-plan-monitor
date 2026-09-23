"""Read registered inventory at a historical cutoff from one bounded SQLite snapshot.

Alerts are not executions. Only durable inventory mutations change quantities;
their registration time, not a backdated trade date, selects the historical prefix.
This proof does not itself authorize replay, delivery, or complete-account claims.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, and_, cast, or_
from sqlalchemy.orm import Session

from trade_plan_monitor.state.events import (
    MonitorEventPayload,
    MonitorEventType,
    _canonical_json,
    monitor_event_id,
)
from trade_plan_monitor.state.inventory_evidence import (
    InventoryConfirmationSnapshot,
    _confirmation,
    _id,
    decode_inventory_mutation,
)
from trade_plan_monitor.state.models import (
    AuditLog,
    MonitorEvent,
    MonitorSequence,
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionLot,
    PositionOpeningBalance,
)
from trade_plan_monitor.state.opening_balance_evidence import (
    OpeningBalanceEvidenceSnapshot,
    decode_opening_balance_mutation,
)
from trade_plan_monitor.state.opening_balance_evidence import _snapshot as _opening_snapshot
from trade_plan_monitor.state.position_lot_evidence import (
    _require,
    _snapshot,
    _timestamp,
    decode_position_lot_mutation,
)
from trade_plan_monitor.state.position_lot_history import (
    _AUDIT,
    _EVENT,
    _LOT,
    _bounded_query,
    _highwater,
    _MissingEvidence,
    _raw,
)
from trade_plan_monitor.state.recovery_read_session import require_owned_recovery_session
from trade_plan_monitor.state.repositories import PositionLotRecord, _symbol

_MAX_ROWS = 256
_MAX_BYTES = 8388608
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_INVENTORY_AUDIT = _AUDIT | {"details_json": 262144, "created_at": 64}
_SOURCE_AUDIT = _AUDIT | {"created_at": 64}
_LOTS = _LOT | {"closed_at": 64, "related_alert_id": 512}
_OPENING = {
    "id": 144, "symbol": 9, "original_qty": None, "remaining_qty": None,
    "sellable_from": 10, "confirmation_id": 512, "revision": None, "closed_at": 64,
}
_CONFIRMATION = {
    "symbol": 9, "confirmation_id": 512, "as_of_trade_date": 10, "confirmed_at": 64,
    "inventory_revision": None, "total_qty": None, "sellable_qty": None,
    "included_lot_ids_json": 65536, "opening_balance_ids_json": 65536,
    "complete_registration": None,
}
_ID_FIELDS = {"id", "entity_id", "aggregate_id", "confirmation_id", "related_alert_id"}


class InventoryHistoryUnknownReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    HISTORY_LIMIT = "HISTORY_LIMIT"


@dataclass(frozen=True)
class UnknownInventoryHistory:
    reason: InventoryHistoryUnknownReason
    status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)


@dataclass(frozen=True)
class ProvenInventoryHistory:
    symbol: str
    cutoff: datetime
    observed_at: datetime
    inventory_revision: int
    current_revision: int
    position_lots: tuple[PositionLotRecord, ...]
    opening_balances: tuple[OpeningBalanceEvidenceSnapshot, ...]
    confirmation: InventoryConfirmationSnapshot | None
    high_water_sequence: int
    status: Literal["PROVEN"] = field(default="PROVEN", init=False)


class _HistoryLimit(ValueError):
    pass


class _UnknownEvidence(ValueError):
    def __init__(self, reason):
        self.reason = (InventoryHistoryUnknownReason.HISTORY_LIMIT if reason == "EVIDENCE_LIMIT"
                       else InventoryHistoryUnknownReason(reason))


class _ReadBudget:
    def __init__(self):
        self.bytes = 0

    def rows(self, session, query, fields, nullable=()):
        """Limit SQL values and cumulative decoded bytes before retaining records."""
        result = []
        for row in session.execute(query.limit(_MAX_ROWS + 1)).mappings():
            if len(result) == _MAX_ROWS:
                raise _HistoryLimit()
            self.bytes += sum(len(row[name]) for name, limit in fields.items()
                              if limit is not None and isinstance(row[name], bytes))
            if self.bytes > _MAX_BYTES:
                raise _HistoryLimit()
            compatible = dict(row)
            # Existing writers allow NUL inside opaque identifiers. Byte lengths
            # and strict UTF-8 still protect against truncation and malformed text.
            for name in _ID_FIELDS & fields.keys():
                compatible[name + "_nul"] = 0
            raw = _raw(compatible, fields, nullable)
            for name in _ID_FIELDS & raw.keys():
                if raw[name] is not None:
                    _id(raw[name])
            result.append(raw)
        return result


def _validated(value):
    if value.status == "UNKNOWN":
        raise _UnknownEvidence(value.reason)
    return value


def _publication(raw, mutation, written, previous, highwater):
    after = mutation.after
    expected = MonitorEventPayload(
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
        and raw["payload_json"] == _canonical_json(expected)
        and raw["occurred_at"] == occurred.astimezone(_SHANGHAI).isoformat()
        and occurred == written
        and previous < raw["sequence"] <= highwater
    )
    return raw["sequence"]


def _confirmed_members(confirmation, lots, openings):
    """Check membership only at confirmation; SYNCED retains original metadata."""
    active_lots = {key: lot for key, lot in lots.items() if lot.remaining_qty}
    active_openings = {key: balance for key, balance in openings.items() if balance.remaining_qty}
    _require(set(confirmation.included_lot_ids) == active_lots.keys())
    _require(set(confirmation.opening_balance_ids) == active_openings.keys())
    _require(confirmation.total_qty == sum(item.remaining_qty for item in (
        *active_lots.values(), *active_openings.values(),
    )))
    sellable = sum(lot.remaining_qty for lot in active_lots.values()
                   if lot.acquired_trade_date < confirmation.as_of_trade_date)
    sellable += sum(balance.remaining_qty for balance in active_openings.values()
                    if balance.sellable_from <= confirmation.as_of_trade_date)
    _require(confirmation.sellable_qty == sellable)


class PositionInventoryHistoryReader:
    """Own a fresh application SQLite session; never flush, mutate, or send.

    Invalid evidence is UNKNOWN. Infrastructure failures and invalid caller/session
    contracts propagate. Use the explicit-BEGIN engine from state.database.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def read(self, symbol: str, *, cutoff: datetime, observed_at: datetime
             ) -> ProvenInventoryHistory | UnknownInventoryHistory:
        _symbol(symbol)
        for value in (cutoff, observed_at):
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError("Inventory history requires aware timestamps")
        _require(cutoff <= observed_at)
        session = self._session_factory()
        require_owned_recovery_session(session, (
            PositionInventoryState, PositionInventoryConfirmation, PositionLot,
            PositionOpeningBalance, AuditLog, MonitorEvent, MonitorSequence,
        ))
        with session:
            return self.read_in_session(session, symbol, cutoff=cutoff, observed_at=observed_at)

    @staticmethod
    def read_in_session(
        session: Session, symbol: str, *, cutoff: datetime, observed_at: datetime,
    ) -> ProvenInventoryHistory | UnknownInventoryHistory:
        """Validate current manual holdings inside a caller-owned snapshot."""

        _symbol(symbol)
        with session.no_autoflush:
            try:
                return PositionInventoryHistoryReader._read(session, symbol, cutoff, observed_at)
            except _HistoryLimit:
                return UnknownInventoryHistory(InventoryHistoryUnknownReason.HISTORY_LIMIT)
            except _MissingEvidence:
                return UnknownInventoryHistory(InventoryHistoryUnknownReason.MISSING_EVIDENCE)
            except _UnknownEvidence as error:
                return UnknownInventoryHistory(error.reason)
            except ValueError, TypeError, RecursionError, OverflowError:
                return UnknownInventoryHistory(InventoryHistoryUnknownReason.INVALID_EVIDENCE)

    @staticmethod
    def _read(session, symbol, cutoff, observed_at):
        budget = _ReadBudget()
        state_fields = {"symbol": 9, "revision": None}
        states = budget.rows(session, _bounded_query(PositionInventoryState, state_fields).where(
            PositionInventoryState.symbol == symbol,
        ), state_fields)
        if not states:
            raise _MissingEvidence()
        current_revision = states[0]["revision"]
        _require(current_revision >= 0)
        if current_revision > _MAX_ROWS:
            raise _HistoryLimit()
        confirmation_query = _bounded_query(PositionInventoryConfirmation, _CONFIRMATION)
        # Preserve the stored integer instead of Boolean's permissive ORM coercion.
        confirmation_query = confirmation_query.with_only_columns(*(
            cast(column, Integer).label(column.key) if column.key == "complete_registration"
            else column for column in confirmation_query.selected_columns
        ))
        confirmations = budget.rows(session, confirmation_query.where(
            PositionInventoryConfirmation.symbol == symbol,
        ), _CONFIRMATION)
        current_confirmation = None
        if confirmations:
            raw = confirmations[0]
            _require(raw["complete_registration"] == 1)
            current_confirmation = _confirmation(raw | {"complete_registration": True}, symbol)
        current_lots = {
            row["id"]: _snapshot(row) for row in budget.rows(
                session, _bounded_query(PositionLot, _LOTS).where(PositionLot.symbol == symbol),
                _LOTS, ("related_alert_id", "closed_at"),
            )
        }
        current_openings = {
            row["id"]: _opening_snapshot(row) for row in budget.rows(
                session, _bounded_query(PositionOpeningBalance, _OPENING).where(
                    PositionOpeningBalance.symbol == symbol,
                ), _OPENING, ("closed_at",),
            )
        }
        receipts = []
        lot_ids, opening_ids = set(current_lots), set(current_openings)
        for raw in budget.rows(session, _bounded_query(AuditLog, _INVENTORY_AUDIT).where(
            AuditLog.entity_type == "POSITION_INVENTORY", AuditLog.entity_id == symbol,
        ), _INVENTORY_AUDIT, ("before_hash", "after_hash")):
            receipt = _validated(decode_inventory_mutation(audit_id=raw.pop("id"), **raw))
            receipts.append(receipt)
            if receipt.created_opening_balance is not None:
                opening_ids.add(receipt.created_opening_balance.id)
            if receipt.source_audit is not None:
                target = (lot_ids if receipt.source_audit.entity_type == "POSITION_LOT"
                          else opening_ids)
                target.add(receipt.source_audit.entity_id)
        if len(lot_ids) + len(opening_ids) > _MAX_ROWS:
            raise _HistoryLimit()
        _require(not lot_ids.intersection(opening_ids))
        if len(receipts) != current_revision:
            raise _MissingEvidence()
        sources = {row["id"]: row for row in budget.rows(
            session, _bounded_query(AuditLog, _SOURCE_AUDIT).where(or_(
                and_(AuditLog.entity_type == "POSITION_LOT", AuditLog.entity_id.in_(lot_ids)),
                and_(AuditLog.entity_type == "POSITION_OPENING_BALANCE",
                     AuditLog.entity_id.in_(opening_ids)),
            )), _SOURCE_AUDIT, ("before_hash", "after_hash"),
        )}
        publications = budget.rows(session, _bounded_query(MonitorEvent, _EVENT).where(
            MonitorEvent.aggregate_id.in_(lot_ids | opening_ids),
        ).order_by(MonitorEvent.sequence), _EVENT)
        highwater = _highwater(session)
        return _reconstruct(symbol, cutoff, observed_at, current_revision, receipts, sources,
                            publications, highwater, current_lots, current_openings,
                            current_confirmation)


def _reconstruct(symbol, cutoff, observed_at, current_revision, receipts, sources,
                 publications, highwater, current_lots, current_openings, current_confirmation):
    lots, openings = {}, {}
    confirmation = None
    selected_lots, selected_openings, selected_confirmation, selected_revision = (), (), None, 0
    last_written, sequence, publication_index = None, 0, 0
    cutoff_day = cutoff.astimezone(_SHANGHAI).date()
    for revision, receipt in enumerate(sorted(receipts, key=lambda item: item.previous_revision)):
        _require(receipt.previous_revision == revision and receipt.before == confirmation)
        written = _timestamp(receipt.created_at)
        _require(written <= observed_at and (last_written is None or last_written <= written))
        last_written = written
        if receipt.source_audit is None:
            opening = receipt.created_opening_balance
            if opening is not None:
                _require(opening.id not in openings)
                openings[opening.id] = opening
            _confirmed_members(receipt.after, lots, openings)
        else:
            source = receipt.source_audit
            if source.id not in sources:
                raise _MissingEvidence()
            raw = sources.pop(source.id)
            _require(all(raw[key] == getattr(source, key)
                         for key in ("id", "action", "entity_type", "entity_id")))
            raw.pop("id")
            decoder, ledger = (decode_position_lot_mutation, lots) if (
                source.entity_type == "POSITION_LOT"
            ) else (decode_opening_balance_mutation, openings)
            mutation = _validated(decoder(**raw))
            _require(raw["created_at"] == receipt.created_at)
            _require(mutation.after.symbol == symbol)
            _require(mutation.effective_trade_date == receipt.effective_trade_date)
            _require(ledger.get(source.entity_id) == mutation.before)
            old_quantity = 0 if mutation.before is None else mutation.before.remaining_qty
            _require(mutation.after.remaining_qty - old_quantity == receipt.total_delta)
            ledger[source.entity_id] = mutation.after
            if mutation.after.closed_at is not None:
                closed = mutation.after.closed_at
                closed_time = closed if isinstance(closed, datetime) else _timestamp(closed)
                _require(closed_time <= observed_at)
            if publication_index >= len(publications):
                raise _MissingEvidence()
            sequence = _publication(publications[publication_index], mutation, written,
                                    sequence, highwater)
            publication_index += 1
        confirmation = receipt.after
        if written <= cutoff:
            _require(receipt.effective_trade_date <= cutoff_day)
            selected_lots = tuple(lot for _, lot in sorted(lots.items()) if lot.remaining_qty)
            selected_openings = tuple(
                item for _, item in sorted(openings.items()) if item.remaining_qty
            )
            _require(all(lot.acquired_trade_date <= cutoff_day for lot in selected_lots))
            _require(all(item.sellable_from <= cutoff_day for item in selected_openings))
            selected_confirmation, selected_revision = confirmation, receipt.next_revision
    _require(not sources and publication_index == len(publications))
    _require(lots == current_lots and openings == current_openings)
    _require(confirmation == current_confirmation)
    return ProvenInventoryHistory(
        symbol, cutoff, observed_at, selected_revision, current_revision,
        selected_lots, selected_openings, selected_confirmation, highwater,
    )
