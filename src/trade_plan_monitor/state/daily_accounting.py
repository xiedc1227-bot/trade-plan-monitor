"""Isolated whole-lot simulation inventory; no shared actual-position access."""

import json
from datetime import date, datetime

from sqlalchemy import case, func, or_, select, text

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.repositories import RevisionConflictError

SIMULATION_VERSION = "daily-simulation-v1"
LEGACY_UNSUPPORTED = "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"


class DailyAccounting:
    def __init__(self, repository):
        self.repo = repository

    def legacy_reason(self, symbol):
        """Recognize preserved development data without validating or converting it."""
        layout = self.repo.session.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_plan_record'"
        )).scalar_one_or_none()
        if layout is not None and "'SIMULATION'" not in layout:
            return LEGACY_UNSUPPORTED
        # Keep malformed/non-object values for the original Python checks below.
        # Current evaluation history needs no Python JSON decoding just to find an old marker.
        payload = DailyRecord.payload_json
        fields = func.json_each(payload).table_valued("key")
        inventory_keys = select(func.count()).select_from(fields).where(
            fields.c.key == "inventory",
        ).scalar_subquery()
        evaluation_candidate = case(
            (func.json_valid(payload).is_not(1), True),
            (func.json_type(payload) != "object", True),
            (inventory_keys > 1, True),  # Python resolves duplicate keys to the last value.
            (func.json_type(payload, "$.inventory").is_(None), False),
            (func.json_type(payload, "$.inventory") != "object", True),
            else_=func.json_type(payload, "$.inventory.orders").is_not(None),
        )
        rows = self.repo.session.execute(
            select(DailyRecord.kind, DailyRecord.payload_json).where(
                DailyRecord.symbol == symbol,
                DailyRecord.kind.in_(("REPORT", "POSITION", "SIGNAL", "EVALUATION", "RISK")),
                or_(DailyRecord.kind != "EVALUATION", evaluation_candidate),
            )
        ).yield_per(100)
        for kind, serialized in rows:
            value = json.loads(serialized)
            if (
                kind == "REPORT"
                or kind == "RISK"
                and any(
                    type(value.get(k)) is not int or value[k] < 0 or value[k] % 100
                    for k in ("target_core_qty", "target_tactical_qty")
                )
                or kind == "POSITION"
                and value.get("simulation_version") != SIMULATION_VERSION
                or kind == "SIGNAL"
                and "simulated_qty" not in value
                or kind == "EVALUATION"
                and "orders" in value.get("inventory", {})
            ):
                return LEGACY_UNSUPPORTED
        return None

    def obsolete_risks(self, symbol):
        """Bounded technical history summary carries no quantity/execution authority."""
        from trade_plan_monitor.state.daily_state_models import DailyObsoleteRisk

        results = []
        serialized = self.repo.session.scalars(select(DailyRecord.payload_json).where(
            DailyRecord.symbol == symbol, DailyRecord.kind == "RISK"
        ).order_by(DailyRecord.updated_at.desc()).limit(2))
        for raw in serialized:
            value = json.loads(raw)
            try:
                summary = DailyObsoleteRisk.model_validate_json(json.dumps({
                    "risk_id": value.get("risk_id"), "kind": value.get("kind"),
                    "status": value.get("status"),
                    "confirmed_trade_date": value.get("confirmed_trade_date"),
                    "scope_evidence": value.get("scope_evidence", "")[:2000],
                }))
            except ValueError:
                continue
            results.append(summary.model_dump(mode="json"))
        return tuple(results)

    def has_latched_risk(self, symbol):
        if self.legacy_reason(symbol):
            return False
        return any(r["payload"]["status"] in {"PENDING", "CONFIRMED"}
                   for r in self.repo.list(symbol=symbol, kind="RISK"))

    def evaluation_current(self, snapshot, *, plan_version_id, content_hash, inventory, now,
                           require_daily_data):
        """Shared simulation/delivery fence over current facts and simulated inventory."""
        if (snapshot.get("plan_version_id") != plan_version_id
            or snapshot.get("content_hash") != content_hash
            or snapshot.get("inventory", {}).get("revision") != inventory["revision"]
            or require_daily_data and snapshot.get("data_blockers")):
            return False
        facts = [r for r in self.repo.list(symbol=inventory["symbol"], kind="FACT")
            if r["payload"]["plan_version_id"] == plan_version_id
            and r["payload"]["content_hash"] == content_hash
            and datetime.fromisoformat(r["payload"]["available_at"]) <= now]
        return [(r["id"], r["revision"]) for r in facts] == [
            (r["id"], r["revision"]) for r in snapshot.get("fact_revisions", ())]

    def _position(self, symbol):
        return self.repo.get("simulation-position-" + symbol)

    def lots(self, symbol, trade_date):
        row = self._position(symbol)
        if row is None:
            return ()
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[symbol[-2:]]
        current = self.repo.session.get(TradingCalendar, (exchange, trade_date))
        return tuple({**batch, "sellable_quantity": (
            self._available(batch, trade_date, exchange)
            if current is not None and current.is_open else None)}
            for batch in row["payload"]["batches"])

    def snapshot(self, symbol, trade_date):
        row = self._position(symbol)
        result = {"symbol": symbol, "revision": 0 if row is None else row["revision"],
                  "known": row is not None, "total_qty": None, "core_qty": None,
                  "tactical_qty": None, "sellable_core": None, "sellable_tactical": None}
        if row is None:
            return result
        batches = row["payload"]["batches"]
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[symbol[-2:]]
        current = self.repo.session.get(TradingCalendar, (exchange, trade_date))
        for bucket in ("core", "tactical"):
            own = [b for b in batches if b["bucket"] == bucket.upper()]
            result[bucket + "_qty"] = sum(b["quantity"] for b in own)
            available = [self._available(b, trade_date, exchange) for b in own]
            result["sellable_" + bucket] = (
                None if current is None or not current.is_open or None in available
                else sum(available)
            )
        result["total_qty"] = result["core_qty"] + result["tactical_qty"]
        return result

    def _settled(self, batch, day, exchange):
        acquired = date.fromisoformat(batch["acquired_trade_date"])
        if batch["baseline"]:
            return acquired <= day
        proof = self.repo.session.get(TradingCalendar, (exchange, acquired))
        return acquired < day and proof is not None and proof.is_open

    def _available(self, batch, day, exchange):
        if batch.get("origin") != "monitor-loop-opening-v1":
            return batch["quantity"] if self._settled(batch, day, exchange) else 0
        observed = date.fromisoformat(batch["observed_trade_date"])
        if day < observed:
            return None
        explicit = batch["sellable_quantity"]
        if batch["acquired_trade_date"] is None:
            return explicit
        if day == observed and explicit is not None:
            return explicit
        acquired = date.fromisoformat(batch["acquired_trade_date"])
        proof = self.repo.session.get(TradingCalendar, (exchange, acquired))
        if acquired >= day:
            return 0
        return batch["quantity"] if proof is not None and proof.is_open else None

    def initialize(self, *, symbol, core_qty, tactical_qty, expected_revision, now):
        self.repo.lock_symbol(symbol)
        row = self._position(symbol)
        if row is not None:
            payload = row["payload"]
            if (payload["initial_core_qty"], payload["initial_tactical_qty"]) == (
                core_qty,
                tactical_qty,
            ):
                return row
            raise RevisionConflictError(row["revision"])
        if expected_revision != 0:
            raise RevisionConflictError(0)
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[symbol[-2:]]
        first = self.repo.session.scalar(select(TradingCalendar.cal_date).where(
            TradingCalendar.exchange == exchange, TradingCalendar.is_open.is_(True),
            TradingCalendar.cal_date >= now.date(),
        ).order_by(TradingCalendar.cal_date).limit(1))
        if first is None:
            raise ValueError("TRADING_CALENDAR_MISSING")
        return self.repo.save(
            "simulation-position-" + symbol,
            kind="POSITION",
            symbol=symbol,
            lineage=symbol,
            expected_revision=0,
            payload={
                "simulation_version": SIMULATION_VERSION,
                "initialized_at": now.isoformat(),
                "initial_core_qty": core_qty,
                "initial_tactical_qty": tactical_qty,
                "batches": [
                    {
                        "id": "initial-" + bucket,
                        "bucket": bucket,
                        "quantity": quantity,
                        "acquired_trade_date": str(first),
                        "baseline": True,
                    }
                    for bucket, quantity in (("CORE", core_qty), ("TACTICAL", tactical_qty))
                    if quantity
                ],
            },
        )

    def simulate(self, *, symbol, identity, side, quantities, expected_revision, now,
                 lot_allocations=None, plan_version_id=None):
        """Apply the server-authorized full quantity; only acquisition-day batches persist."""
        row = self._position(symbol)
        if row is None or row["revision"] != expected_revision:
            raise RevisionConflictError(0 if row is None else row["revision"])
        payload = row["payload"]
        batches = [dict(b) for b in payload["batches"]]
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[symbol[-2:]]
        allocations = None
        if lot_allocations is not None:
            allocations = {(a["id"], a["bucket"]): a["quantity"] for a in lot_allocations}
            keys = {(b["id"], b["bucket"]) for b in batches}
            if (len(allocations) != len(lot_allocations) or not allocations.keys() <= keys
                or any(type(q) is not int or q <= 0 or q % 100 for q in allocations.values())
                or side != "SELL" or any(sum(q for (_, b), q in allocations.items() if b == bucket)
                    != quantity for bucket, quantity in quantities.items())):
                raise ValueError("RISK_LOT_ALLOCATION_CHANGED")
        for bucket, quantity in quantities.items():
            if quantity == 0:
                continue
            if side == "BUY":
                batches.append({"id": identity, "bucket": bucket, "quantity": quantity,
                    "acquired_trade_date": str(now.date()), "baseline": False,
                    **({"plan_version_id": plan_version_id} if plan_version_id else {})})
            else:
                left = quantity
                for batch in sorted(
                    batches, key=lambda b: (b["acquired_trade_date"] or "", b["id"]), reverse=True
                ):
                    available = self._available(batch, now.date(), exchange)
                    if batch["bucket"] != bucket or not available:
                        continue
                    debit = (min(left, available) if allocations is None
                        else allocations.get((batch["id"], bucket), 0))
                    if debit > available or debit > left:
                        raise ValueError("RISK_LOT_ALLOCATION_CHANGED")
                    batch["quantity"] -= debit
                    if batch.get("origin") == "monitor-loop-opening-v1" and (
                        batch["sellable_quantity"] is not None
                    ):
                        batch["sellable_quantity"] = max(0, batch["sellable_quantity"] - debit)
                    left -= debit
                    if not left:
                        break
                if left:
                    raise ValueError("TACTICAL_OR_CORE_SETTLED_QUANTITY_INSUFFICIENT")
        return self.repo.save(row["id"], kind="POSITION", symbol=symbol, lineage=symbol,
            expected_revision=expected_revision,
            payload={**payload, "batches": [b for b in batches if b["quantity"]]})
