"""Bounded public application queries for completed backtest results."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.pagination import (
    CursorSigner,
    InvalidCursorError,
    require_bounded_page_json,
    validate_page_limit,
)
from trade_plan_monitor.backtest.results import (
    BacktestArtifactAvailability,
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunRecord,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_ITEM_BYTES = 32 * 1024
_RUN_ROUTE = "runs"
_FILL_ROUTE = "backtest-results:fills"
_DETAIL_ROUTE = "backtest-results:details"
_RUN_ORDER = "completedAt:desc,runId:desc"
_FILL_ORDER = "filledAt:asc,fillId:asc"
_DETAIL_ORDER = "eventAt:asc,detailId:asc"
_EMPTY_RUN_HIGH_WATER = ("0001-01-01T00:00:00.000000+08:00", "0" * 64)
_PUBLIC_DETAIL_KINDS = frozenset(
    {
        BacktestDetailKind.DECISION,
        BacktestDetailKind.SIGNAL,
        BacktestDetailKind.EXECUTION_OUTCOME,
    }
)

_Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
_Symbol = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$"),
]


class BacktestResultNotFoundError(LookupError):
    """Sanitized absence for every public completed-result lookup."""

    def __init__(self) -> None:
        super().__init__("backtest result not found")


class BacktestRunMembershipConflictError(RuntimeError):
    """A pinned traversal changed membership after its first page."""


class _ServiceValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BacktestRunFilters(_ServiceValue):
    """Closed AND-combined run-list filter contract."""

    symbol: _Symbol | None = None
    plan_version_id: UUID | None = None
    dataset_hash: _Sha256Hex | None = None
    completed_from: Annotated[datetime, AwareDatetime()] | None = None
    completed_to: Annotated[datetime, AwareDatetime()] | None = None
    pinned: Annotated[bool, Field(strict=True)] | None = None
    event_end_from: date | None = Field(default=None, exclude_if=lambda v: v is None)
    event_end_to: date | None = Field(default=None, exclude_if=lambda v: v is None)

    @field_validator("completed_from", "completed_to")
    @classmethod
    def normalize_completed_boundary(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(_SHANGHAI)

    @model_validator(mode="after")
    def validate_completed_range(self) -> Self:
        if self.event_end_from is not None and self.event_end_to is not None and (
            self.event_end_from > self.event_end_to
        ):
            raise ValueError("event_end_to must not precede event_end_from")
        if (
            self.completed_from is not None
            and self.completed_to is not None
            and self.completed_to < self.completed_from
        ):
            raise ValueError("completed_to must not precede completed_from")
        return self


class BacktestDetailFilters(_ServiceValue):
    """Public detail endpoints require exactly one non-equity artifact kind."""

    kind: BacktestDetailKind

    @field_validator("kind")
    @classmethod
    def require_public_detail_kind(cls, value: BacktestDetailKind) -> BacktestDetailKind:
        if value not in _PUBLIC_DETAIL_KINDS:
            raise ValueError("kind must be a public detail kind")
        return value


class BacktestRunPage(_ServiceValue):
    items: tuple[BacktestRunRecord, ...]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: str | None
    has_more: Annotated[bool, Field(strict=True)]
    high_watermark: tuple[str, ...]
    snapshot: tuple[int, ...] = Field(exclude=True)


class BacktestFillPage(_ServiceValue):
    items: tuple[BacktestFillRecord, ...]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: str | None
    has_more: Annotated[bool, Field(strict=True)]
    high_watermark: tuple[str, ...] | None


class BacktestDetailPage(_ServiceValue):
    items: tuple[BacktestDetailRecord, ...]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    next_cursor: str | None
    has_more: Annotated[bool, Field(strict=True)]
    high_watermark: tuple[str, ...] | None
    availability: BacktestArtifactAvailability


class BacktestEquitySeries(_ServiceValue):
    items: tuple[BacktestDetailRecord, ...]
    availability: BacktestArtifactAvailability


class BacktestResultService:
    """Own cursor context, page ceilings, availability, and pin idempotency."""

    def __init__(
        self,
        *,
        store: BacktestResultStore,
        cursor_signer: CursorSigner,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(store, BacktestResultStore):
            raise TypeError("store must be a BacktestResultStore")
        if not callable(getattr(cursor_signer, "encode", None)) or not callable(
            getattr(cursor_signer, "decode", None)
        ):
            raise TypeError("cursor_signer must implement CursorSigner")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")
        self._store = store
        self._cursor_signer = cursor_signer
        self._clock = clock or (lambda: datetime.now(_SHANGHAI))

    def get_run(self, run_id: str) -> BacktestRunRecord:
        record = self._store.get_result_run(run_id)
        if record is None:
            raise BacktestResultNotFoundError
        _require_bounded_items((record,))
        return record

    def list_runs(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        filters: BacktestRunFilters | None = None,
    ) -> BacktestRunPage:
        normalized_limit = validate_page_limit(limit)
        normalized_filters = filters or BacktestRunFilters()
        if not isinstance(normalized_filters, BacktestRunFilters):
            raise TypeError("filters must be BacktestRunFilters or None")
        filter_context = normalized_filters.model_dump(mode="json")
        if cursor is None:
            snapshot_revision = self._store.result_run_high_water()
            pin_revision = (
                self._store.result_pin_membership_revision()
                if normalized_filters.pinned is not None
                else None
            )
            snapshot = (
                (snapshot_revision, pin_revision)
                if pin_revision is not None
                else (snapshot_revision,)
            )
            high_water = None
            last_seen = None
        else:
            decoded = self._cursor_signer.decode(
                cursor,
                route=_RUN_ROUTE,
                filters=filter_context,
                order=_RUN_ORDER,
            )
            try:
                snapshot_revision, pin_revision = _run_snapshot(
                    decoded.snapshot,
                    pinned=normalized_filters.pinned is not None,
                )
                high_water = _required_cursor_position(decoded.high_water)
            except ValueError:
                raise InvalidCursorError from None
            snapshot = decoded.snapshot
            if snapshot is None:  # pragma: no cover - _run_snapshot rejects this
                raise InvalidCursorError
            if pin_revision is not None and (
                self._store.result_pin_membership_revision() != pin_revision
            ):
                raise BacktestRunMembershipConflictError
            last_seen = _required_cursor_position(decoded.last_seen)
        rows = self._store.query_result_runs(
            limit=normalized_limit + 1,
            snapshot_revision=snapshot_revision,
            symbol=normalized_filters.symbol,
            plan_version_id=(
                None
                if normalized_filters.plan_version_id is None
                else str(normalized_filters.plan_version_id)
            ),
            dataset_hash=normalized_filters.dataset_hash,
            completed_from=normalized_filters.completed_from,
            completed_to=normalized_filters.completed_to,
            event_end_from=normalized_filters.event_end_from,
            event_end_to=normalized_filters.event_end_to,
            pinned=normalized_filters.pinned,
            high_water=high_water,
            last_seen=last_seen,
        )
        if (
            pin_revision is not None
            and self._store.result_pin_membership_revision() != pin_revision
        ):
            raise BacktestRunMembershipConflictError
        if high_water is None:
            high_water = rows[0].position if rows else _EMPTY_RUN_HIGH_WATER
        page_rows = rows[:normalized_limit]
        items = tuple(row.record for row in page_rows)
        _require_bounded_items(items)
        has_more = len(rows) > normalized_limit
        next_cursor = (
            self._cursor_signer.encode(
                route=_RUN_ROUTE,
                filters=filter_context,
                order=_RUN_ORDER,
                high_water=high_water,
                last_seen=page_rows[-1].position,
                snapshot=snapshot,
            )
            if has_more
            else None
        )
        page = BacktestRunPage(
            items=items,
            limit=normalized_limit,
            next_cursor=next_cursor,
            has_more=has_more,
            high_watermark=high_water,
            snapshot=snapshot,
        )
        _require_bounded_page(page)
        return page

    def list_fills(
        self,
        run_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> BacktestFillPage:
        normalized_limit = validate_page_limit(limit)
        self.get_run(run_id)
        filter_context = {"runId": run_id}
        if cursor is None:
            high_water = self._store.result_fill_high_water(run_id)
            last_seen = None
        else:
            decoded = self._cursor_signer.decode(
                cursor,
                route=_FILL_ROUTE,
                filters=filter_context,
                order=_FILL_ORDER,
            )
            high_water = _two_part_position(decoded.high_water)
            last_seen = _required_cursor_position(decoded.last_seen)
        rows = self._store.query_result_fills(
            run_id,
            limit=normalized_limit + 1,
            high_water=high_water,
            last_seen=last_seen,
        )
        page_rows = rows[:normalized_limit]
        items = tuple(row.record for row in page_rows)
        _require_bounded_items(items)
        has_more = len(rows) > normalized_limit
        next_cursor = (
            self._cursor_signer.encode(
                route=_FILL_ROUTE,
                filters=filter_context,
                order=_FILL_ORDER,
                high_water=_required_high_water(high_water),
                last_seen=page_rows[-1].position,
            )
            if has_more
            else None
        )
        page = BacktestFillPage(
            items=items,
            limit=normalized_limit,
            next_cursor=next_cursor,
            has_more=has_more,
            high_watermark=high_water,
        )
        _require_bounded_page(page)
        return page

    def list_details(
        self,
        run_id: str,
        *,
        filters: BacktestDetailFilters,
        limit: int = 100,
        cursor: str | None = None,
    ) -> BacktestDetailPage:
        normalized_limit = validate_page_limit(limit)
        if not isinstance(filters, BacktestDetailFilters):
            raise TypeError("filters must be BacktestDetailFilters")
        self.get_run(run_id)
        filter_context = {"kind": filters.kind.value, "runId": run_id}
        if cursor is None:
            high_water = None
            last_seen = None
        else:
            decoded = self._cursor_signer.decode(
                cursor,
                route=_DETAIL_ROUTE,
                filters=filter_context,
                order=_DETAIL_ORDER,
            )
            high_water = _two_part_position(decoded.high_water)
            last_seen = _required_cursor_position(decoded.last_seen)
        snapshot = self._store.read_result_detail_snapshot(
            run_id,
            kind=filters.kind,
            limit=normalized_limit + 1,
            high_water=high_water,
            last_seen=last_seen,
        )
        if snapshot is None:
            raise BacktestResultNotFoundError
        state = snapshot.state
        if state.availability is not BacktestArtifactAvailability.AVAILABLE:
            if cursor is not None:
                raise InvalidCursorError
            return BacktestDetailPage(
                items=(),
                limit=normalized_limit,
                next_cursor=None,
                has_more=False,
                high_watermark=None,
                availability=state.availability,
            )
        high_water = snapshot.high_water
        rows = snapshot.rows
        page_rows = rows[:normalized_limit]
        items = tuple(row.record for row in page_rows)
        _require_bounded_items(items)
        has_more = len(rows) > normalized_limit
        next_cursor = (
            self._cursor_signer.encode(
                route=_DETAIL_ROUTE,
                filters=filter_context,
                order=_DETAIL_ORDER,
                high_water=_required_high_water(high_water),
                last_seen=page_rows[-1].position,
            )
            if has_more
            else None
        )
        page = BacktestDetailPage(
            items=items,
            limit=normalized_limit,
            next_cursor=next_cursor,
            has_more=has_more,
            high_watermark=high_water,
            availability=state.availability,
        )
        _require_bounded_page(page)
        return page

    def get_equity_series(self, run_id: str) -> BacktestEquitySeries:
        self.get_run(run_id)
        kind = BacktestDetailKind.DAILY_EQUITY
        snapshot = self._store.read_result_detail_snapshot(
            run_id,
            kind=kind,
            limit=2_001,
            high_water=None,
            last_seen=None,
        )
        if snapshot is None:
            raise BacktestResultNotFoundError
        state = snapshot.state
        if state.availability is not BacktestArtifactAvailability.AVAILABLE:
            return BacktestEquitySeries(items=(), availability=state.availability)
        rows = snapshot.rows
        if len(rows) > 2_000 or len(rows) != state.original_count:
            raise RuntimeError("daily equity series exceeds its bounded published count")
        items = tuple(row.record for row in rows)
        _require_bounded_items(items)
        series = BacktestEquitySeries(items=items, availability=state.availability)
        _require_bounded_page(series)
        return series

    def set_pinned(
        self,
        run_id: str,
        *,
        pinned: bool,
        expected_revision: int,
        idempotency_key: str,
    ) -> BacktestRunRecord:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("pin clock must return an aware datetime")
        try:
            response = self._store.set_pinned_idempotent(
                run_id,
                pinned=pinned,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
                recorded_at=now.astimezone(_SHANGHAI),
            )
        except KeyError:
            raise BacktestResultNotFoundError from None
        _require_bounded_items((response,))
        return response


def _run_snapshot(
    snapshot: tuple[int, ...] | None,
    *,
    pinned: bool,
) -> tuple[int, int | None]:
    expected_length = 2 if pinned else 1
    if snapshot is None or len(snapshot) != expected_length:
        raise ValueError("run cursor snapshot has invalid arity")
    return snapshot[0], snapshot[1] if pinned else None


def _two_part_position(value: tuple[str, ...] | None) -> tuple[str, str] | None:
    if value is None:
        return None
    if len(value) != 2:
        raise InvalidCursorError
    return value[0], value[1]


def _required_cursor_position(value: tuple[str, ...] | None) -> tuple[str, str]:
    position = _two_part_position(value)
    if position is None:
        raise InvalidCursorError
    return position


def _required_high_water(value: tuple[str, str] | None) -> tuple[str, str]:
    if value is None:
        raise RuntimeError("non-empty result page is missing its high-water mark")
    return value


def _require_bounded_items(items: tuple[BaseModel, ...]) -> None:
    for item in items:
        if len(item.model_dump_json().encode("utf-8")) > _MAX_ITEM_BYTES:
            raise RuntimeError("serialized result item exceeds 32 KiB")


def _require_bounded_page(page: BaseModel) -> None:
    try:
        require_bounded_page_json(page.model_dump_json())
    except ValueError as error:
        raise RuntimeError("serialized result page exceeds 4 MiB") from error


__all__ = [
    "BacktestArtifactAvailability",
    "BacktestDetailFilters",
    "BacktestDetailPage",
    "BacktestEquitySeries",
    "BacktestFillPage",
    "BacktestResultNotFoundError",
    "BacktestResultService",
    "BacktestRunMembershipConflictError",
    "BacktestRunFilters",
    "BacktestRunPage",
]
