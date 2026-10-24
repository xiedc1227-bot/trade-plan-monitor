"""Closed loop input, explicit opening account and bounded research policies."""

from datetime import date
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from trade_plan_monitor.ai.prompts import MAX_SOURCE_TEXT_CHARS
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.exception_replay_input import ExceptionReplayProgram
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    MAX_SCHEDULED_ENTRIES,
    LoopEndBoundary,
    LoopSchedule,
    LoopTimestamp,
    ScheduledLoopSchedule,
)
from trade_plan_monitor.backtest.research_input import ExactDecimal, ResearchValue
from trade_plan_monitor.backtest.run_input import MAX_INITIAL_LOTS, MAX_SAFE_INTEGER
from trade_plan_monitor.domain.daily_plan_models import Text

LOOP_INPUT_SCHEMA_VERSION = "monitor-loop-input-v1"
LOOP_RUN_FORMULA_VERSION = "backtest-run-v5"
MAX_SOURCE_PLANS = 1
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_EXTRACTION_ATTEMPTS = 3
MAX_BATCH_EXTRACTIONS = 1
MAX_LOOP_RECORDS = 70_000
SafeFen = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
SafePositiveFen = Annotated[int, Field(gt=0, le=MAX_SAFE_INTEGER)]
SafeShares = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER, multiple_of=100)]
SafePositiveShares = Annotated[int, Field(gt=0, le=MAX_SAFE_INTEGER, multiple_of=100)]
LoopRate = Annotated[ExactDecimal, Field(ge=0, le=1, allow_inf_nan=False)]


