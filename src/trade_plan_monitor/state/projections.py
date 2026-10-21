"""Durable complete-result projections owned by one caller transaction."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.engine import canonical_result_json
from trade_plan_monitor.decision.models import (
    EvaluationIdentity,
    EvaluationResult,
    IntradayEvaluationIdentity,
    OfficialCloseEvaluationIdentity,
)
from trade_plan_monitor.market_index.canonical import (
    canonical_json as canonical_market_index_json,
)
from trade_plan_monitor.market_index.canonical import (
    validate_market_index_snapshot_integrity,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexSnapshot
from trade_plan_monitor.market_index.selection import retain_effective_snapshot, snapshot_rank
from trade_plan_monitor.runtime.health import LEGACY_RUNTIME_GENERATION
from trade_plan_monitor.state.models import (
    EvaluationLedger,
    PlanActivationState,
    PlanVersion,
)
from trade_plan_monitor.state.models import (
    EvaluationResult as EvaluationResultRow,
)
from trade_plan_monitor.state.models import MarketIndexAcquisitionState as IndexAcquisitionRow
from trade_plan_monitor.state.models import MarketIndexRecoveryState as MarketIndexRecoveryRow
from trade_plan_monitor.state.models import (
    MarketIndexSnapshot as MarketIndexSnapshotRow,
)
from trade_plan_monitor.state.models import (
    MarketIndexSnapshotHead as MarketIndexSnapshotHeadRow,
)
from trade_plan_monitor.state.models import (
    MonitorEvent as MonitorEventRow,
)
from trade_plan_monitor.state.models import (
    PendingOfficialClose as PendingOfficialCloseRow,
)
from trade_plan_monitor.state.models import (
    SymbolDecisionHead as SymbolDecisionHeadRow,
)
from trade_plan_monitor.state.models import (
    SymbolHealthProjection as SymbolHealthProjectionRow,
)
from trade_plan_monitor.state.repositories import PositionLotRecord, RepositoryError

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_PATTERN = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_CANONICAL_RESULT_THRESHOLD_PATTERN = re.compile(
    r'("threshold_ratio"\s*:\s*")(-?[0-9]+e-?[0-9]+)(")'
)
_MAX_RESULT_JSON_BYTES = 8 * 1024 * 1024
_MAX_POSITION_LOTS = 200
_MAX_INDEX_JSON_BYTES = 16 * 1024 * 1024
_MAX_HEALTH_JSON_BYTES = 1024 * 1024
_MAX_PENDING_JSON_BYTES = 64 * 1024


class ProjectionError(RepositoryError):
    """Base error for invalid or conflicting live projection state."""

    code = "PROJECTION_ERROR"


class ProjectionMissingDependencyError(ProjectionError):
    """A result or head cannot name a missing durable dependency."""

    code = "PROJECTION_DEPENDENCY_MISSING"


class ProjectionIdentityConflictError(ProjectionError):
    """An immutable identity already names different canonical content."""

    code = "PROJECTION_IDENTITY_CONFLICT"


class ProjectionRevisionConflictError(ProjectionError):
    """A mutable projection did not advance from its durable revision."""

    code = "PROJECTION_REVISION_CONFLICT"

    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"Projection revision conflict; current revision is {current_revision}")


class _ProjectionValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DecisionHeadRecord(_ProjectionValue):
    """Validated complete decision and the event that made it visible."""

    result: EvaluationResult
    position_lots: tuple[PositionLotRecord, ...]
    activation_revision: Annotated[int, Field(strict=True, ge=1)]
    event_sequence: Annotated[int, Field(strict=True, ge=1)]
    updated_at: datetime


class SymbolHealthProjectionRecord(_ProjectionValue):
    """Opaque-but-validated public health JSON at one monotonic revision."""

    symbol: str
    revision: Annotated[int, Field(strict=True, ge=1)]
    activation_revision: Annotated[int, Field(strict=True, ge=1)]
    runtime_generation: UUID
    projection: dict[str, object]
    observed_at: datetime
    schema_version: Literal[1] = 1


class PendingOfficialCloseRecord(_ProjectionValue):
    """One exact official-close retry identity and canonical resume payload."""

    plan_hash: str
    symbol: str
    trade_date: date
    formula_version: str
    pending: dict[str, object]
    created_at: datetime
    updated_at: datetime


class MarketIndexHeadRecord(_ProjectionValue):
    """Validated immutable index snapshot at one current request-domain head."""

    snapshot: MarketIndexSnapshot
    provider_content_revision: Annotated[int, Field(strict=True, ge=1)]
    updated_at: datetime


class MarketIndexSnapshotRecord(_ProjectionValue):
    """Validated immutable index snapshot and its authenticated source revision."""

    snapshot: MarketIndexSnapshot
    provider_content_revision: Annotated[int, Field(strict=True, ge=1)]


class ProjectionRepository:
    """Read and mutate complete projections inside the active Unit of Work."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_evaluation_result(
        self,
        result: EvaluationResult,
        *,
        position_lots: Sequence[PositionLotRecord] = (),
    ) -> bool:
        """Attach one canonical complete result to a claim without rewriting it."""

        if type(result) is not EvaluationResult:
            raise TypeError("result must be an exact EvaluationResult")
        identity = _evaluation_identity(result.evaluation_identity)
        ledger = self._session.get(EvaluationLedger, identity)
        if ledger is None:
            raise ProjectionMissingDependencyError(
                "A complete evaluation result requires its ledger claim"
            )
        source_at = result.snapshot.market_data_at
        result_json = canonical_result_json(result)
        _bounded_json(result_json, _MAX_RESULT_JSON_BYTES, "evaluation result")
        normalized_lots = _validate_position_lots(result, position_lots)
        position_lots_json = json.dumps(
            [lot.model_dump(mode="json", round_trip=True) for lot in normalized_lots],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        _bounded_json(position_lots_json, _MAX_RESULT_JSON_BYTES, "position lots")
        if (
            ledger.result_hash != result.result_hash
            or ledger.evaluated_at != result.snapshot.evaluated_at.isoformat()
        ):
            raise ProjectionIdentityConflictError(
                "Evaluation claim does not match the complete result"
            )

        statement = sqlite_insert(EvaluationResultRow).values(
            plan_hash=identity[0],
            symbol=identity[1],
            evaluation_kind=identity[2],
            target_value=identity[3],
            formula_version=identity[4],
            result_hash=result.result_hash,
            result_json=result_json,
            position_lots_json=position_lots_json,
            evaluated_at=result.snapshot.evaluated_at.isoformat(),
            source_at=None if source_at is None else source_at.isoformat(),
            schema_version=1,
        )
        inserted = self._session.execute(
            statement.on_conflict_do_nothing(
                index_elements=[
                    EvaluationResultRow.plan_hash,
                    EvaluationResultRow.symbol,
                    EvaluationResultRow.evaluation_kind,
                    EvaluationResultRow.target_value,
                    EvaluationResultRow.formula_version,
                ]
            )
        )
        self._session.flush()
        self._session.expire_all()
        restored = self.get_evaluation_result(result.evaluation_identity)
        if restored != result:
            raise ProjectionIdentityConflictError(
                "Evaluation identity already has different complete content"
            )
        restored_lots = self.get_evaluation_position_lots(result.evaluation_identity)
        if restored_lots != normalized_lots:
            raise ProjectionIdentityConflictError(
                "Evaluation identity already has different position lots"
            )
        return inserted.rowcount == 1

    def get_evaluation_result(
        self,
        identity: EvaluationIdentity,
    ) -> EvaluationResult | None:
        key = _evaluation_identity(identity)
        row = self._session.get(EvaluationResultRow, key)
        return None if row is None else _result_from_row(row)

    def get_evaluation_position_lots(
        self,
        identity: EvaluationIdentity,
    ) -> tuple[PositionLotRecord, ...] | None:
        key = _evaluation_identity(identity)
        row = self._session.get(EvaluationResultRow, key)
        return None if row is None else _position_lots_from_row(row)

    def advance_decision_head(
        self,
        *,
        result: EvaluationResult,
        event_sequence: int,
        activation_revision: int | None = None,
    ) -> DecisionHeadRecord:
        """Advance one symbol only to a complete result's committed event."""

        if type(result) is not EvaluationResult:
            raise TypeError("result must be an exact EvaluationResult")
        sequence = _positive_integer(event_sequence, "event_sequence")
        identity = _evaluation_identity(result.evaluation_identity)
        stored_result = self.get_evaluation_result(result.evaluation_identity)
        if stored_result is None:
            raise ProjectionMissingDependencyError(
                "Decision head requires a complete evaluation result"
            )
        if stored_result != result:
            raise ProjectionIdentityConflictError(
                "Decision head result differs from its immutable payload"
            )
        event_row = self._session.scalar(
            select(MonitorEventRow).where(MonitorEventRow.sequence == sequence)
        )
        if event_row is None:
            raise ProjectionMissingDependencyError(
                "Decision head requires its durable monitor event"
            )
        _validate_decision_event(event_row, result)
        activation_revision = _active_activation_revision(
            self._session,
            symbol=identity[1],
            plan_hash=identity[0],
            expected_revision=activation_revision,
        )

        current = self._session.get(SymbolDecisionHeadRow, identity[1])
        if current is not None and current.activation_revision == activation_revision:
            current_result_row = self._session.get(
                EvaluationResultRow,
                (
                    current.plan_hash,
                    current.symbol,
                    current.evaluation_kind,
                    current.target_value,
                    current.formula_version,
                ),
            )
            if current_result_row is None:
                raise ProjectionError("Stored decision head has no complete result")
            current_result = _result_from_row(current_result_row)
            if _decision_head_rank(current_result) > _decision_head_rank(result):
                raise ProjectionRevisionConflictError(current.event_sequence)
        values = {
            "plan_hash": identity[0],
            "evaluation_kind": identity[2],
            "target_value": identity[3],
            "formula_version": identity[4],
            "result_hash": result.result_hash,
            "activation_revision": activation_revision,
            "event_sequence": sequence,
            "updated_at": event_row.occurred_at,
        }
        if current is None:
            self._session.add(SymbolDecisionHeadRow(symbol=identity[1], **values))
        elif current.event_sequence > sequence:
            raise ProjectionRevisionConflictError(current.event_sequence)
        elif current.event_sequence == sequence:
            if any(getattr(current, name) != value for name, value in values.items()):
                raise ProjectionIdentityConflictError(
                    "Decision event sequence already names another head"
                )
        else:
            for name, value in values.items():
                setattr(current, name, value)
        self._session.flush()
        self._session.expire_all()
        restored = self.get_decision_head(identity[1])
        if restored is None:  # pragma: no cover - protected by successful flush
            raise ProjectionError("Decision head could not be reloaded")
        return restored

    def get_decision_head(self, symbol: str) -> DecisionHeadRecord | None:
        normalized_symbol = _symbol(symbol)
        row = self._session.get(SymbolDecisionHeadRow, normalized_symbol)
        if row is None:
            return None
        result_row = self._session.get(
            EvaluationResultRow,
            (
                row.plan_hash,
                row.symbol,
                row.evaluation_kind,
                row.target_value,
                row.formula_version,
            ),
        )
        if result_row is None:
            raise ProjectionError("Stored decision head has no complete result")
        result = _result_from_row(result_row)
        if result.result_hash != row.result_hash:
            raise ProjectionError("Stored decision head result hash is invalid")
        event_row = self._session.scalar(
            select(MonitorEventRow).where(MonitorEventRow.sequence == row.event_sequence)
        )
        if event_row is None:
            raise ProjectionError("Stored decision head has no durable event")
        _validate_decision_event(event_row, result)
        return DecisionHeadRecord(
            result=result,
            position_lots=_position_lots_from_row(result_row),
            activation_revision=row.activation_revision,
            event_sequence=row.event_sequence,
            updated_at=_market_datetime(row.updated_at, "updated_at"),
        )

    def list_decision_heads(self) -> tuple[DecisionHeadRecord, ...]:
        symbols = self._session.scalars(
            select(SymbolDecisionHeadRow.symbol).order_by(SymbolDecisionHeadRow.symbol)
        ).all()
        records = tuple(self.get_decision_head(symbol) for symbol in symbols)
        if any(record is None for record in records):  # pragma: no cover - same-query invariant
            raise ProjectionError("Stored decision head disappeared during one transaction")
        return tuple(record for record in records if record is not None)

    def put_symbol_health(
        self,
        *,
        symbol: str,
        revision: int,
        activation_revision: int | None = None,
        runtime_generation: UUID = LEGACY_RUNTIME_GENERATION,
        projection: Mapping[str, object] | BaseModel,
        observed_at: datetime,
    ) -> SymbolHealthProjectionRecord:
        normalized_symbol = _symbol(symbol)
        normalized_revision = _positive_integer(revision, "revision")
        normalized_runtime_generation = _uuid(runtime_generation, "runtime_generation")
        normalized_observed_at = _market_datetime(observed_at, "observed_at")
        projection_json = _projection_json(
            projection,
            maximum_bytes=_MAX_HEALTH_JSON_BYTES,
            label="symbol health projection",
        )
        payload = _json_object(projection_json, "symbol health projection")
        if payload.get("symbol") != normalized_symbol:
            raise ValueError("health projection symbol does not match its identity")
        if (
            _market_datetime(payload.get("observedAt"), "projection observedAt")
            != normalized_observed_at
        ):
            raise ValueError("health projection observation does not match its identity")
        activation_revision = _active_activation_revision(
            self._session,
            symbol=normalized_symbol,
            expected_revision=activation_revision,
        )

        current = self._session.get(SymbolHealthProjectionRow, normalized_symbol)
        values = {
            "revision": normalized_revision,
            "activation_revision": activation_revision,
            "runtime_generation": str(normalized_runtime_generation),
            "projection_json": projection_json,
            "observed_at": normalized_observed_at.isoformat(),
            "schema_version": 1,
        }
        if current is None:
            # A pre-0009 legacy symbol_health row may already own a higher
            # revision.  The first public projection inherits that authoritative
            # revision; subsequent updates remain strictly monotonic.
            self._session.add(SymbolHealthProjectionRow(symbol=normalized_symbol, **values))
        elif normalized_revision != current.revision + 1:
            if normalized_revision == current.revision and all(
                getattr(current, name) == value for name, value in values.items()
            ):
                return _health_from_row(current)
            raise ProjectionRevisionConflictError(current.revision)
        else:
            for name, value in values.items():
                setattr(current, name, value)
        self._session.flush()
        self._session.expire_all()
        restored = self.get_symbol_health(normalized_symbol)
        if restored is None:  # pragma: no cover - protected by successful flush
            raise ProjectionError("Symbol health projection could not be reloaded")
        return restored

    def get_symbol_health(self, symbol: str) -> SymbolHealthProjectionRecord | None:
        row = self._session.get(SymbolHealthProjectionRow, _symbol(symbol))
        return None if row is None else _health_from_row(row)

    def put_pending_official_close(
        self,
        *,
        plan_hash: str,
        symbol: str,
        trade_date: date,
        formula_version: str,
        pending: Mapping[str, object] | BaseModel,
        observed_at: datetime,
    ) -> PendingOfficialCloseRecord:
        identity = (
            _sha256(plan_hash, "plan_hash"),
            _symbol(symbol),
            _trade_date(trade_date),
            _token(formula_version, "formula_version", maximum=32),
        )
        timestamp = _market_datetime(observed_at, "observed_at")
        pending_json = _projection_json(
            pending,
            maximum_bytes=_MAX_PENDING_JSON_BYTES,
            label="pending official close",
        )
        existing = self._session.scalar(
            select(PendingOfficialCloseRow).where(
                PendingOfficialCloseRow.symbol == identity[1],
            )
        )
        if (
            existing is not None
            and (
                existing.plan_hash,
                existing.symbol,
                existing.trade_date,
                existing.formula_version,
            )
            != identity
        ):
            raise ProjectionIdentityConflictError(
                "Symbol already has another unresolved official-close identity"
            )
        current = self._session.get(PendingOfficialCloseRow, identity)
        if current is None:
            self._session.add(
                PendingOfficialCloseRow(
                    plan_hash=identity[0],
                    symbol=identity[1],
                    trade_date=identity[2],
                    formula_version=identity[3],
                    pending_json=pending_json,
                    created_at=timestamp.isoformat(),
                    updated_at=timestamp.isoformat(),
                )
            )
        else:
            current.pending_json = pending_json
            current.updated_at = timestamp.isoformat()
        self._session.flush()
        self._session.expire_all()
        restored = self._session.get(PendingOfficialCloseRow, identity)
        if restored is None:  # pragma: no cover - protected by successful flush
            raise ProjectionError("Pending official close could not be reloaded")
        return _pending_from_row(restored)

    def get_pending_official_close(
        self,
        *,
        symbol: str,
        trade_date: date,
    ) -> PendingOfficialCloseRecord | None:
        rows = self._session.scalars(
            select(PendingOfficialCloseRow).where(
                PendingOfficialCloseRow.symbol == _symbol(symbol),
                PendingOfficialCloseRow.trade_date == _trade_date(trade_date),
            )
        ).all()
        if len(rows) > 1:
            raise ProjectionError("Stored symbol/date has multiple pending close identities")
        return None if not rows else _pending_from_row(rows[0])

    def list_pending_official_closes(
        self,
        *,
        symbol: str,
    ) -> tuple[PendingOfficialCloseRecord, ...]:
        rows = self._session.scalars(
            select(PendingOfficialCloseRow)
            .where(PendingOfficialCloseRow.symbol == _symbol(symbol))
            .order_by(
                PendingOfficialCloseRow.trade_date,
                PendingOfficialCloseRow.plan_hash,
                PendingOfficialCloseRow.formula_version,
            )
        ).all()
        return tuple(_pending_from_row(row) for row in rows)

    def clear_pending_official_close(
        self,
        *,
        plan_hash: str,
        symbol: str,
        trade_date: date,
        formula_version: str,
    ) -> bool:
        result = self._session.execute(
            delete(PendingOfficialCloseRow).where(
                PendingOfficialCloseRow.plan_hash == _sha256(plan_hash, "plan_hash"),
                PendingOfficialCloseRow.symbol == _symbol(symbol),
                PendingOfficialCloseRow.trade_date == _trade_date(trade_date),
                PendingOfficialCloseRow.formula_version
                == _token(formula_version, "formula_version", maximum=32),
            )
        )
        self._session.flush()
        return result.rowcount == 1

    def list_market_index_recoveries(
        self,
        *, include_exhausted: bool = False,
    ) -> tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...]:
        rows = self._session.scalars(select(MarketIndexRecoveryRow)).all()
        return tuple(
            (
                MarketIndexCode(row.index_code),
                _market_datetime(row.decision_cutoff, "decision_cutoff"),
                _market_datetime(row.first_failed_at, "first_failed_at"),
                row.attempts,
                _market_datetime(row.due_at, "due_at"),
            )
            for row in rows
            if include_exhausted or row.attempts < 3
        )

    def replace_market_index_recoveries(
        self,
        records: tuple[tuple[MarketIndexCode, datetime, datetime, int, datetime], ...],
        *, kinds: Mapping[MarketIndexCode, str] | None = None,
        source_identity: str | None = None,
    ) -> None:
        existing = self._session.scalars(select(MarketIndexRecoveryRow)).all()
        selected = {record[0].value for record in records}
        for row in existing:
            if row.index_code not in selected:
                self._session.delete(row)
        for code, cutoff, first_failed_at, attempts, due_at in records:
            kind = (kinds or {}).get(code, "TRANSIENT")
            if kind not in {"TRANSIENT", "FINAL_BUCKET"} or not (
                0 <= attempts <= 3
                if kind == "FINAL_BUCKET" or (cutoff.hour, cutoff.minute) in ((11, 30), (15, 0))
                else 0 <= attempts < 3
            ) or due_at <= first_failed_at:
                raise ValueError("market-index recovery state is invalid")
            row = self._session.get(MarketIndexRecoveryRow, code.value)
            if row is None:
                row = MarketIndexRecoveryRow(index_code=code.value)
                self._session.add(row)
            row.decision_cutoff = _market_datetime(cutoff, "decision_cutoff").isoformat()
            row.first_failed_at = _market_datetime(
                first_failed_at, "first_failed_at"
            ).isoformat()
            row.attempts = attempts
            row.due_at = _market_datetime(due_at, "due_at").isoformat()
            row.kind = kind
            row.source_identity = source_identity

    def market_index_recovery_kinds(self, *, source_identity: str | None = None) -> dict:
        rows = self._session.scalars(select(MarketIndexRecoveryRow)).all()
        return {MarketIndexCode(row.index_code): row.kind for row in rows
            if source_identity is None or row.source_identity == source_identity}

    def put_market_index_snapshot(
        self,
        snapshot: MarketIndexSnapshot,
        *,
        provider_content_revision: int,
    ) -> bool:
        if type(snapshot) is not MarketIndexSnapshot:
            raise TypeError("snapshot must be an exact MarketIndexSnapshot")
        validate_market_index_snapshot_integrity(snapshot)
        provider_revision = _positive_integer(
            provider_content_revision,
            "provider_content_revision",
        )
        if provider_revision != snapshot.cache_key.provider_content_revision:
            raise ValueError("provider content revision does not match snapshot cache identity")
        snapshot_json = canonical_market_index_json(snapshot)
        _bounded_json(snapshot_json, _MAX_INDEX_JSON_BYTES, "market-index snapshot")
        values = _market_index_values(snapshot, provider_revision, snapshot_json)
        statement = sqlite_insert(MarketIndexSnapshotRow).values(**values)
        inserted = self._session.execute(
            statement.on_conflict_do_nothing(index_elements=[MarketIndexSnapshotRow.snapshot_hash])
        )
        self._session.flush()
        self._session.expire_all()
        row = self._session.get(MarketIndexSnapshotRow, snapshot.snapshot_hash)
        if row is None:  # pragma: no cover - protected by successful insert
            raise ProjectionError("Market-index snapshot could not be reloaded")
        restored, restored_provider_revision = _market_index_from_row(row)
        if restored != snapshot or restored_provider_revision != provider_revision:
            raise ProjectionIdentityConflictError(
                "Market-index snapshot hash already has different canonical content"
            )
        return inserted.rowcount == 1

    def advance_market_index_head(
        self,
        snapshot: MarketIndexSnapshot,
        *,
        provider_content_revision: int,
        observed_at: datetime | None = None,
    ) -> MarketIndexHeadRecord:
        if type(snapshot) is not MarketIndexSnapshot:
            raise TypeError("snapshot must be an exact MarketIndexSnapshot")
        provider_revision = _positive_integer(
            provider_content_revision,
            "provider_content_revision",
        )
        row = self._session.get(MarketIndexSnapshotRow, snapshot.snapshot_hash)
        if row is None:
            raise ProjectionMissingDependencyError(
                "Market-index head requires its immutable snapshot"
            )
        restored, restored_provider_revision = _market_index_from_row(row)
        if restored != snapshot or restored_provider_revision != provider_revision:
            raise ProjectionIdentityConflictError(
                "Market-index head identity differs from its immutable snapshot"
            )
        head_observed_at = (
            snapshot.observed_at
            if observed_at is None
            else _market_datetime(observed_at, "observed_at")
        )
        if head_observed_at < snapshot.observed_at:
            raise ValueError("market-index head cannot precede its immutable snapshot")

        key = (
            snapshot.mapping_version,
            snapshot.index_code.value,
            snapshot.decision_cutoff.isoformat(),
            snapshot.request_set_hash,
        )
        current = self._session.get(MarketIndexSnapshotHeadRow, key)
        if current is not None:
            previous = self.get_market_index_snapshot(current.snapshot_hash)
            if previous is None:
                raise ProjectionMissingDependencyError("Effective index payload is missing")
            if retain_effective_snapshot(
                previous.snapshot,
                snapshot,
                current_observed_at=_market_datetime(current.updated_at, "updated_at"),
                incoming_observed_at=head_observed_at,
            ):
                return self.get_market_index_head(
                    mapping_version=snapshot.mapping_version, index_code=snapshot.index_code,
                    decision_cutoff=snapshot.decision_cutoff,
                    request_set_hash=snapshot.request_set_hash,
                )
        values = {
            "provider_content_revision": provider_revision,
            "snapshot_hash": snapshot.snapshot_hash,
            "updated_at": head_observed_at.isoformat(),
        }
        if current is None:
            self._session.add(
                MarketIndexSnapshotHeadRow(
                    mapping_version=key[0],
                    index_code=key[1],
                    decision_cutoff=key[2],
                    request_set_hash=key[3],
                    **values,
                )
            )
        elif current.provider_content_revision == provider_revision:
            if current.snapshot_hash != snapshot.snapshot_hash:
                raise ProjectionIdentityConflictError(
                    "Market-index revision already names another snapshot head"
                )
            current_observed_at = _market_datetime(current.updated_at, "updated_at")
            if current_observed_at > head_observed_at:
                raise ProjectionRevisionConflictError(current.provider_content_revision)
            current.updated_at = head_observed_at.isoformat()
        elif _market_datetime(current.updated_at, "updated_at") >= head_observed_at:
            raise ProjectionRevisionConflictError(current.provider_content_revision)
        else:
            for name, value in values.items():
                setattr(current, name, value)
        self._session.flush()
        self._session.expire_all()
        restored_head = self.get_market_index_head(
            mapping_version=snapshot.mapping_version,
            index_code=snapshot.index_code,
            decision_cutoff=snapshot.decision_cutoff,
            request_set_hash=snapshot.request_set_hash,
        )
        if restored_head is None:  # pragma: no cover - protected by successful flush
            raise ProjectionError("Market-index head could not be reloaded")
        return restored_head

    def get_market_index_snapshot(
        self,
        snapshot_hash: str,
    ) -> MarketIndexSnapshotRecord | None:
        row = self._session.get(
            MarketIndexSnapshotRow,
            _sha256(snapshot_hash, "snapshot_hash"),
        )
        if row is None:
            return None
        snapshot, provider_revision = _market_index_from_row(row)
        return MarketIndexSnapshotRecord(
            snapshot=snapshot,
            provider_content_revision=provider_revision,
        )

    def put_market_index_acquisition(
        self, snapshot: MarketIndexSnapshot, *, observed_at: datetime, sequence: int,
        source_identity: str | None = None,
    ) -> None:
        """Record a committed attempted capture without granting data authority."""
        validate_market_index_snapshot_integrity(snapshot)
        key = (snapshot.mapping_version, snapshot.index_code.value)
        row = self._session.get(IndexAcquisitionRow, key)
        if row is not None and (
            _market_datetime(row.decision_cutoff, "decision_cutoff"),
            _market_datetime(row.observed_at, "observed_at"), row.sequence,
        ) > (snapshot.decision_cutoff, observed_at, sequence):
            return
        if row is None:
            row = IndexAcquisitionRow(mapping_version=key[0], index_code=key[1])
            self._session.add(row)
        row.attempt_id = snapshot.snapshot_hash
        row.decision_cutoff = snapshot.decision_cutoff.isoformat()
        row.request_set_hash = snapshot.request_set_hash
        row.observed_at = _market_datetime(observed_at, "observed_at").isoformat()
        row.snapshot_hash = snapshot.snapshot_hash
        row.health = snapshot.health.value
        row.issues_json = json.dumps([issue.value for issue in snapshot.issues])
        row.sequence = sequence
        row.source_identity = source_identity
        head = self.get_market_index_head(
            mapping_version=snapshot.mapping_version, index_code=snapshot.index_code,
            decision_cutoff=snapshot.decision_cutoff, request_set_hash=snapshot.request_set_hash,
        )
        if head is not None and head.snapshot.snapshot_hash == snapshot.snapshot_hash:
            row.effective_source_identity = source_identity
            row.effective_snapshot_hash = snapshot.snapshot_hash
        self._session.flush()

    def market_index_source_matches(
        self, snapshot: MarketIndexSnapshot, source_identity: str | None
    ) -> bool:
        row = self._session.get(
            IndexAcquisitionRow, (snapshot.mapping_version, snapshot.index_code.value)
        )
        return bool(row is not None and source_identity is not None
            and row.effective_source_identity == source_identity
            and row.effective_snapshot_hash == snapshot.snapshot_hash)

    def list_market_index_acquisitions(self, *, mapping_version: str) -> tuple:
        rows = self._session.scalars(select(IndexAcquisitionRow).where(
            IndexAcquisitionRow.mapping_version == mapping_version
        )).all()
        result = []
        for row in rows:
            record = self.get_market_index_snapshot(row.snapshot_hash)
            if record is None or (
                record.snapshot.index_code.value != row.index_code
                or record.snapshot.mapping_version != row.mapping_version
                or record.snapshot.decision_cutoff != _market_datetime(
                    row.decision_cutoff, "decision_cutoff"
                )
                or record.snapshot.request_set_hash != row.request_set_hash
                or row.attempt_id != record.snapshot.snapshot_hash
                or row.sequence < 0
                or record.snapshot.health.value != row.health
                or [i.value for i in record.snapshot.issues] != json.loads(row.issues_json)
            ):
                raise ProjectionIdentityConflictError("Invalid index acquisition linkage")
            result.append((record.snapshot, _market_datetime(row.observed_at, "observed_at")))
        return tuple(result)

    def repair_market_index_heads(self, *, trade_date: date, mapping_version: str) -> int:
        """Restore only poisoned exact-key heads from validated immutable LIVE captures."""
        heads = self._session.scalars(select(MarketIndexSnapshotHeadRow).where(
            MarketIndexSnapshotHeadRow.mapping_version == mapping_version,
            MarketIndexSnapshotHeadRow.decision_cutoff.like(f"{trade_date.isoformat()}T%"),
        )).all()
        repaired = 0
        for head in heads:
            current = self.get_market_index_snapshot(head.snapshot_hash)
            if current is None:
                raise ProjectionMissingDependencyError("Repair head has no payload")
            if current.snapshot.health.value == "LIVE":
                continue
            rows = self._session.scalars(select(MarketIndexSnapshotRow).where(
                MarketIndexSnapshotRow.mapping_version == head.mapping_version,
                MarketIndexSnapshotRow.index_code == head.index_code,
                MarketIndexSnapshotRow.decision_cutoff == head.decision_cutoff,
                MarketIndexSnapshotRow.request_set_hash == head.request_set_hash,
            )).all()
            candidates = [_market_index_from_row(row)[0] for row in rows]
            live = [item for item in candidates if item.health.value == "LIVE"]
            if not live:
                continue
            selected = max(live, key=lambda item: (item.observed_at, item.snapshot_hash))
            head.snapshot_hash = selected.snapshot_hash
            head.provider_content_revision = selected.cache_key.provider_content_revision
            head.updated_at = selected.observed_at.isoformat()
            repaired += 1
        self._session.flush()
        return repaired

    def backfill_market_index_acquisitions(self, *, trade_date: date, mapping_version: str) -> int:
        """Use exact committed event identities; uncertain links remain absent."""
        from trade_plan_monitor.state.events import MonitorEventType, monitor_event_id

        rows = self._session.scalars(select(MarketIndexSnapshotRow).where(
            MarketIndexSnapshotRow.mapping_version == mapping_version,
            MarketIndexSnapshotRow.decision_cutoff.like(f"{trade_date.isoformat()}T%"),
        ).limit(4097)).all()
        if len(rows) > 4096:
            raise ProjectionError("Index repair exceeds its daily capture bound")
        selected = {}
        for row in rows:
            snapshot, _ = _market_index_from_row(row)
            event_id = monitor_event_id(
                MonitorEventType.MARKET_INDEX_UPDATED, snapshot.index_code.value,
                snapshot.decision_cutoff.isoformat(), snapshot.request_set_hash,
                snapshot.snapshot_hash, snapshot.observed_at.isoformat(),
            )
            event = self._session.get(MonitorEventRow, str(event_id))
            if event is None:
                continue
            current = selected.get(snapshot.index_code)
            if current is None or event.sequence > current[1].sequence:
                selected[snapshot.index_code] = (snapshot, event)
        count = 0
        for code, (snapshot, event) in selected.items():
            if self._session.get(IndexAcquisitionRow, (mapping_version, code.value)) is None:
                self.put_market_index_acquisition(snapshot,
                    observed_at=_market_datetime(event.occurred_at, "occurred_at"),
                    sequence=event.sequence)
                count += 1
        return count

    def list_latest_market_index_snapshots(
        self,
        *,
        mapping_version: str,
        index_codes: tuple[MarketIndexCode, ...],
    ) -> tuple[MarketIndexSnapshotRecord, ...]:
        if (
            type(index_codes) is not tuple
            or len(set(index_codes)) != len(index_codes)
            or any(not isinstance(index_code, MarketIndexCode) for index_code in index_codes)
        ):
            raise TypeError("index_codes must be a tuple of unique MarketIndexCode values")
        normalized_mapping_version = _token(
            mapping_version,
            "mapping_version",
            maximum=32,
        )
        if not index_codes:
            return ()
        candidates = self._session.execute(
            select(MarketIndexSnapshotHeadRow, MarketIndexSnapshotRow)
            .outerjoin(
                MarketIndexSnapshotRow,
                MarketIndexSnapshotHeadRow.snapshot_hash == MarketIndexSnapshotRow.snapshot_hash,
            )
            .where(
                MarketIndexSnapshotHeadRow.mapping_version == normalized_mapping_version,
                MarketIndexSnapshotHeadRow.index_code.in_(
                    tuple(index_code.value for index_code in index_codes)
                ),
            )
            .execution_options(yield_per=128, populate_existing=True)
        )
        latest_by_index: dict[MarketIndexCode, MarketIndexSnapshotRecord] = {}
        for head, row in candidates:
            if row is None:
                raise ProjectionMissingDependencyError(
                    "Market-index head names a missing immutable snapshot"
                )
            # Every historical candidate is verified, even when it cannot win.
            snapshot, provider_revision = _market_index_from_row(row)
            if (
                snapshot.mapping_version != head.mapping_version
                or snapshot.index_code.value != head.index_code
                or snapshot.decision_cutoff.isoformat() != head.decision_cutoff
                or snapshot.request_set_hash != head.request_set_hash
                or provider_revision != head.provider_content_revision
            ):
                raise ProjectionError("Stored market-index head crosses snapshot identity")
            record = MarketIndexSnapshotRecord(
                snapshot=snapshot, provider_content_revision=provider_revision,
            )
            index_code = record.snapshot.index_code
            current = latest_by_index.get(index_code)
            incoming_rank = _market_index_snapshot_rank(record.snapshot)
            current_rank = (
                None if current is None else _market_index_snapshot_rank(current.snapshot)
            )
            if current_rank is None or incoming_rank > current_rank:
                latest_by_index[index_code] = record
        return tuple(
            latest_by_index[index_code]
            for index_code in index_codes
            if index_code in latest_by_index
        )

    def list_market_index_snapshot_heads(
        self,
        *,
        mapping_version: str,
        index_code: MarketIndexCode,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[MarketIndexSnapshotRecord, ...]:
        """Return immutable payloads named by current heads in one cutoff range."""

        if not isinstance(index_code, MarketIndexCode):
            raise TypeError("index_code must be a MarketIndexCode")
        normalized_mapping_version = _token(
            mapping_version,
            "mapping_version",
            maximum=32,
        )
        normalized_start = _market_datetime(start_at, "start_at")
        normalized_end = _market_datetime(end_at, "end_at")
        if normalized_start > normalized_end:
            raise ValueError("start_at cannot follow end_at")
        heads = self._session.scalars(
            select(MarketIndexSnapshotHeadRow)
            .where(
                MarketIndexSnapshotHeadRow.mapping_version
                == normalized_mapping_version,
                MarketIndexSnapshotHeadRow.index_code == index_code.value,
                MarketIndexSnapshotHeadRow.decision_cutoff
                >= normalized_start.isoformat(),
                MarketIndexSnapshotHeadRow.decision_cutoff
                <= normalized_end.isoformat(),
            )
            .order_by(
                MarketIndexSnapshotHeadRow.decision_cutoff,
                MarketIndexSnapshotHeadRow.request_set_hash,
            )
        ).all()
        snapshot_rows = self._session.scalars(
            select(MarketIndexSnapshotRow).where(
                MarketIndexSnapshotRow.snapshot_hash.in_(
                    tuple(head.snapshot_hash for head in heads)
                )
            )
        ).all()
        rows_by_hash = {row.snapshot_hash: row for row in snapshot_rows}
        records: list[MarketIndexSnapshotRecord] = []
        for head in heads:
            row = rows_by_hash.get(head.snapshot_hash)
            if row is None:  # pragma: no cover - foreign key protects this
                raise ProjectionMissingDependencyError(
                    "Market-index head names a missing immutable snapshot"
                )
            snapshot, provider_revision = _market_index_from_row(row)
            record = MarketIndexSnapshotRecord(
                snapshot=snapshot,
                provider_content_revision=provider_revision,
            )
            snapshot = record.snapshot
            if (
                snapshot.mapping_version != normalized_mapping_version
                or snapshot.index_code is not index_code
                or snapshot.decision_cutoff.isoformat() != head.decision_cutoff
                or snapshot.request_set_hash != head.request_set_hash
                or snapshot.revision != head.provider_content_revision
            ):
                raise ProjectionIdentityConflictError(
                    "Market-index head identity does not match its immutable snapshot"
                )
            records.append(record)
        return tuple(records)

    def get_market_index_snapshot_revision(
        self,
        *,
        mapping_version: str,
        index_code: str | MarketIndexCode,
        decision_cutoff: datetime,
        request_set_hash: str,
        provider_content_revision: int,
    ) -> MarketIndexSnapshotRecord | None:
        try:
            normalized_index_code = MarketIndexCode(index_code).value
        except TypeError, ValueError:
            raise ValueError("index_code is not supported") from None
        identity = (
            _token(mapping_version, "mapping_version", maximum=32),
            normalized_index_code,
            _market_datetime(decision_cutoff, "decision_cutoff").isoformat(),
            _sha256(request_set_hash, "request_set_hash"),
            _positive_integer(provider_content_revision, "provider_content_revision"),
        )
        row = self._session.scalar(
            select(MarketIndexSnapshotRow).where(
                MarketIndexSnapshotRow.mapping_version == identity[0],
                MarketIndexSnapshotRow.index_code == identity[1],
                MarketIndexSnapshotRow.decision_cutoff == identity[2],
                MarketIndexSnapshotRow.request_set_hash == identity[3],
                MarketIndexSnapshotRow.provider_content_revision == identity[4],
            )
        )
        if row is None:
            return None
        snapshot, provider_revision = _market_index_from_row(row)
        return MarketIndexSnapshotRecord(
            snapshot=snapshot,
            provider_content_revision=provider_revision,
        )

    def get_market_index_head(
        self,
        *,
        mapping_version: str,
        index_code: str | MarketIndexCode,
        decision_cutoff: datetime,
        request_set_hash: str,
    ) -> MarketIndexHeadRecord | None:
        try:
            normalized_index_code = MarketIndexCode(index_code).value
        except TypeError, ValueError:
            raise ValueError("index_code is not supported") from None
        key = (
            _token(mapping_version, "mapping_version", maximum=32),
            normalized_index_code,
            _market_datetime(decision_cutoff, "decision_cutoff").isoformat(),
            _sha256(request_set_hash, "request_set_hash"),
        )
        head = self._session.get(MarketIndexSnapshotHeadRow, key)
        if head is None:
            return None
        row = self._session.get(MarketIndexSnapshotRow, head.snapshot_hash)
        if row is None:
            raise ProjectionError("Stored market-index head has no immutable snapshot")
        snapshot, provider_revision = _market_index_from_row(row)
        if (
            snapshot.mapping_version != head.mapping_version
            or snapshot.index_code.value != head.index_code
            or snapshot.decision_cutoff.isoformat() != head.decision_cutoff
            or snapshot.request_set_hash != head.request_set_hash
            or provider_revision != head.provider_content_revision
        ):
            raise ProjectionError("Stored market-index head crosses snapshot identity")
        return MarketIndexHeadRecord(
            snapshot=snapshot,
            provider_content_revision=provider_revision,
            updated_at=_market_datetime(head.updated_at, "updated_at"),
        )


def _evaluation_identity(identity: EvaluationIdentity) -> tuple[str, str, str, str, str]:
    if isinstance(identity, IntradayEvaluationIdentity):
        target_value = _market_datetime(identity.bucket_end, "bucket_end").isoformat()
    elif isinstance(identity, OfficialCloseEvaluationIdentity):
        target_value = _trade_date(identity.official_trade_date).isoformat()
    else:
        raise TypeError("identity must be an evaluation identity")
    return (
        _sha256(identity.plan_hash, "plan_hash"),
        _symbol(identity.symbol),
        identity.kind,
        target_value,
        _token(identity.formula_version, "formula_version", maximum=32),
    )


def _active_activation_revision(
    session: Session,
    *,
    symbol: str,
    plan_hash: str | None = None,
    expected_revision: int | None = None,
) -> int:
    normalized_expected = (
        None
        if expected_revision is None
        else _positive_integer(expected_revision, "activation_revision")
    )
    state = session.get(PlanActivationState, symbol)
    if state is None:
        if normalized_expected not in {None, 1}:
            raise ProjectionRevisionConflictError(0)
        return 1
    if state.plan_version_id is None or state.revision < 1:
        raise ProjectionMissingDependencyError(
            "A public projection requires an active plan generation"
        )
    if normalized_expected is not None and state.revision != normalized_expected:
        raise ProjectionRevisionConflictError(state.revision)
    if plan_hash is not None:
        version = session.get(PlanVersion, state.plan_version_id)
        if version is None or version.symbol != symbol or version.plan_hash != plan_hash:
            raise ProjectionIdentityConflictError(
                "Decision projection does not match the active plan generation"
            )
    return state.revision


def _decision_head_rank(result: EvaluationResult) -> tuple[datetime, int, datetime]:
    identity = result.evaluation_identity
    if isinstance(identity, IntradayEvaluationIdentity):
        target_at = identity.bucket_end
        kind_rank = 0
    elif isinstance(identity, OfficialCloseEvaluationIdentity):
        target_at = datetime.combine(
            identity.official_trade_date,
            datetime.min.time().replace(hour=15),
            result.snapshot.evaluated_at.tzinfo,
        )
        kind_rank = 1
    else:  # pragma: no cover - closed EvaluationIdentity union
        raise TypeError("identity must be an evaluation identity")
    return target_at, kind_rank, result.snapshot.evaluated_at


def _market_index_snapshot_rank(snapshot: MarketIndexSnapshot) -> tuple:
    return snapshot_rank(snapshot)


def _result_validation_json(value: str) -> str:
    """Adapt canonical decision decimals to the stricter embedded plan parser."""

    _bounded_json(value, _MAX_RESULT_JSON_BYTES, "evaluation result")
    remaining_expansion = _MAX_RESULT_JSON_BYTES - len(value.encode("utf-8"))

    def restore(match: re.Match[str]) -> str:
        nonlocal remaining_expansion
        encoded = match.group(2)
        try:
            decimal = Decimal(encoded)
        except ArithmeticError, ValueError:  # pragma: no cover - closed regex
            raise ValueError("canonical result threshold is invalid") from None
        if not decimal.is_finite() or not Decimal("-1") <= decimal <= Decimal("10"):
            raise ValueError("canonical result threshold is outside its domain")
        sign, digits, exponent = decimal.as_tuple()
        if not isinstance(exponent, int):
            raise ValueError("canonical result threshold exponent must be finite")
        coefficient_length = len(digits)
        decimal_position = coefficient_length + exponent
        if exponent >= 0:
            length = coefficient_length + exponent
        elif decimal_position > 0:
            length = coefficient_length + 1
        else:
            length = 2 - decimal_position + coefficient_length
        growth = max(0, length + int(bool(sign)) - len(encoded))
        if growth > remaining_expansion:
            raise ValueError("canonical result threshold expansion is too large")
        remaining_expansion -= growth
        return f"{match.group(1)}{format(decimal, 'f')}{match.group(3)}"

    adapted = _CANONICAL_RESULT_THRESHOLD_PATTERN.sub(restore, value)
    _bounded_json(adapted, _MAX_RESULT_JSON_BYTES, "evaluation result")
    return adapted


def _result_from_row(row: EvaluationResultRow) -> EvaluationResult:
    try:
        result = EvaluationResult.model_validate_json(_result_validation_json(row.result_json))
        identity = _evaluation_identity(result.evaluation_identity)
        source_at = None if row.source_at is None else _market_datetime(row.source_at, "source_at")
        valid = (
            identity
            == (
                row.plan_hash,
                row.symbol,
                row.evaluation_kind,
                row.target_value,
                row.formula_version,
            )
            and row.result_hash == result.result_hash
            and row.evaluated_at == result.snapshot.evaluated_at.isoformat()
            and source_at == result.snapshot.market_data_at
            and row.schema_version == 1
            and canonical_result_json(result) == row.result_json
        )
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProjectionError("Stored complete evaluation result is invalid")
    return result


def _validate_position_lots(
    result: EvaluationResult,
    position_lots: Sequence[PositionLotRecord],
) -> tuple[PositionLotRecord, ...]:
    lots = tuple(position_lots)
    if len(lots) > _MAX_POSITION_LOTS:
        raise ValueError("position lots exceed the decision projection limit")
    if any(type(lot) is not PositionLotRecord for lot in lots):
        raise TypeError("position_lots must contain exact PositionLotRecord values")
    if len({lot.id for lot in lots}) != len(lots):
        raise ValueError("position lot identities must be unique")
    symbol = result.snapshot.symbol
    if any(
        lot.symbol != symbol or lot.remaining_qty <= 0 or lot.closed_at is not None for lot in lots
    ):
        raise ValueError("position lots must be open and match the decision symbol")
    ordered = tuple(sorted(lots, key=lambda lot: (lot.acquired_trade_date, lot.id)))
    if lots != ordered:
        raise ValueError("position lots must use canonical acquisition order")

    identity = result.evaluation_identity
    trade_date = (
        identity.bucket_end.date()
        if isinstance(identity, IntradayEvaluationIdentity)
        else identity.official_trade_date
    )
    position = result.snapshot.position
    core = tuple(lot for lot in lots if lot.bucket.value == "CORE")
    tactical = tuple(lot for lot in lots if lot.bucket.value == "TACTICAL")
    if (
        sum(lot.remaining_qty for lot in core) != position.core_quantity
        or sum(lot.remaining_qty for lot in tactical) != position.tactical_quantity
        or sum(lot.remaining_qty for lot in core if lot.acquired_trade_date < trade_date)
        != position.sellable_core_quantity
        or sum(lot.remaining_qty for lot in tactical if lot.acquired_trade_date < trade_date)
        != position.sellable_tactical_quantity
    ):
        raise ValueError("position lots do not match the authoritative decision summary")
    return lots


def _position_lots_from_row(
    row: EvaluationResultRow,
) -> tuple[PositionLotRecord, ...]:
    try:
        payload = json.loads(row.position_lots_json)
        if not isinstance(payload, list):
            raise ValueError("position lots must be a JSON array")
        result = _result_from_row(row)
        lots = _validate_position_lots(
            result,
            tuple(PositionLotRecord.model_validate(item) for item in payload),
        )
        canonical = json.dumps(
            [lot.model_dump(mode="json", round_trip=True) for lot in lots],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        valid = canonical == row.position_lots_json
    except TypeError, ValueError, RecursionError:
        valid = False
        lots = ()
    if not valid:
        raise ProjectionError("Stored evaluation position lots are invalid")
    return lots


def _validate_decision_event(row: MonitorEventRow, result: EvaluationResult) -> None:
    try:
        payload = _json_object(row.payload_json, "monitor event")
        valid = (
            row.event_type == "symbol.snapshot.updated"
            and row.aggregate_id == result.snapshot.symbol
            and payload.get("entityId") == result.snapshot.symbol
            and payload.get("symbol") == result.snapshot.symbol
            and payload.get("resultHash") == result.result_hash
            and row.schema_version == 1
            and _market_datetime(row.occurred_at, "occurred_at") == result.snapshot.evaluated_at
        )
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProjectionIdentityConflictError(
            "Decision head event does not match its complete result"
        )


def _health_from_row(row: SymbolHealthProjectionRow) -> SymbolHealthProjectionRecord:
    try:
        projection = _json_object(row.projection_json, "symbol health projection")
        record = SymbolHealthProjectionRecord(
            symbol=_symbol(row.symbol),
            revision=row.revision,
            activation_revision=row.activation_revision,
            runtime_generation=_uuid(row.runtime_generation, "runtime_generation"),
            projection=projection,
            observed_at=_market_datetime(row.observed_at, "observed_at"),
            schema_version=row.schema_version,
        )
        valid = _projection_json(
            record.projection,
            maximum_bytes=_MAX_HEALTH_JSON_BYTES,
            label="symbol health projection",
        ) == row.projection_json and (
            projection.get("symbol") == record.symbol
            and _market_datetime(projection.get("observedAt"), "projection observedAt")
            == record.observed_at
        )
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProjectionError("Stored symbol health projection is invalid")
    return record


def _pending_from_row(row: PendingOfficialCloseRow) -> PendingOfficialCloseRecord:
    try:
        record = PendingOfficialCloseRecord(
            plan_hash=_sha256(row.plan_hash, "plan_hash"),
            symbol=_symbol(row.symbol),
            trade_date=_trade_date(row.trade_date),
            formula_version=_token(row.formula_version, "formula_version", maximum=32),
            pending=_json_object(row.pending_json, "pending official close"),
            created_at=_market_datetime(row.created_at, "created_at"),
            updated_at=_market_datetime(row.updated_at, "updated_at"),
        )
        valid = (
            record.updated_at >= record.created_at
            and _projection_json(
                record.pending,
                maximum_bytes=_MAX_PENDING_JSON_BYTES,
                label="pending official close",
            )
            == row.pending_json
        )
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProjectionError("Stored pending official close is invalid")
    return record


def _market_index_values(
    snapshot: MarketIndexSnapshot,
    provider_revision: int,
    snapshot_json: str,
) -> dict[str, object]:
    return {
        "snapshot_hash": snapshot.snapshot_hash,
        "mapping_version": snapshot.mapping_version,
        "index_code": snapshot.index_code.value,
        "decision_cutoff": snapshot.decision_cutoff.isoformat(),
        "request_set_hash": snapshot.request_set_hash,
        "provider_content_revision": provider_revision,
        "revision": snapshot.revision,
        "bar_set_hash": snapshot.bar_set_hash,
        "formula_definition_hash": snapshot.formula_definition_hash,
        "snapshot_json": snapshot_json,
        "observed_at": snapshot.observed_at.isoformat(),
        "schema_version": 1,
    }


def _market_index_from_row(row: MarketIndexSnapshotRow) -> tuple[MarketIndexSnapshot, int]:
    try:
        snapshot = MarketIndexSnapshot.model_validate_json(row.snapshot_json)
        validate_market_index_snapshot_integrity(snapshot)
        values = _market_index_values(
            snapshot,
            row.provider_content_revision,
            row.snapshot_json,
        )
        valid = (
            all(getattr(row, name) == value for name, value in values.items())
            and canonical_market_index_json(snapshot) == row.snapshot_json
            and snapshot.cache_key.provider_content_revision == row.provider_content_revision
        )
    except TypeError, ValueError:
        valid = False
    if not valid:
        raise ProjectionError("Stored market-index snapshot is invalid")
    return snapshot, row.provider_content_revision


def _projection_json(
    value: Mapping[str, object] | BaseModel,
    *,
    maximum_bytes: int,
    label: str,
) -> str:
    if isinstance(value, BaseModel):
        payload: object = value.model_dump(mode="json", round_trip=True, by_alias=True)
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise TypeError(f"{label} must be a mapping or BaseModel")
    try:
        encoded = json.dumps(
            payload,
            default=_json_default,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(f"{label} must contain canonical JSON-compatible values") from error
    _bounded_json(encoded, maximum_bytes, label)
    _json_object(encoded, label)
    return encoded


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("decimal JSON values must be finite")
        return str(value)
    if type(value) in {date, datetime}:
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(parsed, dict) or any(type(key) is not str for key in parsed):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _bounded_json(value: str, maximum_bytes: int, label: str) -> None:
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{label} exceeds its persistence size limit")


def _positive_integer(value: int, name: str) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError(f"{name} must be a positive 32-bit integer")
    return value


def _uuid(value: object, name: str) -> UUID:
    if type(value) is UUID:
        parsed = value
    elif type(value) is not str:
        raise TypeError(f"{name} must be a UUID")
    else:
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError(f"{name} must be a UUID") from None
        if str(parsed) != value:
            raise ValueError(f"{name} must be a canonical UUID")
    if parsed.version != 4:
        raise ValueError(f"{name} must be a UUIDv4")
    return parsed


def _market_datetime(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        parsed = None
    if type(parsed) is not datetime or parsed.utcoffset() != timedelta(hours=8):
        raise ValueError(f"{name} must use the Asia/Shanghai offset")
    return parsed


def _trade_date(value: date) -> date:
    if type(value) is not date:
        raise TypeError("trade_date must be a date")
    return value


def _sha256(value: str, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _symbol(value: str) -> str:
    if type(value) is not str or _SYMBOL_PATTERN.fullmatch(value) is None:
        raise ValueError("symbol must be a canonical A-share symbol")
    return value


def _token(value: str, name: str, *, maximum: int) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1 to {maximum} non-padding characters")
    return value


__all__ = [
    "DecisionHeadRecord",
    "MarketIndexHeadRecord",
    "MarketIndexSnapshotRecord",
    "PendingOfficialCloseRecord",
    "ProjectionError",
    "ProjectionIdentityConflictError",
    "ProjectionMissingDependencyError",
    "ProjectionRepository",
    "ProjectionRevisionConflictError",
    "SymbolHealthProjectionRecord",
]
