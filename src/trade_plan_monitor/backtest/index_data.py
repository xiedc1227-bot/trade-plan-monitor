"""Plan-specific index requirements and cutoff-safe offline replay snapshots."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from trade_plan_monitor.decision.models import (
    ConditionEvidence,
    ConditionOutcome,
    EvaluationResult,
    IndexConditionEvidence,
    IndexConditionType,
)
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
    canonical_json,
    market_index_bar_set_hash,
    market_index_request_set_hash,
)
from trade_plan_monitor.market_index.identity import (
    Board,
    MarketIndexCode,
    ReferenceMarketBinding,
    resolve_board_reference,
)
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactRequest,
    MarketIndexInterval,
    MarketIndexSnapshot,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.requirements import (
    fact_request_for_index_condition,
    iter_plan_index_conditions,
    required_bar_counts,
    union_fact_requests,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_INDEX_DATA_DOMAIN = b"backtest-index-data-v1\0"
_INDEX_REQUIREMENTS_DOMAIN = b"backtest-index-requirements-v1\0"


class _BacktestIndexValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class IndexArtifactMembership(_BacktestIndexValue):
    """Exact immutable membership of one normalized index-bar revision."""

    natural_key: Annotated[str, Field(min_length=1, max_length=160)]
    artifact_hash: Sha256Hex
    index_code: MarketIndexCode
    interval: MarketIndexInterval
    bar_at: AwareDatetime
    provider_revision: Annotated[int, Field(ge=1, le=2_147_483_647)]

    @classmethod
    def from_bar(cls, bar: MarketIndexBar) -> Self:
        if type(bar) is not MarketIndexBar:
            raise TypeError("bar must be an exact MarketIndexBar")
        identity = (
            bar.bar_at.date().isoformat()
            if bar.interval is MarketIndexInterval.OFFICIAL_DAILY
            else bar.bar_at.isoformat(timespec="microseconds")
        )
        kind = "INDEX_DAILY" if bar.interval is MarketIndexInterval.OFFICIAL_DAILY else "INDEX_5M"
        return cls(
            natural_key=f"{kind}:{bar.index_code.value}:{identity}",
            artifact_hash=market_index_bar_set_hash((bar,)),
            index_code=bar.index_code,
            interval=bar.interval,
            bar_at=bar.bar_at,
            provider_revision=bar.provider_revision,
        )

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.bar_at.utcoffset() != timedelta(hours=8):
            raise ValueError("index artifact time must use the Asia/Shanghai offset")
        identity = (
            self.bar_at.date().isoformat()
            if self.interval is MarketIndexInterval.OFFICIAL_DAILY
            else self.bar_at.isoformat(timespec="microseconds")
        )
        kind = "INDEX_DAILY" if self.interval is MarketIndexInterval.OFFICIAL_DAILY else "INDEX_5M"
        expected = f"{kind}:{self.index_code.value}:{identity}"
        if self.natural_key != expected:
            raise ValueError("index artifact natural_key must match its exact identity")
        return self


class BacktestIndexRequirement(_BacktestIndexValue):
    """One plan's exact path-addressed board-index requirement."""

    required: bool
    binding: ReferenceMarketBinding | None
    condition_paths: tuple[str, ...]
    fact_requests: tuple[MarketIndexFactRequest, ...]
    required_five_minute_count: Annotated[int, Field(ge=0, le=251)]
    required_official_day_count: Annotated[int, Field(ge=0, le=310)]
    index_requirement_hash: Sha256Hex
    formula_definition_hash: Sha256Hex = FORMULA_DEFINITION_HASH

    @model_validator(mode="after")
    def validate_requirement(self) -> Self:
        if self.condition_paths != tuple(sorted(set(self.condition_paths))):
            raise ValueError("index condition paths must be ordered and unique")
        if self.required != bool(self.condition_paths):
            raise ValueError("required must match the presence of index condition paths")
        if self.required and self.binding is None:
            raise ValueError("required index coverage needs a reference-market binding")
        if not self.required and (
            self.fact_requests
            or self.required_five_minute_count
            or self.required_official_day_count
        ):
            raise ValueError("an unused index cannot require facts or history")
        return self


