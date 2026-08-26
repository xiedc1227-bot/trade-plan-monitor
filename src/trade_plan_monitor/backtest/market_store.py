"""Content-addressed SQLite storage for immutable historical market facts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import (
    DATASET_SCHEMA_VERSION,
    DatasetFreezeResult,
    DatasetItem,
    DatasetManifest,
    DatasetScope,
    MarketStoreStatistics,
    exchange_for_symbol,
)
from trade_plan_monitor.backtest.migration import (
    MigrationInventory,
    inspect_market_database,
    require_safe_store_initialization,
)
from trade_plan_monitor.backtest.storage_guard import reject_incompatible_database
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteBatch
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay

_ArtifactKind = Literal["CALENDAR", "MINUTE", "LIMIT", "DAILY"]
_MarketValue = TypeVar("_MarketValue", bound=BaseModel)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_MANIFEST_CACHE = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_artifact (
    artifact_hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
    provider TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_artifact_natural_key
    ON market_artifact (natural_key, created_at);

CREATE TABLE IF NOT EXISTS market_head (
    natural_key TEXT PRIMARY KEY,
    artifact_hash TEXT NOT NULL REFERENCES market_artifact (artifact_hash),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
    symbol TEXT,
    trade_date TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_head_kind_symbol_date
    ON market_head (kind, symbol, trade_date);

CREATE TABLE IF NOT EXISTS market_minute_artifact (
    artifact_hash TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    bar_end TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_minute_artifact_symbol_end
    ON market_minute_artifact (symbol, bar_end, artifact_hash);

CREATE TABLE IF NOT EXISTS market_minute_head (
    symbol TEXT NOT NULL,
    bar_end TEXT NOT NULL,
    artifact_hash TEXT NOT NULL
        REFERENCES market_minute_artifact (artifact_hash) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (symbol, bar_end)
);
CREATE INDEX IF NOT EXISTS ix_market_minute_head_end
    ON market_minute_head (bar_end, symbol);

CREATE TABLE IF NOT EXISTS market_dataset (
    dataset_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_dataset_item (
    dataset_hash TEXT NOT NULL REFERENCES market_dataset (dataset_hash) ON DELETE RESTRICT,
    natural_key TEXT NOT NULL,
    artifact_hash TEXT NOT NULL REFERENCES market_artifact (artifact_hash) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('CALENDAR', 'MINUTE', 'LIMIT', 'DAILY')),
    symbol TEXT,
    trade_date TEXT NOT NULL,
    PRIMARY KEY (dataset_hash, natural_key)
);
CREATE INDEX IF NOT EXISTS ix_market_dataset_item_lookup
    ON market_dataset_item (dataset_hash, kind, symbol, trade_date);
"""