class LoopSource(ResearchValue):
    source_id: StableIdentifier
    text: str = Field(min_length=1, max_length=MAX_SOURCE_TEXT_CHARS)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source text must not be blank")
        return value

    @property
    def source_hash(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


class LoopSourceBatch(ResearchValue):
    """One supplied plan source; a second item is outside this mode's scope."""

    sources: tuple[LoopSource, ...] = Field(min_length=1, max_length=MAX_SOURCE_PLANS)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError("source IDs must be unique")
        if sum(len(source.text.encode("utf-8")) for source in self.sources) > MAX_SOURCE_BYTES:
            raise ValueError("source batch exceeds 8 MiB of UTF-8 text")
        return self


class LoopSourceCollection(ResearchValue):
    """New preparation branch; reuse per-source and aggregate UTF-8 safeguards."""

    sources: tuple[LoopSource, ...] = Field(min_length=1, max_length=MAX_SCHEDULED_ENTRIES)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        return LoopSourceBatch.bounded(self)


class KnownLoopCash(ResearchValue):
    kind: Literal["KNOWN"] = "KNOWN"
    balance_fen: SafeFen


class UnknownLoopCash(ResearchValue):
    kind: Literal["UNKNOWN"] = "UNKNOWN"


class PositionLimitFunding(ResearchValue):
    """No capital budget: shared plan authority still limits every simulated position."""

    kind: Literal["POSITION_LIMIT_ONLY"] = "POSITION_LIMIT_ONLY"


class LoopInitialLot(ResearchValue):
    lot_key: StableIdentifier
    bucket: Literal["CORE", "TACTICAL"]
    quantity: SafePositiveShares
    cost_basis_fen: SafeFen | None
    acquired_trade_date: date | None
    sellable_quantity: SafeShares | None
    evidence: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.sellable_quantity is not None and self.sellable_quantity > self.quantity:
            raise ValueError("sellable quantity exceeds opening lot quantity")
        return self


class LoopOpeningMark(ResearchValue):
    price_fen: SafePositiveFen
    price_at: LoopTimestamp
    available_at: LoopTimestamp
    evidence: Text

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.price_at > self.available_at:
            raise ValueError("opening mark price follows its availability")
        return self


class LoopAccountInput(ResearchValue):
    snapshot_at: LoopTimestamp
    inventory_known: bool
    cash: Annotated[
        KnownLoopCash | UnknownLoopCash | PositionLimitFunding, Field(discriminator="kind")
    ]
    lots: tuple[LoopInitialLot, ...] = Field(max_length=MAX_INITIAL_LOTS)
    opening_mark: LoopOpeningMark | None
    evidence: Text

    @field_validator("lots")
    @classmethod
    def canonical_lots(cls, value: tuple[LoopInitialLot, ...]) -> tuple[LoopInitialLot, ...]:
        return tuple(sorted(value, key=lambda lot: (lot.bucket, lot.lot_key)))

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.inventory_known and self.lots:
            raise ValueError("unknown inventory forbids inferred opening lots")
        if len({lot.lot_key for lot in self.lots}) != len(self.lots):
            raise ValueError("opening lot keys must be unique")
        for lot in self.lots:
            if lot.acquired_trade_date is not None:
                if lot.acquired_trade_date > self.snapshot_at.date():
                    raise ValueError("opening acquisition date is in the future")
                if lot.acquired_trade_date == self.snapshot_at.date() and lot.sellable_quantity:
                    raise ValueError("same-day opening acquisition is not T+1 sellable")
        cash = self.cash.balance_fen if isinstance(self.cash, KnownLoopCash) else 0
        market_value = (
            sum(lot.quantity for lot in self.lots) * self.opening_mark.price_fen
            if self.opening_mark is not None
            else 0
        )
        if (
            max(
                sum(lot.quantity for lot in self.lots),
                cash + sum(lot.cost_basis_fen or 0 for lot in self.lots),
                cash + market_value,
            )
            > MAX_SAFE_INTEGER
        ):
            raise ValueError("opening account exceeds the safe integer range")
        return self

    @property
    def accounting_cost_fen(self) -> int | None:
        if not self.inventory_known or any(lot.cost_basis_fen is None for lot in self.lots):
            return None
        return sum(lot.cost_basis_fen for lot in self.lots)

    @property
    def opening_equity_fen(self) -> int | None:
        if not self.inventory_known or not isinstance(self.cash, KnownLoopCash):
            return None
        quantity = sum(lot.quantity for lot in self.lots)
        if quantity and self.opening_mark is None:
            return None
        return self.cash.balance_fen + (quantity * self.opening_mark.price_fen if quantity else 0)


class LoopCosts(ResearchValue):
    formula_version: Literal["monitor-loop-costs-v1"] = "monitor-loop-costs-v1"
    commission_rate: LoopRate
    minimum_commission_fen: SafeFen
    stamp_duty_rate: LoopRate
    transfer_fee_rate: LoopRate
    buy_slippage_fen: SafeFen
    sell_slippage_fen: SafeFen


class LoopResponsePolicy(ResearchValue):
    mode: Literal["FOLLOW_REMINDERS", "OBSERVE_ONLY", "RECORDED_ACTIONS"]
    response_delay_seconds: SafeFen = 0
    fill_model: Literal["NEXT_ELIGIBLE_MINUTE_CLOSE"] = "NEXT_ELIGIBLE_MINUTE_CLOSE"


class LoopLimits(ResearchValue):
    max_evaluations: Literal[70000] = MAX_LOOP_RECORDS
    max_reminders: Literal[70000] = MAX_LOOP_RECORDS
    max_intents: Literal[70000] = MAX_LOOP_RECORDS
    max_execution_attempts: Literal[70000] = MAX_LOOP_RECORDS


class MonitorLoopInput(ResearchValue):
    schema_version: Literal["monitor-loop-input-v1"] = LOOP_INPUT_SCHEMA_VERSION
    run_formula_version: Literal["backtest-run-v5", "backtest-run-v8"] = LOOP_RUN_FORMULA_VERSION
    exception_program: ExceptionReplayProgram | None = Field(
        default=None, exclude_if=lambda value: value is None)
    schedule: LoopSchedule
    initial_account: LoopAccountInput
    boundary: LoopEndBoundary
    dataset_hash: Sha256Hex
    response: LoopResponsePolicy
    costs: LoopCosts
    limits: LoopLimits = Field(default_factory=LoopLimits)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        exception = any(row.version.snapshot.schema_version == 7 for row in self.schedule.entries)
        if exception != (self.run_formula_version == "backtest-run-v8") or exception != (
            self.exception_program is not None
        ):
            raise ValueError("EXCEPTION_LOOP_REQUIRES_EXPLICIT_PROGRAM_V8")
        if self.exception_program is not None:
            self.exception_program.validate_scope(
                plans=tuple(row.version.snapshot for row in self.schedule.entries),
                started_at=self.boundary.started_at)
        if self.initial_account.snapshot_at > self.boundary.started_at:
            raise ValueError("opening account snapshot cannot follow the historical start")
        mark = self.initial_account.opening_mark
        if mark is not None and mark.available_at > self.boundary.started_at:
            raise ValueError("opening mark was unavailable at the historical start")
        selected = self.schedule.select(self.boundary.started_at)
        if selected is None:
            raise ValueError("uncovered run start")
        if any(
            row.version.review.reviewed_at > self.boundary.submitted_at
            for row in self.schedule.entries
        ):
            raise ValueError("all plan reviews must exist before submission")
        if (
            sum(lot.quantity for lot in self.initial_account.lots)
            > selected.version.snapshot.position.max_qty
        ):
            raise ValueError("opening inventory exceeds the initial plan maximum")
        return self

    @property
    def input_hash(self) -> str:
        return sha256(("monitor-loop-input-v1\0" + canonical_json(self)).encode()).hexdigest()

    @property
    def run_id(self) -> str:
        return sha256((self.run_formula_version + "\0" + canonical_json(self)).encode()).hexdigest()


class ScheduledLoopInput(ResearchValue):
    """One account/run over reviewed daily versions, separately encoded from v1."""

    schema_version: Literal["monitor-loop-input-v2"] = "monitor-loop-input-v2"
    run_formula_version: Literal["backtest-run-v6", "backtest-run-v8"] = "backtest-run-v6"
    exception_program: ExceptionReplayProgram | None = Field(
        default=None, exclude_if=lambda value: value is None)
    schedule: ScheduledLoopSchedule
    initial_account: LoopAccountInput
    boundary: LoopEndBoundary
    dataset_hash: Sha256Hex
    response: LoopResponsePolicy
    costs: LoopCosts
    limits: LoopLimits = Field(default_factory=LoopLimits)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        return MonitorLoopInput.coherent(self)

    @model_validator(mode="after")
    def first_account(self) -> Self:
        selected = self.schedule.select(self.boundary.started_at)
        first = self.schedule.entries[0]
        if (
            selected.version != first.version
            or self.boundary.started_at.date() != first.effective_trade_date
        ):
            raise ValueError("opening account must bind the first scheduled version")
        return self

    @property
    def input_hash(self) -> str:
        return sha256((self.schema_version + "\0" + canonical_json(self)).encode()).hexdigest()

    @property
    def run_id(self) -> str:
        return sha256((self.run_formula_version + "\0" + canonical_json(self)).encode()).hexdigest()


class WorkbenchLoopInput(MonitorLoopInput):
    """Same executor/formula, with every independently confirmed research fact bound."""

    schema_version: Literal["workbench-loop-input-v1"] = "workbench-loop-input-v1"
    selection_hash: Sha256Hex

    @property
    def input_hash(self) -> str:
        return sha256((self.schema_version + "\0" + canonical_json(self)).encode()).hexdigest()


_LOOP_INPUT_CODEC = TypeAdapter(
    Annotated[
        MonitorLoopInput | ScheduledLoopInput | WorkbenchLoopInput,
        Field(discriminator="schema_version"),
    ]
)


def decode_monitor_loop_input_json(
    value: str | bytes,
) -> MonitorLoopInput | ScheduledLoopInput | WorkbenchLoopInput:
    return _LOOP_INPUT_CODEC.validate_json(value)