class BacktestIndexConditionSummary(_BacktestIndexValue):
    """Canonical per-path outcome counts persisted with an index-bearing report."""

    plan_path: Annotated[str, Field(min_length=1, max_length=256)]
    condition_type: IndexConditionType
    parameters: dict[str, int | Decimal | str]
    formula_id: Literal["SMA", "SMA_LOOKBACK", "RETURN"]
    satisfied_count: Annotated[int, Field(ge=0)]
    unsatisfied_count: Annotated[int, Field(ge=0)]
    missing_count: Annotated[int, Field(ge=0)]
    applicable_branch_count: Annotated[int, Field(ge=0)]

    @field_validator("parameters")
    @classmethod
    def canonicalize_parameters(
        cls,
        value: dict[str, int | Decimal | str],
    ) -> dict[str, int | Decimal | str]:
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (
            self.satisfied_count + self.unsatisfied_count + self.missing_count
            != self.applicable_branch_count
        ):
            raise ValueError("index condition counts must sum to applicable_branch_count")
        return self


class BacktestReferenceMarketBinding(_BacktestIndexValue):
    selection: Literal["AUTO_BOARD"] = "AUTO_BOARD"
    mapping_version: Literal["board-index-map-v1"] = "board-index-map-v1"
    index_code: MarketIndexCode
    display_name: Annotated[str, Field(min_length=1, max_length=32)]
    board: Board


class BacktestReferenceMarketResult(_BacktestIndexValue):
    """Persisted coverage, identities, and path summaries for one completed run."""

    binding: BacktestReferenceMarketBinding
    required: Literal[True] = True
    condition_paths: tuple[str, ...]
    required_five_minute_count: Annotated[int, Field(ge=0, le=251)]
    available_five_minute_count: Annotated[int, Field(ge=0)]
    required_official_day_count: Annotated[int, Field(ge=0, le=310)]
    available_official_day_count: Annotated[int, Field(ge=0)]
    warmup_start: date
    warmup_end: date
    coverage_status: Literal["AVAILABLE", "BLOCKED"]
    blockers: tuple[str, ...]
    market_index_data_hash: Sha256Hex
    index_requirement_hash: Sha256Hex
    formula_definition_hash: Sha256Hex
    dataset_hash: Sha256Hex
    condition_summaries: tuple[BacktestIndexConditionSummary, ...]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.condition_paths != tuple(sorted(set(self.condition_paths))):
            raise ValueError("condition paths must be ordered and unique")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("coverage blockers must be ordered and unique")
        if self.warmup_start > self.warmup_end:
            raise ValueError("index warm-up start cannot follow its end")
        if tuple(item.plan_path for item in self.condition_summaries) != self.condition_paths:
            raise ValueError("condition summaries must match exact requirement paths")
        if (self.coverage_status == "AVAILABLE") != (not self.blockers):
            raise ValueError("coverage status must agree with blockers")
        return self


def build_backtest_index_requirement(plan: TradePlan) -> BacktestIndexRequirement:
    """Derive exact requests, paths, dynamic history counts, and identity for a plan."""

    from trade_plan_monitor.domain.market_linkage_models import (
        MarketLinkedRule,
        MarketLinkedTradePlan,
    )
    from trade_plan_monitor.market_index.canonical import LINKED_INDEX_FORMULA_HASH
    if isinstance(plan, MarketLinkedTradePlan):
        paths = tuple(sorted(f"ordinary_rules.{rule.rule_id}.market_policy"
                      for rule in plan.ordinary_rules if isinstance(rule, MarketLinkedRule)))
        digest = sha256(b"market-linkage-requirements-v1\0" + canonical_json({
            "paths": paths, "binding": plan.reference_market,
            "formula": LINKED_INDEX_FORMULA_HASH, "daily": 60}).encode()).hexdigest()
        return BacktestIndexRequirement(required=True, binding=plan.reference_market,
            condition_paths=paths, fact_requests=(SmaFactRequest(period=60),),
            required_five_minute_count=0, required_official_day_count=60,
            index_requirement_hash=digest, formula_definition_hash=LINKED_INDEX_FORMULA_HASH)
    if not isinstance(plan, TradePlan):
        raise TypeError("plan must be a TradePlan")
    leaves = iter_plan_index_conditions(plan)
    entries = tuple(
        sorted(
            (
                {
                    "planPath": path,
                    "condition": condition,
                    "factRequest": fact_request_for_index_condition(condition),
                }
                for path, condition in leaves
            ),
            key=lambda item: str(item["planPath"]),
        )
    )
    digest = sha256(
        _INDEX_REQUIREMENTS_DOMAIN + canonical_json(entries).encode("utf-8")
    ).hexdigest()
    requests = union_fact_requests(
        tuple(entry["factRequest"] for entry in entries)  # type: ignore[misc]
    )
    if entries:
        five_minute_count, official_day_count = _required_warmup_counts(requests)
    else:
        five_minute_count, official_day_count = 0, 0
    return BacktestIndexRequirement(
        required=bool(entries),
        binding=plan.reference_market,
        condition_paths=tuple(str(entry["planPath"]) for entry in entries),
        fact_requests=requests,
        required_five_minute_count=five_minute_count,
        required_official_day_count=official_day_count,
        index_requirement_hash=digest,
    )