class BacktestMarketStore:
    """Persist shared market revisions and freeze exact reproducible datasets."""

    def __init__(self, database_path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        if isinstance(database_path, str) and not database_path.strip():
            raise ValueError("database_path must not be empty")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        self._path = Path(database_path).expanduser().resolve()
        if self._path.exists() and not self._path.is_file():
            raise ValueError("database_path must point to a file")
        self._migration_inventory = inspect_market_database(self._path)
        require_safe_store_initialization(self._migration_inventory)
        reject_incompatible_database(
            self._path,
            store_name="backtest market",
            forbidden_prefixes=("backtest_",),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = busy_timeout_ms
        self._manifest_cache: dict[str, DatasetManifest] = {}
        self._manifest_item_cache: dict[str, dict[str, DatasetItem]] = {}
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._path

    @property
    def migration_inventory(self) -> MigrationInventory:
        """Return the immutable inventory captured before initialization."""

        return self._migration_inventory

    def record_minute_batch(self, batch: HistoricalMinuteBatch) -> str:
        """Record one fully validated historical trading day."""

        if not isinstance(batch, HistoricalMinuteBatch):
            raise TypeError("batch must be a HistoricalMinuteBatch")
        natural_key = f"MINUTE:{batch.symbol}:{batch.trade_date.isoformat()}"
        minute_rows: list[tuple[str, str, str, str]] = []
        minute_references: list[dict[str, str]] = []
        for bar in batch.bars:
            content_json = _canonical_json(bar.model_dump(mode="python", round_trip=True))
            artifact_hash = _content_hash(
                {
                    "kind": "MINUTE_BAR",
                    "provider": "TUSHARE",
                    "contract_version": batch.contract_version.value,
                    "symbol": bar.symbol,
                    "bar_end": bar.bar_end.isoformat(),
                    "content": json.loads(content_json),
                }
            )
            minute_rows.append((artifact_hash, bar.symbol, bar.bar_end.isoformat(), content_json))
            minute_references.append(
                {"artifactHash": artifact_hash, "barEnd": bar.bar_end.isoformat()}
            )
        day_content = {
            "bars": minute_references,
            "contractVersion": batch.contract_version.value,
            "openingSpecial": batch.opening_special.model_dump(
                mode="python",
                round_trip=True,
            ),
            "symbol": batch.symbol,
            "tradeDate": batch.trade_date.isoformat(),
        }
        day_content_json = _canonical_json(day_content)
        day_hash = _content_hash(
            {
                "kind": "MINUTE",
                "provider": "TUSHARE",
                "contract_version": batch.contract_version.value,
                "natural_key": natural_key,
                "content": day_content,
            }
        )
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for artifact_hash, symbol, bar_end, content_json in minute_rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO market_minute_artifact (
                        artifact_hash, symbol, bar_end, content_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (artifact_hash, symbol, bar_end, content_json, now),
                )
                head = connection.execute(
                    """
                    SELECT artifact_hash, revision FROM market_minute_head
                    WHERE symbol = ? AND bar_end = ?
                    """,
                    (symbol, bar_end),
                ).fetchone()
                if head is not None and str(head[0]) == artifact_hash:
                    continue
                revision = 1 if head is None else int(head[1]) + 1
                connection.execute(
                    """
                    INSERT INTO market_minute_head (
                        symbol, bar_end, artifact_hash, revision, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, bar_end) DO UPDATE SET
                        artifact_hash = excluded.artifact_hash,
                        revision = excluded.revision,
                        updated_at = excluded.updated_at
                    """,
                    (symbol, bar_end, artifact_hash, revision, now),
                )
            existing = connection.execute(
                "SELECT artifact_hash, revision FROM market_head WHERE natural_key = ?",
                (natural_key,),
            ).fetchone()
            if existing is None or str(existing[0]) != day_hash:
                revision = 1 if existing is None else int(existing[1]) + 1
                connection.execute(
                    """
                    INSERT OR IGNORE INTO market_artifact (
                        artifact_hash, kind, provider, contract_version,
                        natural_key, content_json, created_at
                    ) VALUES (?, 'MINUTE', 'TUSHARE', ?, ?, ?, ?)
                    """,
                    (
                        day_hash,
                        batch.contract_version.value,
                        natural_key,
                        day_content_json,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO market_head (
                        natural_key, artifact_hash, revision, kind,
                        symbol, trade_date, updated_at
                    ) VALUES (?, ?, ?, 'MINUTE', ?, ?, ?)
                    ON CONFLICT(natural_key) DO UPDATE SET
                        artifact_hash = excluded.artifact_hash,
                        revision = excluded.revision,
                        kind = excluded.kind,
                        symbol = excluded.symbol,
                        trade_date = excluded.trade_date,
                        updated_at = excluded.updated_at
                    """,
                    (
                        natural_key,
                        day_hash,
                        revision,
                        batch.symbol,
                        batch.trade_date.isoformat(),
                        now,
                    ),
                )
            connection.commit()
        return day_hash

    def record_trading_days(self, values: Iterable[TradingDay]) -> tuple[str, ...]:
        return self._record_many("CALENDAR", values)

    def record_daily_limits(self, values: Iterable[DailyLimit]) -> tuple[str, ...]:
        return self._record_many("LIMIT", values)

    def record_daily_bars(self, values: Iterable[DailyBar]) -> tuple[str, ...]:
        return self._record_many("DAILY", values)

    def statistics(self) -> MarketStoreStatistics:
        with self._connect() as connection:
            artifact_count = self._count(connection, "market_artifact")
            head_count = self._count(connection, "market_head")
            minute_artifact_count = self._count(connection, "market_minute_artifact")
            minute_head_count = self._count(connection, "market_minute_head")
            dataset_count = self._count(connection, "market_dataset")
        return MarketStoreStatistics(
            artifact_count=artifact_count,
            head_count=head_count,
            minute_artifact_count=minute_artifact_count,
            minute_head_count=minute_head_count,
            dataset_count=dataset_count,
        )

    def head_revision(self, natural_key: str) -> int | None:
        normalized_key = self._validate_natural_key(natural_key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision FROM market_head WHERE natural_key = ?",
                (normalized_key,),
            ).fetchone()
        return None if row is None else int(row[0])

    def has_head(self, natural_key: str) -> bool:
        """Return whether one natural identity has a current validated revision."""

        return self.head_revision(natural_key) is not None

    def current_trading_day(self, exchange: str, cal_date: date) -> TradingDay | None:
        """Read the current calendar head without selecting a frozen dataset."""

        natural_key = f"CALENDAR:{exchange}:{cal_date.isoformat()}"
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.artifact_hash, a.kind, a.provider, a.contract_version,
                       a.natural_key, a.content_json
                FROM market_head AS h
                JOIN market_artifact AS a ON a.artifact_hash = h.artifact_hash
                WHERE h.natural_key = ?
                """,
                (natural_key,),
            ).fetchone()
        if row is None:
            return None
        content = _validated_market_artifact(
            row,
            expected_key=natural_key,
            expected_kind="CALENDAR",
        )
        value = TradingDay.model_validate_json(content)
        if value.exchange != exchange or value.cal_date != cal_date:
            raise RuntimeError("current calendar artifact identity is invalid")
        return value

    def freeze_dataset(self, scope: DatasetScope) -> DatasetFreezeResult:
        """Verify required surfaces and freeze their current immutable revisions."""

        if not isinstance(scope, DatasetScope):
            raise TypeError("scope must be a DatasetScope")
        with self._connect() as connection:
            # Hold a stable WAL read snapshot while validating historical facts. In
            # particular, do not reserve the database writer for a multi-year scan.
            connection.execute("BEGIN")
            required = self._required_keys(scope, connection)
            items: list[DatasetItem] = []
            blockers: list[str] = []
            calendars: list[TradingDay] = []
            daily_limits: dict[tuple[str, date], DailyLimit] = {}
            daily_bars: dict[tuple[str, date], DailyBar] = {}
            for natural_key, kind, symbol, trade_date in required:
                row = connection.execute(
                    """
                    SELECT a.artifact_hash, a.kind, a.provider, a.contract_version,
                           a.natural_key, a.content_json
                    FROM market_head AS h
                    JOIN market_artifact AS a ON a.artifact_hash = h.artifact_hash
                    WHERE h.natural_key = ?
                    """,
                    (natural_key,),
                ).fetchone()
                if row is None:
                    blockers.append(self._missing_blocker(kind, symbol, trade_date, natural_key))
                    continue
                try:
                    content = _validated_market_artifact(
                        row,
                        expected_key=natural_key,
                        expected_kind=kind,
                    )
                    if kind == "CALENDAR":
                        calendar = TradingDay.model_validate_json(content)
                        if calendar.cal_date != trade_date:
                            raise ValueError("calendar date does not match its key")
                        calendars.append(calendar)
                    elif kind == "MINUTE" and symbol is not None:
                        minute_batch = _validated_minute_batch(
                            connection,
                            content,
                            expected_symbol=symbol,
                            expected_date=trade_date,
                        )
                        price_blocker = _price_limit_blocker(
                            minute_batch=minute_batch,
                            daily_limit=daily_limits.get((symbol, trade_date)),
                            daily_bar=daily_bars.get((symbol, trade_date)),
                        )
                        if price_blocker is not None:
                            blockers.append(price_blocker)
                    elif kind == "LIMIT" and symbol is not None:
                        limit = DailyLimit.model_validate_json(content)
                        if limit.symbol != symbol or limit.trade_date != trade_date:
                            raise ValueError("daily-limit identity does not match its key")
                        daily_limits[(symbol, trade_date)] = limit
                    elif kind == "DAILY" and symbol is not None:
                        daily = DailyBar.model_validate_json(content)
                        if (
                            daily.symbol != symbol
                            or daily.trade_date != trade_date
                            or not daily.is_official
                        ):
                            raise ValueError("daily identity does not match its key")
                        daily_bars[(symbol, trade_date)] = daily
                except RuntimeError, TypeError, ValueError, json.JSONDecodeError:
                    blockers.append(_invalid_blocker(kind, symbol, trade_date, natural_key))
                    continue
                items.append(
                    DatasetItem(
                        natural_key=natural_key,
                        artifact_hash=str(row[0]),
                        kind=kind,
                        symbol=symbol,
                        trade_date=trade_date,
                    )
                )
            blockers.extend(_calendar_chain_blockers(calendars))
            connection.commit()
            if blockers:
                return DatasetFreezeResult(
                    ready=False,
                    dataset_hash=None,
                    blockers=tuple(sorted(set(blockers))),
                )

            ordered_items = tuple(sorted(items, key=lambda item: item.natural_key))
            dataset_hash = _content_hash(_dataset_identity(scope, ordered_items))
            manifest = DatasetManifest(
                dataset_hash=dataset_hash,
                scope=scope,
                items=ordered_items,
            )
            manifest_json = _canonical_json(manifest.model_dump(mode="python", round_trip=True))
            # Only publication reserves the writer. Revalidate every selected head
            # after acquiring it so a concurrent correction cannot be mixed in.
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_heads(connection, ordered_items)
            connection.execute(
                """
                INSERT OR IGNORE INTO market_dataset (dataset_hash, manifest_json, created_at)
                VALUES (?, ?, ?)
                """,
                (dataset_hash, manifest_json, _utc_now()),
            )
            item_rows = tuple(
                (
                    dataset_hash,
                    item.natural_key,
                    item.artifact_hash,
                    item.kind,
                    item.symbol,
                    item.trade_date.isoformat(),
                )
                for item in ordered_items
            )
            for start in range(0, len(item_rows), 1_000):
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO market_dataset_item (
                        dataset_hash, natural_key, artifact_hash, kind, symbol, trade_date
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    item_rows[start : start + 1_000],
                )
            if self._load_manifest(connection, dataset_hash) != manifest:
                self._manifest_cache.pop(dataset_hash, None)
                self._manifest_item_cache.pop(dataset_hash, None)
                raise RuntimeError("stored dataset manifest does not match its frozen identity")
            connection.commit()
        return DatasetFreezeResult(ready=True, dataset_hash=dataset_hash, blockers=())

    def dataset_manifest(self, dataset_hash: str) -> DatasetManifest:
        normalized_hash = _validate_hash(dataset_hash, "dataset_hash")
        with self._connect() as connection:
            return self._load_manifest(connection, normalized_hash)

    def dataset_minutes(
        self,
        dataset_hash: str,
        symbol: str,
        trade_date: date,
    ) -> tuple[MinuteBar, ...]:
        content = self._dataset_content(dataset_hash, "MINUTE", symbol, trade_date)
        try:
            day_manifest = json.loads(content)
            if set(day_manifest) != {
                "bars",
                "contractVersion",
                "openingSpecial",
                "symbol",
                "tradeDate",
            }:
                raise ValueError("minute day manifest fields are invalid")
            if (
                day_manifest["symbol"] != symbol
                or day_manifest["tradeDate"] != trade_date.isoformat()
            ):
                raise ValueError("minute day manifest identity is invalid")
            references = day_manifest["bars"]
            if not isinstance(references, list) or any(
                not isinstance(reference, dict) or set(reference) != {"artifactHash", "barEnd"}
                for reference in references
            ):
                raise ValueError("minute references are invalid")
            hashes = tuple(reference["artifactHash"] for reference in references)
            if len(hashes) != 240 or len(set(hashes)) != 240:
                raise ValueError("minute day manifest must contain 240 unique artifacts")
            if any(_validate_hash(value, "minute artifact hash") != value for value in hashes):
                raise ValueError("minute artifact hash is invalid")
            placeholders = ",".join("?" for _ in hashes)
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT artifact_hash, symbol, bar_end, content_json
                    FROM market_minute_artifact
                    WHERE artifact_hash IN ({placeholders})
                    """,
                    hashes,
                ).fetchall()
            row_by_hash = {str(row[0]): row for row in rows}
            if len(row_by_hash) != len(hashes):
                raise ValueError("minute dataset references missing immutable artifacts")
            bars: list[MinuteBar] = []
            for reference, artifact_hash in zip(references, hashes, strict=True):
                row = row_by_hash[artifact_hash]
                content_json = str(row[3])
                bar = MinuteBar.model_validate_json(content_json)
                if (
                    str(row[1]) != symbol
                    or str(row[2]) != reference["barEnd"]
                    or bar.symbol != symbol
                    or bar.bar_end.isoformat() != reference["barEnd"]
                ):
                    raise ValueError("minute artifact identity is invalid")
                expected_hash = _content_hash(
                    {
                        "kind": "MINUTE_BAR",
                        "provider": "TUSHARE",
                        "contract_version": day_manifest["contractVersion"],
                        "symbol": bar.symbol,
                        "bar_end": bar.bar_end.isoformat(),
                        "content": json.loads(content_json),
                    }
                )
                if artifact_hash != expected_hash:
                    raise ValueError("minute artifact content hash is invalid")
                bars.append(bar)
            batch = HistoricalMinuteBatch.model_validate_json(
                _canonical_json(
                    {
                        "symbol": day_manifest["symbol"],
                        "trade_date": day_manifest["tradeDate"],
                        "contract_version": day_manifest["contractVersion"],
                        "bars": [bar.model_dump(mode="python", round_trip=True) for bar in bars],
                        "opening_special": day_manifest["openingSpecial"],
                    }
                )
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("frozen minute day manifest is invalid") from error
        return batch.bars

    def dataset_daily_limit(
        self,
        dataset_hash: str,
        symbol: str,
        trade_date: date,
    ) -> DailyLimit:
        content = self._dataset_content(dataset_hash, "LIMIT", symbol, trade_date)
        value = DailyLimit.model_validate_json(content)
        if value.symbol != symbol or value.trade_date != trade_date:
            raise RuntimeError("frozen daily-limit artifact identity is invalid")
        return value

    def dataset_daily_bar(
        self,
        dataset_hash: str,
        symbol: str,
        trade_date: date,
    ) -> DailyBar:
        content = self._dataset_content(dataset_hash, "DAILY", symbol, trade_date)
        value = DailyBar.model_validate_json(content)
        if value.symbol != symbol or value.trade_date != trade_date or not value.is_official:
            raise RuntimeError("frozen daily artifact identity is invalid")
        return value

    def dataset_trading_day(
        self,
        dataset_hash: str,
        exchange: str,
        trade_date: date,
    ) -> TradingDay:
        natural_key = f"CALENDAR:{exchange}:{trade_date.isoformat()}"
        content = self._dataset_content_by_key(dataset_hash, natural_key)
        value = TradingDay.model_validate_json(content)
        if value.exchange != exchange or value.cal_date != trade_date:
            raise RuntimeError("frozen calendar artifact identity is invalid")
        return value

    def dataset_trading_days(
        self,
        dataset_hash: str,
        exchange: str,
    ) -> tuple[TradingDay, ...]:
        """Load one frozen exchange calendar in bounded indexed queries."""

        manifest = self.dataset_manifest(dataset_hash)
        items = tuple(
            item
            for item in manifest.items
            if item.kind == "CALENDAR" and item.natural_key.startswith(f"CALENDAR:{exchange}:")
        )
        contents = self._dataset_contents_for_items(manifest, items)
        values = tuple(TradingDay.model_validate_json(contents[item.natural_key]) for item in items)
        if any(value.exchange != exchange for value in values):
            raise RuntimeError("frozen calendar range contains a wrong exchange")
        return tuple(sorted(values, key=lambda value: value.cal_date))

    def dataset_daily_bars(
        self,
        dataset_hash: str,
        symbol: str,
    ) -> tuple[DailyBar, ...]:
        """Load one symbol's frozen official daily history without per-row connections."""

        manifest = self.dataset_manifest(dataset_hash)
        items = tuple(
            item for item in manifest.items if item.kind == "DAILY" and item.symbol == symbol
        )
        contents = self._dataset_contents_for_items(manifest, items)
        values = tuple(DailyBar.model_validate_json(contents[item.natural_key]) for item in items)
        if any(value.symbol != symbol or not value.is_official for value in values):
            raise RuntimeError("frozen daily range contains an invalid bar")
        return tuple(sorted(values, key=lambda value: value.trade_date))

    def _initialize(self) -> None:
        with self._connect() as connection:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                raise RuntimeError("backtest market database did not enter WAL mode")
            connection.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _record_many(
        self,
        kind: Literal["CALENDAR", "LIMIT", "DAILY"],
        values: Iterable[_MarketValue],
    ) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise TypeError("values must be an iterable of normalized market values")
        expected_type: type[BaseModel]
        if kind == "CALENDAR":
            expected_type = TradingDay
        elif kind == "LIMIT":
            expected_type = DailyLimit
        else:
            expected_type = DailyBar

        prepared: list[tuple[str, str, str | None, date, str, str]] = []
        for value in tuple(values):
            if not isinstance(value, expected_type):
                raise TypeError(f"{kind.lower()} value has the wrong type")
            if isinstance(value, TradingDay):
                natural_key = f"CALENDAR:{value.exchange}:{value.cal_date.isoformat()}"
                symbol = None
                trade_date = value.cal_date
            else:
                if isinstance(value, DailyBar) and not value.is_official:
                    raise ValueError("historical daily bars must be official")
                if isinstance(value, DailyBar) and value.received_at != datetime.combine(
                    value.trade_date,
                    time(15, 20),
                    _SHANGHAI,
                ):
                    raise ValueError("historical daily receipt must use deterministic 15:20")
                if isinstance(value, DailyLimit) and value.received_at != datetime.combine(
                    value.trade_date,
                    time(9, 30),
                    _SHANGHAI,
                ):
                    raise ValueError("historical daily-limit receipt must use deterministic 09:30")
                natural_key = f"{kind}:{value.symbol}:{value.trade_date.isoformat()}"
                symbol = value.symbol
                trade_date = value.trade_date
            content_json = _canonical_json(value.model_dump(mode="python", round_trip=True))
            artifact_hash = _content_hash(
                {
                    "kind": kind,
                    "provider": "TUSHARE",
                    "contract_version": "normalized-market-v1",
                    "natural_key": natural_key,
                    "content": json.loads(content_json),
                }
            )
            prepared.append((natural_key, artifact_hash, symbol, trade_date, content_json, kind))
        hashes: list[str] = []
        for start in range(0, len(prepared), 1_000):
            hashes.extend(self._record_batch(prepared[start : start + 1_000]))
        return tuple(hashes)

    def _record_batch(
        self,
        prepared: list[tuple[str, str, str | None, date, str, str]],
    ) -> tuple[str, ...]:
        now = _utc_now()
        hashes: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for natural_key, artifact_hash, symbol, trade_date, content_json, kind in prepared:
                hashes.append(artifact_hash)
                head = connection.execute(
                    "SELECT artifact_hash, revision FROM market_head WHERE natural_key = ?",
                    (natural_key,),
                ).fetchone()
                if head is not None and str(head[0]) == artifact_hash:
                    continue
                revision = 1 if head is None else int(head[1]) + 1
                connection.execute(
                    """
                    INSERT OR IGNORE INTO market_artifact (
                        artifact_hash, kind, provider, contract_version,
                        natural_key, content_json, created_at
                    ) VALUES (?, ?, 'TUSHARE', 'normalized-market-v1', ?, ?, ?)
                    """,
                    (artifact_hash, kind, natural_key, content_json, now),
                )
                connection.execute(
                    """
                    INSERT INTO market_head (
                        natural_key, artifact_hash, revision, kind,
                        symbol, trade_date, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(natural_key) DO UPDATE SET
                        artifact_hash = excluded.artifact_hash,
                        revision = excluded.revision,
                        kind = excluded.kind,
                        symbol = excluded.symbol,
                        trade_date = excluded.trade_date,
                        updated_at = excluded.updated_at
                    """,
                    (
                        natural_key,
                        artifact_hash,
                        revision,
                        kind,
                        symbol,
                        trade_date.isoformat(),
                        now,
                    ),
                )
            connection.commit()
        return tuple(hashes)

    def _required_keys(
        self,
        scope: DatasetScope,
        connection: sqlite3.Connection,
    ) -> tuple[tuple[str, _ArtifactKind, str | None, date], ...]:
        required: list[tuple[str, _ArtifactKind, str | None, date]] = []
        cursor = scope.warmup_start
        exchanges = tuple(sorted({exchange_for_symbol(symbol) for symbol in scope.symbols}))
        while cursor <= scope.end:
            open_exchanges: set[str] = set()
            for exchange in exchanges:
                calendar_key = f"CALENDAR:{exchange}:{cursor.isoformat()}"
                required.append((calendar_key, "CALENDAR", None, cursor))
                row = connection.execute(
                    """
                    SELECT a.artifact_hash, a.kind, a.provider, a.contract_version,
                           a.natural_key, a.content_json
                    FROM market_head AS h
                    JOIN market_artifact AS a ON a.artifact_hash = h.artifact_hash
                    WHERE h.natural_key = ?
                    """,
                    (calendar_key,),
                ).fetchone()
                if row is None:
                    continue
                try:
                    content = _validated_market_artifact(
                        row,
                        expected_key=calendar_key,
                        expected_kind="CALENDAR",
                    )
                    calendar = TradingDay.model_validate_json(content)
                except RuntimeError, ValueError:
                    continue
                if calendar.exchange != exchange or calendar.cal_date != cursor:
                    continue
                if calendar.is_open:
                    open_exchanges.add(exchange)
            for symbol in scope.symbols:
                if exchange_for_symbol(symbol) not in open_exchanges:
                    continue
                date_text = cursor.isoformat()
                required.append((f"DAILY:{symbol}:{date_text}", "DAILY", symbol, cursor))
                if cursor >= scope.start:
                    required.extend(
                        (
                            (f"LIMIT:{symbol}:{date_text}", "LIMIT", symbol, cursor),
                            (f"MINUTE:{symbol}:{date_text}", "MINUTE", symbol, cursor),
                        )
                    )
            cursor += timedelta(days=1)
        return tuple(required)

    def _load_manifest(
        self,
        connection: sqlite3.Connection,
        dataset_hash: str,
    ) -> DatasetManifest:
        row = connection.execute(
            "SELECT manifest_json FROM market_dataset WHERE dataset_hash = ?",
            (dataset_hash,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown dataset_hash: {dataset_hash}")
        try:
            manifest = DatasetManifest.model_validate_json(str(row[0]))
        except ValueError as error:
            raise RuntimeError("stored dataset manifest is invalid") from error
        if manifest.dataset_hash != dataset_hash:
            raise RuntimeError("stored dataset manifest identity is invalid")
        ordered_items = tuple(sorted(manifest.items, key=lambda item: item.natural_key))
        if manifest.items != ordered_items:
            raise RuntimeError("stored dataset manifest items are not canonical")
        if _content_hash(_dataset_identity(manifest.scope, ordered_items)) != dataset_hash:
            raise RuntimeError("stored dataset manifest failed its content hash")
        rows = connection.execute(
            """
            SELECT natural_key, artifact_hash, kind, symbol, trade_date
            FROM market_dataset_item
            WHERE dataset_hash = ?
            ORDER BY natural_key
            """,
            (dataset_hash,),
        ).fetchall()
        stored_items = tuple(
            DatasetItem(
                natural_key=str(item[0]),
                artifact_hash=str(item[1]),
                kind=str(item[2]),
                symbol=None if item[3] is None else str(item[3]),
                trade_date=date.fromisoformat(str(item[4])),
            )
            for item in rows
        )
        if stored_items != ordered_items:
            raise RuntimeError("stored dataset membership does not match its manifest")
        if (
            dataset_hash not in self._manifest_cache
            and len(self._manifest_cache) >= _MAX_MANIFEST_CACHE
        ):
            evicted_hash = next(iter(self._manifest_cache))
            self._manifest_cache.pop(evicted_hash)
            self._manifest_item_cache.pop(evicted_hash, None)
        self._manifest_cache[dataset_hash] = manifest
        self._manifest_item_cache[dataset_hash] = {
            item.natural_key: item for item in manifest.items
        }
        return manifest

    def _dataset_contents_for_items(
        self,
        manifest: DatasetManifest,
        items: tuple[DatasetItem, ...],
    ) -> dict[str, str]:
        item_index = self._manifest_item_cache.get(manifest.dataset_hash)
        if item_index is None:
            item_index = {item.natural_key: item for item in manifest.items}
            self._manifest_item_cache[manifest.dataset_hash] = item_index
        if any(item_index.get(item.natural_key) != item for item in items):
            raise ValueError("items must belong to the supplied dataset manifest")
        contents: dict[str, str] = {}
        with self._connect() as connection:
            for start in range(0, len(items), 500):
                batch = items[start : start + 500]
                if not batch:
                    continue
                keys = tuple(item.natural_key for item in batch)
                placeholders = ",".join("?" for _ in keys)
                rows = connection.execute(
                    f"""
                    SELECT i.natural_key, i.artifact_hash, i.kind, i.symbol, i.trade_date,
                           a.artifact_hash, a.kind, a.provider, a.contract_version,
                           a.natural_key, a.content_json
                    FROM market_dataset_item AS i
                    JOIN market_artifact AS a ON a.artifact_hash = i.artifact_hash
                    WHERE i.dataset_hash = ? AND i.natural_key IN ({placeholders})
                    """,
                    (manifest.dataset_hash, *keys),
                ).fetchall()
                rows_by_key = {str(row[0]): row for row in rows}
                for item in batch:
                    row = rows_by_key.get(item.natural_key)
                    if row is None:
                        raise RuntimeError("frozen dataset membership is incomplete")
                    _validate_dataset_item_row(row[:5], item)
                    contents[item.natural_key] = _validated_market_artifact(
                        row[5:],
                        expected_key=item.natural_key,
                        expected_kind=item.kind,
                    )
        return contents

    def _dataset_content(
        self,
        dataset_hash: str,
        kind: _ArtifactKind,
        symbol: str,
        trade_date: date,
    ) -> str:
        if type(symbol) is not str or not symbol:
            raise ValueError("symbol must not be empty")
        if isinstance(trade_date, datetime) or not isinstance(trade_date, date):
            raise TypeError("trade_date must be a date")
        natural_key = f"{kind}:{symbol}:{trade_date.isoformat()}"
        return self._dataset_content_by_key(dataset_hash, natural_key)

    def _dataset_content_by_key(self, dataset_hash: str, natural_key: str) -> str:
        normalized_hash = _validate_hash(dataset_hash, "dataset_hash")
        manifest = self._manifest_cache.get(normalized_hash)
        if manifest is None:
            manifest = self.dataset_manifest(normalized_hash)
        item_index = self._manifest_item_cache.get(normalized_hash)
        if item_index is None:
            item_index = {item.natural_key: item for item in manifest.items}
            self._manifest_item_cache[normalized_hash] = item_index
        item = item_index.get(natural_key)
        if item is None:
            raise KeyError(f"dataset does not contain {natural_key}")
        return self._dataset_contents_for_items(manifest, (item,))[natural_key]

    @staticmethod
    def _assert_current_heads(
        connection: sqlite3.Connection,
        items: tuple[DatasetItem, ...],
    ) -> None:
        for start in range(0, len(items), 500):
            batch = items[start : start + 500]
            keys = tuple(item.natural_key for item in batch)
            placeholders = ",".join("?" for _ in keys)
            rows = connection.execute(
                f"""
                SELECT natural_key, artifact_hash
                FROM market_head
                WHERE natural_key IN ({placeholders})
                """,
                keys,
            ).fetchall()
            actual = {str(row[0]): str(row[1]) for row in rows}
            expected = {item.natural_key: item.artifact_hash for item in batch}
            if actual != expected:
                raise RuntimeError("market heads changed during dataset freeze")

    @staticmethod
    def _missing_blocker(
        kind: _ArtifactKind,
        symbol: str | None,
        trade_date: date,
        natural_key: str,
    ) -> str:
        labels = {
            "CALENDAR": "MISSING_CALENDAR",
            "MINUTE": "MISSING_MINUTES",
            "LIMIT": "MISSING_DAILY_LIMIT",
            "DAILY": "MISSING_DAILY_BAR",
        }
        identity = symbol if symbol is not None else natural_key.split(":", maxsplit=2)[1]
        return f"{labels[kind]}:{identity}:{trade_date.isoformat()}"

    @staticmethod
    def _count(connection: sqlite3.Connection, table: str) -> int:
        if table not in {
            "market_artifact",
            "market_head",
            "market_minute_artifact",
            "market_minute_head",
            "market_dataset",
        }:
            raise ValueError("unsupported count table")
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    @staticmethod
    def _validate_natural_key(value: str) -> str:
        if type(value) is not str or not value or len(value) > 128:
            raise ValueError("natural_key must contain between 1 and 128 characters")
        return value


def _canonical_json(value: object) -> str:
    return canonical_json(value)


def _dataset_identity(
    scope: DatasetScope,
    items: tuple[DatasetItem, ...],
) -> dict[str, object]:
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "scope": scope.model_dump(mode="python", round_trip=True),
        "items": [item.model_dump(mode="python", round_trip=True) for item in items],
    }


def _validated_market_artifact(
    row: tuple[object, ...],
    *,
    expected_key: str,
    expected_kind: _ArtifactKind,
) -> str:
    if len(row) != 6:
        raise RuntimeError("market artifact row shape is invalid")
    artifact_hash, kind, provider, contract_version, natural_key, content_json = (
        str(value) for value in row
    )
    if kind != expected_kind or natural_key != expected_key or provider != "TUSHARE":
        raise RuntimeError("market artifact metadata is invalid")
    try:
        content = json.loads(content_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("market artifact content is invalid JSON") from error
    expected_hash = _content_hash(
        {
            "kind": kind,
            "provider": provider,
            "contract_version": contract_version,
            "natural_key": natural_key,
            "content": content,
        }
    )
    if artifact_hash != expected_hash:
        raise RuntimeError("market artifact failed its content hash")
    return content_json


def _validate_dataset_item_row(row: tuple[object, ...], expected: DatasetItem) -> None:
    if len(row) != 5:
        raise RuntimeError("dataset item row shape is invalid")
    actual = (
        str(row[0]),
        str(row[1]),
        str(row[2]),
        None if row[3] is None else str(row[3]),
        str(row[4]),
    )
    wanted = (
        expected.natural_key,
        expected.artifact_hash,
        expected.kind,
        expected.symbol,
        expected.trade_date.isoformat(),
    )
    if actual != wanted:
        raise RuntimeError("dataset item does not match its manifest")


def _calendar_chain_blockers(values: list[TradingDay]) -> tuple[str, ...]:
    blockers: list[str] = []
    exchanges = sorted({value.exchange for value in values})
    for exchange in exchanges:
        last_open: date | None = None
        calendar = sorted(
            (value for value in values if value.exchange == exchange),
            key=lambda value: value.cal_date,
        )
        for value in calendar:
            if last_open is not None and value.previous_trade_date != last_open:
                blockers.append(f"INVALID_CALENDAR_CHAIN:{exchange}:{value.cal_date.isoformat()}")
            if value.is_open:
                last_open = value.cal_date
    return tuple(blockers)


def _validated_minute_batch(
    connection: sqlite3.Connection,
    content_json: str,
    *,
    expected_symbol: str,
    expected_date: date,
) -> HistoricalMinuteBatch:
    day_manifest = json.loads(content_json)
    if not isinstance(day_manifest, dict) or set(day_manifest) != {
        "bars",
        "contractVersion",
        "openingSpecial",
        "symbol",
        "tradeDate",
    }:
        raise ValueError("minute day manifest fields are invalid")
    if (
        day_manifest["symbol"] != expected_symbol
        or day_manifest["tradeDate"] != expected_date.isoformat()
    ):
        raise ValueError("minute day manifest identity is invalid")
    references = day_manifest["bars"]
    if not isinstance(references, list) or any(
        not isinstance(reference, dict) or set(reference) != {"artifactHash", "barEnd"}
        for reference in references
    ):
        raise ValueError("minute references are invalid")
    hashes = tuple(reference["artifactHash"] for reference in references)
    if len(hashes) != 240 or len(set(hashes)) != 240:
        raise ValueError("minute day manifest must contain 240 unique artifacts")
    for artifact_hash in hashes:
        _validate_hash(artifact_hash, "minute artifact hash")
    placeholders = ",".join("?" for _ in hashes)
    rows = connection.execute(
        f"""
        SELECT artifact_hash, symbol, bar_end, content_json
        FROM market_minute_artifact
        WHERE artifact_hash IN ({placeholders})
        """,
        hashes,
    ).fetchall()
    row_by_hash = {str(row[0]): row for row in rows}
    if len(row_by_hash) != len(hashes):
        raise ValueError("minute dataset references missing immutable artifacts")
    bars: list[MinuteBar] = []
    for reference, artifact_hash in zip(references, hashes, strict=True):
        row = row_by_hash[artifact_hash]
        bar_content = str(row[3])
        bar = MinuteBar.model_validate_json(bar_content)
        if (
            str(row[1]) != expected_symbol
            or str(row[2]) != reference["barEnd"]
            or bar.symbol != expected_symbol
            or bar.bar_end.isoformat() != reference["barEnd"]
        ):
            raise ValueError("minute artifact identity is invalid")
        expected_hash = _content_hash(
            {
                "kind": "MINUTE_BAR",
                "provider": "TUSHARE",
                "contract_version": day_manifest["contractVersion"],
                "symbol": bar.symbol,
                "bar_end": bar.bar_end.isoformat(),
                "content": json.loads(bar_content),
            }
        )
        if artifact_hash != expected_hash:
            raise ValueError("minute artifact content hash is invalid")
        bars.append(bar)
    return HistoricalMinuteBatch.model_validate_json(
        _canonical_json(
            {
                "symbol": day_manifest["symbol"],
                "trade_date": day_manifest["tradeDate"],
                "contract_version": day_manifest["contractVersion"],
                "bars": [bar.model_dump(mode="python", round_trip=True) for bar in bars],
                "opening_special": day_manifest["openingSpecial"],
            }
        )
    )


def _price_limit_blocker(
    *,
    minute_batch: HistoricalMinuteBatch,
    daily_limit: DailyLimit | None,
    daily_bar: DailyBar | None,
) -> str | None:
    if daily_limit is None or daily_bar is None:
        return None
    prices = (
        daily_bar.open_fen,
        daily_bar.high_fen,
        daily_bar.low_fen,
        daily_bar.close_fen,
        *(
            price
            for bar in minute_batch.bars
            for price in (bar.open_fen, bar.high_fen, bar.low_fen, bar.close_fen)
        ),
    )
    if any(
        price < daily_limit.down_limit_fen or price > daily_limit.up_limit_fen for price in prices
    ):
        return (
            f"PRICE_OUTSIDE_DAILY_LIMIT:{minute_batch.symbol}:{minute_batch.trade_date.isoformat()}"
        )
    return None


def _invalid_blocker(
    kind: _ArtifactKind,
    symbol: str | None,
    trade_date: date,
    natural_key: str,
) -> str:
    identity = symbol if symbol is not None else natural_key.split(":", maxsplit=2)[1]
    return f"INVALID_{kind}:{identity}:{trade_date.isoformat()}"


def _content_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_hash(value: str, name: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


__all__ = ["BacktestMarketStore"]
