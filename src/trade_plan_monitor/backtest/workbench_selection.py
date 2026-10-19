"""Immutable research context for one genuinely reviewed workbench plan."""

from datetime import date, datetime, time
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import LoopAccountInput
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    LoopPlanVersion,
    LoopSchedule,
    LoopScheduleEntry,
    LoopTimestamp,
)
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.backtest.research_input import ResearchValue, _confirmed
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.daily_plan_models import Text
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.web.schemas import ApiValue


class WorkbenchPlanReference(ApiValue):
    origin: Literal["WORKBENCH"]
    plan_version_id: UUID = Field(strict=False)
    plan_hash: Sha256Hex
    content_hash: Sha256Hex
    source_hash: Sha256Hex
    review_evidence_hash: Sha256Hex
    review_id: UUID = Field(strict=False)
    review_revision: int = Field(ge=1, le=9_007_199_254_740_991)


class WorkbenchReplayContext(ApiValue):
    effective_trade_date: date = Field(strict=False)
    available_at: datetime | None = Field(default=None, strict=False)
    information_cutoff: datetime = Field(strict=False)
    initial_account: LoopAccountInput
    confirmed: Literal[True]
    evidence: Text

    _confirmation = field_validator("confirmed", mode="before")(_confirmed)

    @field_validator("initial_account", mode="before")
    @classmethod
    def parse_account(cls, value):
        if isinstance(value, dict):
            return LoopAccountInput.model_validate_json(canonical_json(value))
        return value

    @field_validator("available_at", "information_cutoff")
    @classmethod
    def shanghai(cls, value):
        from trade_plan_monitor.backtest.plan_schedule import require_loop_timestamp

        return None if value is None else require_loop_timestamp(value)


class WorkbenchSelectionCommand(ApiValue):
    schema_version: Literal["workbench-loop-selection-v1"]
    plan: WorkbenchPlanReference
    context: WorkbenchReplayContext


class WorkbenchReviewedPlan(ResearchValue):
    reference: WorkbenchPlanReference
    version: LoopPlanVersion
    draft_json: str = Field(max_length=1_048_576)
    source_text: str = Field(max_length=1_048_576)
    mapping_json: str = Field(max_length=1_048_576)

    @model_validator(mode="after")
    def approved(self) -> Self:
        draft = load_daily_draft_json(self.draft_json)
        review = build_daily_review(
            draft, DailyMapping.model_validate_json(self.mapping_json), self.source_text
        )
        ref, version = self.reference, self.version
        if (
            review.issues
            or draft.to_executable() != version.snapshot
            or ref.plan_hash != daily_draft_sha256(draft)
            or ref.content_hash != review.content_hash
            or ref.source_hash != review.source_hash
            or ref.review_evidence_hash != review.evidence_hash
            or version.version_id != str(ref.plan_version_id)
            or version.source_hashes != (ref.source_hash,)
            or version.evidence_hash != ref.review_evidence_hash
        ):
            raise ValueError("workbench approval differs from its immutable source")
        return self