def _required_warmup_counts(
    requests: tuple[MarketIndexFactRequest, ...],
) -> tuple[int, int]:
    """Return only the pre-event history explicitly requested by plan formulas."""

    five_minute_count = 0
    official_day_count = 0
    for request in requests:
        if isinstance(request, SmaFactRequest):
            official_day_count = max(official_day_count, request.period)
        elif isinstance(request, SmaLookbackFactRequest):
            official_day_count = max(
                official_day_count,
                request.period + request.lookback,
            )
        elif isinstance(request, ReturnFactRequest):
            required = request.window_size + 1
            if request.window is ReturnWindow.FIVE_MINUTE_BUCKETS:
                five_minute_count = max(five_minute_count, required)
            else:
                official_day_count = max(official_day_count, required)
        else:  # pragma: no cover - closed request union
            raise TypeError("unsupported market-index fact request")
    return five_minute_count, official_day_count


def market_index_data_hash(
    memberships: tuple[IndexArtifactMembership, ...],
) -> str:
    """Hash sorted exact index artifact memberships under the approved domain."""

    if type(memberships) is not tuple or any(
        type(item) is not IndexArtifactMembership for item in memberships
    ):
        raise TypeError("memberships must be an exact tuple of IndexArtifactMembership")
    ordered = tuple(sorted(memberships, key=lambda item: item.natural_key))
    if len({item.natural_key for item in ordered}) != len(ordered):
        raise ValueError("index artifact memberships must have unique natural identities")
    return sha256(_INDEX_DATA_DOMAIN + canonical_json(ordered).encode("utf-8")).hexdigest()


def _condition_parameters(condition: object) -> dict[str, int | Decimal | str]:
    parameters: dict[str, int | Decimal | str] = {}
    for name in ("period", "lookback", "window", "window_size", "threshold_ratio"):
        if not hasattr(condition, name):
            continue
        value = getattr(condition, name)
        parameters[name] = value.value if hasattr(value, "value") else value
    return dict(sorted(parameters.items()))


def _iter_index_evidence(
    evidence: ConditionEvidence,
) -> tuple[IndexConditionEvidence, ...]:
    values: list[IndexConditionEvidence] = []
    if evidence.index_evidence is not None:
        values.append(evidence.index_evidence)
    for child in evidence.children:
        values.extend(_iter_index_evidence(child))
    return tuple(values)


def summarize_backtest_index_conditions(
    plan: TradePlan,
    decisions: tuple[EvaluationResult, ...],
) -> tuple[BacktestIndexConditionSummary, ...]:
    """Count only persisted evaluator outcomes, grouped by exact plan path."""

    if not isinstance(plan, TradePlan):
        raise TypeError("plan must be a TradePlan")
    if type(decisions) is not tuple or any(
        type(item) is not EvaluationResult for item in decisions
    ):
        raise TypeError("decisions must be an exact tuple of EvaluationResult")
    leaves = iter_plan_index_conditions(plan)
    by_path = {path: condition for path, condition in leaves}
    counts = {
        path: {
            ConditionOutcome.SATISFIED: 0,
            ConditionOutcome.UNSATISFIED: 0,
            ConditionOutcome.MISSING_INPUT: 0,
        }
        for path in by_path
    }
    for decision in decisions:
        evidence_items = tuple(
            index_evidence
            for evidence in decision.snapshot.condition_evidence
            if isinstance(evidence, ConditionEvidence)
            for index_evidence in _iter_index_evidence(evidence)
        )
        seen_paths: set[str] = set()
        for evidence in evidence_items:
            if evidence.plan_path in seen_paths:
                raise ValueError("one decision cannot repeat an index condition path")
            seen_paths.add(evidence.plan_path)
            condition = by_path.get(evidence.plan_path)
            if condition is None or evidence.condition_type != condition.type:
                raise ValueError("decision index evidence does not match its plan path")
            counts[evidence.plan_path][evidence.outcome] += 1
    summaries: list[BacktestIndexConditionSummary] = []
    for path, condition in leaves:
        request = fact_request_for_index_condition(condition)
        path_counts = counts[path]
        satisfied = path_counts[ConditionOutcome.SATISFIED]
        unsatisfied = path_counts[ConditionOutcome.UNSATISFIED]
        missing = path_counts[ConditionOutcome.MISSING_INPUT]
        summaries.append(
            BacktestIndexConditionSummary(
                plan_path=path,
                condition_type=condition.type,
                parameters=_condition_parameters(condition),
                formula_id=request.formula_id,
                satisfied_count=satisfied,
                unsatisfied_count=unsatisfied,
                missing_count=missing,
                applicable_branch_count=satisfied + unsatisfied + missing,
            )
        )
    return tuple(summaries)


