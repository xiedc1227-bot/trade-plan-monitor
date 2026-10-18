"""Immutable historical factor evidence, separate from the legacy raw-market catalog."""

import sqlite3
from contextlib import closing
from datetime import date, datetime, time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime


class HistoricalAdjustmentFactor(ResearchValue):
    symbol: AShareSymbol
    trade_date: date
    factor: Decimal = Field(gt=0, allow_inf_nan=False)
    provider: Literal["TUSHARE"] = "TUSHARE"
    source: Literal["adj_factor"] = "adj_factor"
    availability_policy: Literal["HISTORICAL_SESSION_OPEN_V1"] = "HISTORICAL_SESSION_OPEN_V1"
    available_at: ShanghaiDatetime
    collected_at: ShanghaiDatetime

    @model_validator(mode="after")
    def chronology(self):
        if self.available_at < datetime.combine(self.trade_date, time(9, 30), SHANGHAI):
            raise ValueError("factor cannot precede its historical session opening")
        if self.collected_at < self.available_at:
            raise ValueError("factor collection cannot precede declared availability")
        return self

    @property
    def evidence_hash(self):
        return sha256(("historical-daily-factor-v1\0" + canonical_json(self)).encode()).hexdigest()


class DailyBasisStore:
    """Optional sidecar; frozen manifests copy evidence and never reread this mutable source.

    Historical availability is an explicit research convention. Collection time
    remains the real provider receipt time, not a claim of contemporaneous capture.
    Existing raw market databases and historical dataset identities stay readable.
    """

    def __init__(self, market_path):
        self.path = Path(str(market_path) + ".daily-basis.sqlite3")

    def record(self, values):
        checked = tuple(
            HistoricalAdjustmentFactor.model_validate_json(v.model_dump_json()) for v in values
        )
        if not checked:
            return
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS daily_factor ("
                "hash TEXT PRIMARY KEY, symbol TEXT NOT NULL, trade_date TEXT NOT NULL, "
                "collected_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT OR IGNORE INTO daily_factor VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        v.evidence_hash,
                        v.symbol,
                        str(v.trade_date),
                        v.collected_at.isoformat(),
                        canonical_json(v),
                    )
                    for v in checked
                ),
            )

    def read(self, symbol, start, end, *, cutoff=None):
        if not self.path.exists():
            return ()
        with closing(
            sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute(
                "SELECT hash, symbol, trade_date, collected_at, payload "
                "FROM daily_factor WHERE symbol=? AND trade_date BETWEEN ? AND ? "
                "ORDER BY trade_date, collected_at, hash",
                (symbol, str(start), str(end)),
            )
            selected = {}
            for digest, stored_symbol, day, collected, payload in rows:
                value = HistoricalAdjustmentFactor.model_validate_json(payload)
                if (
                    value.evidence_hash,
                    value.symbol,
                    str(value.trade_date),
                    value.collected_at.isoformat(),
                ) != (digest, stored_symbol, day, collected):
                    raise ValueError("historical factor evidence integrity failure")
                if cutoff is not None and value.available_at > cutoff:
                    continue
                previous = selected.get(value.trade_date)
                if (
                    previous
                    and previous.collected_at == value.collected_at
                    and previous.factor != value.factor
                ):
                    raise ValueError("conflicting historical factor evidence")
                selected[value.trade_date] = value
            return tuple(selected.values())


def factors_for_request(market, request):
    return DailyBasisStore(market.database_path).read(
        request.scope.symbols[0],
        request.scope.warmup_start,
        request.scope.end,
        cutoff=request.boundary.evidence_cutoff,
    )
