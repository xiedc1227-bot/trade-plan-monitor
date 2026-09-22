"""Fixed version-one stored inventory snapshots and source-linked audit receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from trade_plan_monitor.state.models import (
    AuditLog,
    PositionInventoryConfirmation,
    PositionOpeningBalance,
)


@dataclass(frozen=True)
class InventoryAuditSource:
    """Capture a flushed source before repository revision updates expire ORM state."""

    id: str
    action: str
    entity_type: str
    entity_id: str
    created_at: str
    occurred_at: datetime

    @classmethod
    def capture(cls, audit: AuditLog, occurred_at: datetime) -> InventoryAuditSource:
        return cls(
            audit.id,
            audit.action,
            audit.entity_type,
            audit.entity_id,
            audit.created_at,
            occurred_at,
        )


def confirmation_snapshot(row: PositionInventoryConfirmation | None) -> dict[str, object] | None:
    """Preserve stored timestamps and member JSON without DTO normalization."""
    if row is None:
        return None
    return {
        "symbol": row.symbol,
        "confirmation_id": row.confirmation_id,
        "as_of_trade_date": row.as_of_trade_date.isoformat(),
        "confirmed_at": row.confirmed_at,
        "inventory_revision": row.inventory_revision,
        "total_qty": row.total_qty,
        "sellable_qty": row.sellable_qty,
        "included_lot_ids_json": row.included_lot_ids_json,
        "opening_balance_ids_json": row.opening_balance_ids_json,
        "complete_registration": row.complete_registration,
    }


def opening_snapshot(row: PositionOpeningBalance) -> dict[str, object]:
    """Copy closure time without the public record's datetime normalization."""
    return {
        "id": row.id,
        "symbol": row.symbol,
        "original_qty": row.original_qty,
        "remaining_qty": row.remaining_qty,
        "sellable_from": row.sellable_from.isoformat(),
        "confirmation_id": row.confirmation_id,
        "revision": row.revision,
        "closed_at": row.closed_at,
    }


def inventory_change_audit(
    *,
    symbol: str,
    source: InventoryAuditSource,
    effective_trade_date: date,
    total_delta: int,
    sync_outcome: Literal["SYNCED", "MISSING", "STALE"],
    before: dict[str, object],
    after: dict[str, object],
) -> AuditLog:
    """Build a separate receipt without consuming an application ID or clock tick."""
    return AuditLog(
        id=str(uuid5(NAMESPACE_URL, "trade-plan-monitor:inventory-recovery:v1:" + source.id)),
        action="POSITION_INVENTORY_CHANGED",
        entity_type="POSITION_INVENTORY",
        entity_id=symbol,
        before_hash=sha256(_canonical_json(before).encode("utf-8")).hexdigest(),
        after_hash=sha256(_canonical_json(after).encode("utf-8")).hexdigest(),
        details_json=_canonical_json(
            {
                "recoveryEvidence": {
                    "schemaVersion": 1,
                    "sourceAudit": {
                        "id": source.id,
                        "action": source.action,
                        "entityType": source.entity_type,
                        "entityId": source.entity_id,
                    },
                    "effectiveTradeDate": effective_trade_date.isoformat(),
                    "totalDelta": total_delta,
                    "syncOutcome": sync_outcome,
                    "before": before,
                    "after": after,
                }
            }
        ),
        created_at=source.created_at,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