def build_reference_market_result(
    *,
    plan: TradePlan,
    dataset_hash: str,
    market_data_hash: str,
    event_start: date,
    dataset_warmup_start: date,
    official_open_dates: tuple[date, ...],
    bars: tuple[MarketIndexBar, ...],
    decisions: tuple[EvaluationResult, ...] = (),
) -> BacktestReferenceMarketResult:
    """Compute plan-specific coverage and summaries from frozen index membership."""

    requirement = build_backtest_index_requirement(plan)
    if not requirement.required or requirement.binding is None:
        raise ValueError("reference-market result requires an index-bearing plan")
    if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
        raise TypeError("bars must be an exact tuple of MarketIndexBar")
    if type(official_open_dates) is not tuple or any(
        type(item) is not date for item in official_open_dates
    ):
        raise TypeError("official_open_dates must be an exact tuple of dates")
    if official_open_dates != tuple(sorted(set(official_open_dates))):
        raise ValueError("official_open_dates must be ordered and unique")
    if any(bar.index_code is not requirement.binding.index_code for bar in bars):
        raise ValueError("reference-market bars must match the plan binding")
    warmup = tuple(bar for bar in bars if bar.bar_at.date() < event_start)
    five_minute = tuple(bar for bar in warmup if bar.interval is MarketIndexInterval.FIVE_MINUTE)
    official_daily = tuple(
        bar for bar in warmup if bar.interval is MarketIndexInterval.OFFICIAL_DAILY
    )
    warmup_open_dates = tuple(day for day in official_open_dates if day < event_start)
    event_open_dates = tuple(day for day in official_open_dates if day >= event_start)
    required_official_dates = (
        warmup_open_dates[-requirement.required_official_day_count :]
        if requirement.required_official_day_count
        else ()
    )
    actual_warmup_official_dates = {bar.bar_at.date() for bar in official_daily}
    all_warmup_five_minute_ends = tuple(
        bar_at
        for day in warmup_open_dates
        for bar_at in expected_minute_ends(day, is_open=True)[4::5]
    )
    required_five_minute_ends = (
        all_warmup_five_minute_ends[-requirement.required_five_minute_count :]
        if requirement.required_five_minute_count
        else ()
    )
    actual_warmup_five_minute_ends = {bar.bar_at for bar in five_minute}
    event_bars = tuple(bar for bar in bars if bar.bar_at.date() >= event_start)
    actual_event_official_dates = {
        bar.bar_at.date()
        for bar in event_bars
        if bar.interval is MarketIndexInterval.OFFICIAL_DAILY
    }
    actual_event_five_minute_ends = {
        bar.bar_at for bar in event_bars if bar.interval is MarketIndexInterval.FIVE_MINUTE
    }
    expected_event_five_minute_ends = {
        bar_at
        for day in event_open_dates
        for bar_at in expected_minute_ends(day, is_open=True)[4::5]
    }
    blockers: list[str] = []
    if (
        len(five_minute) < requirement.required_five_minute_count
        or len(required_five_minute_ends) < requirement.required_five_minute_count
    ):
        blockers.append("INSUFFICIENT_INDEX_FIVE_MINUTE_WARMUP")
    elif not set(required_five_minute_ends).issubset(actual_warmup_five_minute_ends):
        blockers.append("GAPPED_INDEX_FIVE_MINUTE_WARMUP")
    if (
        len(official_daily) < requirement.required_official_day_count
        or len(required_official_dates) < requirement.required_official_day_count
    ):
        blockers.append("INSUFFICIENT_INDEX_OFFICIAL_WARMUP")
    elif not set(required_official_dates).issubset(actual_warmup_official_dates):
        blockers.append("GAPPED_INDEX_OFFICIAL_WARMUP")
    if not set(event_open_dates).issubset(actual_event_official_dates):
        blockers.append("GAPPED_INDEX_OFFICIAL_EVENT")
    if not expected_event_five_minute_ends.issubset(actual_event_five_minute_ends):
        blockers.append("GAPPED_INDEX_FIVE_MINUTE_EVENT")
    resolved = resolve_board_reference(plan.symbol)
    first_warmup = min(
        (bar.bar_at.date() for bar in warmup),
        default=dataset_warmup_start,
    )
    return BacktestReferenceMarketResult(
        binding=BacktestReferenceMarketBinding(
            index_code=resolved.index_code,
            display_name=resolved.display_name,
            board=resolved.board,
        ),
        condition_paths=requirement.condition_paths,
        required_five_minute_count=requirement.required_five_minute_count,
        available_five_minute_count=len(five_minute),
        required_official_day_count=requirement.required_official_day_count,
        available_official_day_count=len(official_daily),
        warmup_start=first_warmup,
        warmup_end=event_start,
        coverage_status="AVAILABLE" if not blockers else "BLOCKED",
        blockers=tuple(sorted(blockers)),
        market_index_data_hash=market_data_hash,
        index_requirement_hash=requirement.index_requirement_hash,
        formula_definition_hash=FORMULA_DEFINITION_HASH,
        dataset_hash=dataset_hash,
        condition_summaries=summarize_backtest_index_conditions(plan, decisions),
    )