class WorkbenchPlanSelection(ResearchValue):
    schema_version: Literal["workbench-loop-selection-v1"] = "workbench-loop-selection-v1"
    selection_id: StableIdentifier
    reviewed: WorkbenchReviewedPlan
    context: WorkbenchReplayContext
    confirmed_at: LoopTimestamp
    version: LoopPlanVersion

    @property
    def account(self):
        return self.context.initial_account

    @property
    def source(self):
        return PreparationSource(
            source_id=str(self.reviewed.reference.plan_version_id),
            text=self.reviewed.source_text,
            effective_trade_date=self.context.effective_trade_date,
            available_at=self.context.available_at,
        )

    @property
    def schedule(self):
        return LoopSchedule(
            entries=(
                LoopScheduleEntry(
                    effective_trade_date=self.context.effective_trade_date,
                    version=self.version,
                ),
            )
        )

    @property
    def manifest_hash(self):
        return sha256((self.schema_version + "\0" + canonical_json(self)).encode()).hexdigest()

    @model_validator(mode="after")
    def bound(self) -> Self:
        original, version = self.reviewed.version, self.version
        available = self.source.execution_available_at
        if version != original.model_copy(
            update={
                "available_at": available,
                "information_cutoff": self.context.information_cutoff,
            }
        ):
            raise ValueError("selection changed reviewed rules or chronology")
        start = max(
            available, datetime.combine(self.context.effective_trade_date, time.min, SHANGHAI)
        )
        if (
            self.schedule.select(start) is None
            or self.account.snapshot_at > start
            or self.account.opening_mark is not None
            and self.account.opening_mark.available_at > start
            or sum(lot.quantity for lot in self.account.lots) > version.snapshot.position.max_qty
            or self.confirmed_at < original.review.reviewed_at
        ):
            raise ValueError("invalid historical opening context")
        return self


def freeze_workbench_selection(reviewed, context, *, selection_id, confirmed_at):
    available = context.available_at or datetime.combine(
        context.effective_trade_date, time(9, 30), SHANGHAI
    )
    return WorkbenchPlanSelection(
        selection_id=selection_id,
        reviewed=reviewed,
        context=context,
        confirmed_at=confirmed_at,
        version=LoopPlanVersion.model_validate_json(
            reviewed.version.model_copy(
                update={
                    "available_at": available,
                    "information_cutoff": context.information_cutoff,
                }
            ).model_dump_json()
        ),
    )


class WorkbenchSelectionStore:
    """One immutable selection table, with the preparation owner's transaction/receipts."""

    def __init__(self, preparation_store):
        self._store = preparation_store

    @staticmethod
    def _request_hash(command):
        return sha256(
            ("workbench-loop-selection-v1\0" + canonical_json(command)).encode()
        ).hexdigest()

    def _replay(self, connection, command, key):
        from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

        row = connection.execute(
            "SELECT request_hash,response_json FROM backtest_preparation_idempotency "
            "WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != self._request_hash(command):
            raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
        return WorkbenchPlanSelection.model_validate_json(row[1])

    def replay(self, command, key):
        with self._store._connect() as connection:
            return self._replay(connection, command, key)

    def get(self, selection_id):
        with self._store._connect() as connection:
            row = connection.execute(
                "SELECT document_json FROM backtest_plan_selection WHERE selection_id = ?",
                (selection_id,),
            ).fetchone()
        if row is None:
            return None
        value = WorkbenchPlanSelection.model_validate_json(row[0])
        if value.selection_id != selection_id:
            raise ValueError("selection identity differs from its stored key")
        return value

    def save(self, command, reviewed, key):
        from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

        with self._store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._replay(connection, command, key)
            if previous is not None:
                return previous
            if reviewed.reference != command.plan:
                raise PreparationConflictError("WORKBENCH_REVIEW_CHANGED")
            selection = freeze_workbench_selection(
                reviewed,
                command.context,
                selection_id=str(uuid4()),
                confirmed_at=self._store._clock(),
            )
            encoded = selection.model_dump_json()
            connection.execute(
                "INSERT INTO backtest_plan_selection VALUES (?,?)",
                (selection.selection_id, encoded),
            )
            connection.execute(
                "INSERT INTO backtest_preparation_idempotency VALUES (?,?,?)",
                (key, self._request_hash(command), encoded),
            )
            connection.commit()
            return selection


class WorkbenchSelectionView(ApiValue):
    schema_version: Literal["workbench-loop-selection-v1"] = "workbench-loop-selection-v1"
    selection_id: StableIdentifier
    selection_hash: Sha256Hex
    frozen: WorkbenchPlanSelection

    @classmethod
    def project(cls, value):
        return cls(
            selection_id=value.selection_id, selection_hash=value.manifest_hash, frozen=value
        )
