"""Immutable, versioned input values for deterministic backtest identity."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import (
    INDEX_DATASET_SCHEMA_VERSION,
    DatasetManifest,
)
from trade_plan_monitor.backtest.index_data import build_backtest_index_requirement
from trade_plan_monitor.backtest.models import ExecutionConfig, PositionLot
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import PositionBucket, TradePlan
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_index.canonical import FORMULA_DEFINITION_HASH
from trade_plan_monitor.market_index.identity import ReferenceMarketBinding

RUN_FORMULA_V1 = "backtest-run-v1"
RUN_FORMULA_V2 = "backtest-run-v2"
RUN_FORMULA_V3 = "backtest-run-v3"
RUN_INPUT_SCHEMA_VERSION = "backtest-run-input-v1"
FIVE_MINUTE_CONTEXT_BARS = 512
DAILY_CONTEXT_BARS = 499
CALENDAR_CONTEXT_DAYS = 512
MAX_INITIAL_LOTS = 200
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_RunFormulaVersion = Literal["backtest-run-v1", "backtest-run-v2", "backtest-run-v3"]
_Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
_LotKey = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
_PositiveSafeInteger = Annotated[int, Field(strict=True, gt=0, le=MAX_SAFE_INTEGER)]
_PositiveSafeBoardLot = Annotated[
    int,
    Field(strict=True, gt=0, le=MAX_SAFE_INTEGER, multiple_of=100),
]


class _RunInputValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _BacktestContextBounds(_RunInputValue):
    calendar_days: Literal[512] = CALENDAR_CONTEXT_DAYS
    daily_bars_before_current: Literal[499] = DAILY_CONTEXT_BARS
    five_minute_bars: Literal[512] = FIVE_MINUTE_CONTEXT_BARS


class BacktestInitialLotInput(_RunInputValue):
    """Caller-stable initial holding input without a run-bound lot identity."""

    lot_key: _LotKey
    bucket: PositionBucket
    acquired_trade_date: Annotated[date, Field(strict=True)]
    quantity: _PositiveSafeBoardLot
    cost_basis_fen: _PositiveSafeInteger


class BacktestRunInput(_RunInputValue):
    """Canonical replay input whose formula selects an exact v1 or v2 run identity."""

    schema_version: Literal["backtest-run-input-v1"] = RUN_INPUT_SCHEMA_VERSION
    run_formula_version: _RunFormulaVersion
    plan_snapshot: TradePlan
    plan_sha256: _Sha256Hex
    plan_version_id: UUID | None = None
    dataset_hash: _Sha256Hex
    start: Annotated[date, Field(strict=True)]
    end: Annotated[date, Field(strict=True)]
    initial_cash_fen: _PositiveSafeInteger
    initial_lots: Annotated[
        tuple[BacktestInitialLotInput, ...],
        Field(max_length=MAX_INITIAL_LOTS),
    ] = ()
    indicator_formula_version: str
    context_bounds: _BacktestContextBounds = Field(default_factory=_BacktestContextBounds)
    execution_config: ExecutionConfig
    manual_event_risk: bool
    reference_market_binding: ReferenceMarketBinding | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    market_index_data_hash: _Sha256Hex | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    index_requirement_hash: _Sha256Hex | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    formula_definition_hash: _Sha256Hex | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @classmethod
    def create(
        cls,
        *,
        plan: TradePlan,
        manifest: DatasetManifest,
        initial_cash_fen: int,
        initial_lots: tuple[BacktestInitialLotInput, ...],
        execution_config: ExecutionConfig,
        manual_event_risk: bool,
        plan_version_id: UUID | None = None,
    ) -> Self:
        if not isinstance(plan, TradePlan):
            raise TypeError("plan must be a TradePlan")
        if not isinstance(manifest, DatasetManifest):
            raise TypeError("manifest must be a DatasetManifest")
        if type(initial_lots) is not tuple or any(
            not isinstance(item, BacktestInitialLotInput) for item in initial_lots
        ):
            raise TypeError("initial_lots must be a tuple of BacktestInitialLotInput values")
        if not isinstance(execution_config, ExecutionConfig):
            raise TypeError("execution_config must be an ExecutionConfig")
        if type(manual_event_risk) is not bool:
            raise TypeError("manual_event_risk must be an explicit bool")
        if plan_version_id is not None and not isinstance(plan_version_id, UUID):
            raise TypeError("plan_version_id must be a UUID or None")
        requirement = build_backtest_index_requirement(plan)
        formula_version = (
            RUN_FORMULA_V3
            if requirement.required
            else RUN_FORMULA_V2
            if initial_lots
            else RUN_FORMULA_V1
        )
        index_identity: dict[str, object] = {}
        if requirement.required:
            if manifest.schema_version != INDEX_DATASET_SCHEMA_VERSION:
                raise ValueError("index-bearing plan requires backtest-dataset-v2")
            binding = next(
                (item for item in manifest.reference_market_bindings if item.symbol == plan.symbol),
                None,
            )
            if binding is None or plan.reference_market is None:
                raise ValueError("dataset is missing the plan's reference-market binding")
            stored_binding = ReferenceMarketBinding(
                selection=binding.selection,
                mapping_version=binding.mapping_version,
                index_code=binding.index_code,
            )
            if stored_binding != plan.reference_market:
                raise ValueError("dataset reference-market binding does not match plan")
            if manifest.market_index_data_hash is None or manifest.formula_definition_hash is None:
                raise ValueError("index-bearing dataset is missing immutable hash identity")
            index_identity = {
                "reference_market_binding": stored_binding,
                "market_index_data_hash": manifest.market_index_data_hash,
                "index_requirement_hash": requirement.index_requirement_hash,
                "formula_definition_hash": manifest.formula_definition_hash,
            }
        return cls(
            run_formula_version=formula_version,
            plan_snapshot=plan,
            plan_sha256=plan_sha256(plan),
            plan_version_id=plan_version_id,
            dataset_hash=manifest.dataset_hash,
            start=manifest.scope.start,
            end=manifest.scope.end,
            initial_cash_fen=initial_cash_fen,
            initial_lots=initial_lots,
            indicator_formula_version=plan.monitoring.indicator_formula_version,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
            **index_identity,
        )

    @field_validator("initial_lots")
    @classmethod
    def normalize_initial_lots(
        cls,
        value: tuple[BacktestInitialLotInput, ...],
    ) -> tuple[BacktestInitialLotInput, ...]:
        return tuple(
            sorted(
                value,
                key=lambda item: (item.bucket, item.acquired_trade_date, item.lot_key),
            )
        )

    @model_validator(mode="after")
    def validate_canonical_input(self) -> Self:
        validation = validate_trade_plan(
            self.plan_snapshot,
            available_market_evidence=ALL_MARKET_EVIDENCE,
        )
        if not validation.can_activate:
            raise ValueError("plan_snapshot must be deterministically activatable")
        if self.plan_sha256 != plan_sha256(self.plan_snapshot):
            raise ValueError("plan_sha256 must match the canonical plan snapshot")
        if (
            self.indicator_formula_version
            != self.plan_snapshot.monitoring.indicator_formula_version
        ):
            raise ValueError("indicator formula version must match the plan snapshot")
        requirement = build_backtest_index_requirement(self.plan_snapshot)
        expected_formula = (
            RUN_FORMULA_V3
            if requirement.required
            else RUN_FORMULA_V2
            if self.initial_lots
            else RUN_FORMULA_V1
        )
        if self.run_formula_version != expected_formula:
            raise ValueError("run formula version must match the normalized initial-lot shape")
        index_fields = (
            self.reference_market_binding,
            self.market_index_data_hash,
            self.index_requirement_hash,
            self.formula_definition_hash,
        )
        if requirement.required:
            if any(value is None for value in index_fields):
                raise ValueError("backtest-run-v3 requires complete index hash identity")
            if self.reference_market_binding != self.plan_snapshot.reference_market:
                raise ValueError("run reference-market binding must match plan")
            if self.index_requirement_hash != requirement.index_requirement_hash:
                raise ValueError("run index_requirement_hash must match plan paths")
            if self.formula_definition_hash != FORMULA_DEFINITION_HASH:
                raise ValueError("run formula_definition_hash must match approved formulas")
        elif any(value is not None for value in index_fields):
            raise ValueError("stock-only run formulas forbid index hash identity")
        if self.start > self.end:
            raise ValueError("dataset start cannot be after end")

        lot_keys = tuple(item.lot_key for item in self.initial_lots)
        if len(set(lot_keys)) != len(lot_keys):
            raise ValueError("initial-lot keys must be unique within one run input")
        if any(item.acquired_trade_date > self.start for item in self.initial_lots):
            raise ValueError("initial-lot acquired trade date cannot be after dataset start")

        bucket_quantities = {
            "CORE": sum(item.quantity for item in self.initial_lots if item.bucket == "CORE"),
            "TACTICAL": sum(
                item.quantity for item in self.initial_lots if item.bucket == "TACTICAL"
            ),
        }
        position = self.plan_snapshot.position
        if bucket_quantities["CORE"] > position.core_target_qty:
            raise ValueError("initial CORE quantity exceeds the reviewed plan cap")
        if bucket_quantities["TACTICAL"] > position.tactical_target_qty:
            raise ValueError("initial TACTICAL quantity exceeds the reviewed plan cap")
        if sum(bucket_quantities.values()) > position.max_qty:
            raise ValueError("initial total quantity exceeds the reviewed plan maximum")
        if self.initial_cash_fen + sum(item.cost_basis_fen for item in self.initial_lots) > (
            MAX_SAFE_INTEGER
        ):
            raise ValueError("initial cash and lot costs must fit one JavaScript safe integer")
        return self

    @property
    def run_id(self) -> str:
        preimage = {
            "formula_version": self.run_formula_version,
            "plan_hash": self.plan_sha256,
            "plan_version": self.plan_snapshot.version,
            "dataset_hash": self.dataset_hash,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "initial_cash_fen": self.initial_cash_fen,
            "initial_lots": [
                item.model_dump(mode="python", round_trip=True) for item in self.initial_lots
            ],
            "indicator_formula_version": self.indicator_formula_version,
            "context_bounds": self.context_bounds.model_dump(mode="python", round_trip=True),
            "execution_config_hash": self.execution_config.config_hash,
            "execution_config": self.execution_config.model_dump(mode="python", round_trip=True),
            "manual_event_risk": self.manual_event_risk,
        }
        if self.run_formula_version == RUN_FORMULA_V3:
            preimage.update(
                {
                    "reference_market_binding": self.reference_market_binding,
                    "market_index_data_hash": self.market_index_data_hash,
                    "index_requirement_hash": self.index_requirement_hash,
                    "formula_definition_hash": self.formula_definition_hash,
                }
            )
        return sha256(
            (self.run_formula_version + "\0" + canonical_json(preimage)).encode("utf-8")
        ).hexdigest()

    def derive_position_lots(self) -> tuple[PositionLot, ...]:
        """Derive internal lot identities only after the versioned run hash exists."""

        run_id = self.run_id
        return tuple(
            PositionLot.from_initial_input(
                run_id=run_id,
                symbol=self.plan_snapshot.symbol,
                lot_key=item.lot_key,
                bucket=item.bucket,
                acquired_trade_date=item.acquired_trade_date,
                quantity=item.quantity,
                cost_basis_fen=item.cost_basis_fen,
            )
            for item in self.initial_lots
        )


__all__ = [
    "CALENDAR_CONTEXT_DAYS",
    "DAILY_CONTEXT_BARS",
    "FIVE_MINUTE_CONTEXT_BARS",
    "MAX_INITIAL_LOTS",
    "MAX_SAFE_INTEGER",
    "RUN_FORMULA_V1",
    "RUN_FORMULA_V2",
    "RUN_FORMULA_V3",
    "RUN_INPUT_SCHEMA_VERSION",
    "BacktestInitialLotInput",
    "BacktestRunInput",
]