class MarketIndexReplaySeries:
    """Immutable offline bar series that publishes only cutoff-visible snapshots."""

    def __init__(
        self,
        *,
        index_code: MarketIndexCode,
        bars: tuple[MarketIndexBar, ...],
        dataset_revision: int,
    ) -> None:
        if not isinstance(index_code, MarketIndexCode):
            raise TypeError("index_code must be a MarketIndexCode")
        if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
            raise TypeError("bars must be an exact tuple of MarketIndexBar")
        if type(dataset_revision) is not int or not 1 <= dataset_revision <= 2_147_483_647:
            raise ValueError("dataset_revision must be a positive 32-bit integer")
        if any(bar.index_code is not index_code for bar in bars):
            raise ValueError("every replay bar must match index_code")
        ordered = tuple(sorted(bars, key=lambda bar: (bar.bar_at, bar.interval.value)))
        identities = tuple((bar.interval, bar.bar_at) for bar in ordered)
        if len(set(identities)) != len(identities):
            raise ValueError("replay index bars must have unique natural identities")
        self._index_code = index_code
        self._bars = ordered
        self._dataset_revision = dataset_revision
        self._snapshots: dict[tuple[datetime, datetime, str, int], MarketIndexSnapshot] = {}

    def snapshot(
        self,
        *,
        decision_cutoff: datetime,
        requests: tuple[MarketIndexFactRequest, ...],
        observed_no_later_than: datetime,
    ) -> MarketIndexSnapshot:
        for name, value in (
            ("decision_cutoff", decision_cutoff),
            ("observed_no_later_than", observed_no_later_than),
        ):
            if value.utcoffset() != timedelta(hours=8):
                raise ValueError(f"{name} must use the Asia/Shanghai offset")
        normalized_requests = union_fact_requests(requests)
        key = (
            decision_cutoff,
            observed_no_later_than,
            market_index_request_set_hash(normalized_requests),
            self._dataset_revision,
        )
        cached = self._snapshots.get(key)
        if cached is not None:
            return cached
        visible = tuple(
            bar
            for bar in self._bars
            if bar.bar_at <= decision_cutoff and bar.observed_at <= observed_no_later_than
        )
        five_minute = tuple(
            bar for bar in visible if bar.interval is MarketIndexInterval.FIVE_MINUTE
        )
        official_daily = tuple(
            bar for bar in visible if bar.interval is MarketIndexInterval.OFFICIAL_DAILY
        )
        five_minute_count, official_daily_count = required_bar_counts(normalized_requests)
        snapshot_bars = five_minute[-five_minute_count:] + official_daily[-official_daily_count:]
        content_revision = max(
            (bar.provider_revision for bar in snapshot_bars),
            default=1,
        )
        snapshot_observed_at = max(
            (bar.observed_at for bar in snapshot_bars),
            default=observed_no_later_than,
        )
        snapshot = build_market_index_snapshot(
            index_code=self._index_code,
            decision_cutoff=decision_cutoff,
            requests=normalized_requests,
            five_minute_bars=five_minute,
            official_daily_bars=official_daily,
            content_revision=content_revision,
            observed_at=snapshot_observed_at,
            observed_no_later_than=observed_no_later_than,
        )
        self._snapshots[key] = snapshot
        return snapshot


__all__ = [
    "BacktestIndexRequirement",
    "BacktestIndexConditionSummary",
    "BacktestReferenceMarketResult",
    "IndexArtifactMembership",
    "MarketIndexReplaySeries",
    "build_backtest_index_requirement",
    "build_reference_market_result",
    "market_index_data_hash",
    "summarize_backtest_index_conditions",
]
