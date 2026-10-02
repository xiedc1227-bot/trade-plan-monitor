"""Human-only daily evidence, exact-share inventory and actual execution boundaries."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator

from trade_plan_monitor.ai.daily_review import (
    DailyFieldBinding,
    DailyMapping,
    DailyReviewSnapshot,
    DailySourceExclusion,
    DailySupplement,
    build_daily_review,
    daily_contract_bindings,
    daily_source_clauses,
    normalize_daily_exclusions,
    semantic_values,
)
from trade_plan_monitor.domain.daily_plan_models import FactKind
from trade_plan_monitor.domain.daily_plan_validation import (
    DailyPlanDraft,
    daily_draft_content_sha256,
    daily_draft_json,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.daily_scope import require_technical_text
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.daily_state_models import (
    DailyEvaluationState,
    DailyInventoryView,
    DailyObsoleteRisk,
    DailyRiskAction,
    DailyRiskState,
    DailySignalState,
)
from trade_plan_monitor.web.routers.plans import (
    PlanDocument,
    PlanServiceDependency,
    PlanSymbolPath,
    Sha256Hex,
)
from trade_plan_monitor.web.schemas import ApiValue, MutationContextDependency

router = APIRouter(prefix="/api/v1", tags=["daily-plans"])
Qty = Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
WholeQty = Annotated[int, Field(strict=True, ge=0, multiple_of=100, le=9_007_199_254_740_991)]
PositiveWholeQty = Annotated[
    int, Field(strict=True, gt=0, multiple_of=100, le=9_007_199_254_740_991)
]


class DailySupplementCommand(ApiValue):
    candidate_json: PlanDocument
    content_hash: Sha256Hex
    supplements: tuple[DailySupplement, ...] = Field(min_length=1, max_length=2000, strict=False)
    expected_revision: Qty


class DailyMutationReceipt(ApiValue):
    id: str
    revision: Qty
    recorded_at: ShanghaiDatetime


class DailyReviewPreviewCommand(ApiValue):
    candidate_json: PlanDocument
    source_text: str = Field(min_length=1, max_length=200_000)
    mapping: DailyMapping | None = None
    scope_selections: tuple[DailySourceExclusion, ...] = Field(
        default=(), max_length=512, strict=False
    )


class DailyReviewPreview(ApiValue):
    candidate_json: PlanDocument
    review: DailyReviewSnapshot
    supplement_revision: Qty


class DailyEditorSchemaView(ApiValue):
    schema_version: Literal[4] = 4
    candidate_schema: dict
    operation_schemas: dict


@router.get("/daily-plan-editor-schema", response_model=DailyEditorSchemaView)
async def editor_schema():
    return DailyEditorSchemaView(
        candidate_schema=DailyPlanDraft.model_json_schema(),
        operation_schemas={
            "FACT": DailyFactCommand.model_json_schema(by_alias=True),
            "POSITION": DailyPositionCommand.model_json_schema(by_alias=True),
            "SIMULATION": DailySimulationCommand.model_json_schema(by_alias=True),
            "REASSESSMENT": DailyRiskReassessmentCommand.model_json_schema(by_alias=True),
        },
    )


async def _preview(command: DailyReviewPreviewCommand, context: MutationContextDependency, service):
    del context
    draft = load_daily_draft_json(command.candidate_json)
    digest = daily_draft_content_sha256(draft)
    if command.mapping is None:
        clauses = daily_source_clauses(command.source_text)
        mapping = DailyMapping(
            mapping_version="daily-mapping-v1",
            candidate_content_hash=digest,
            clauses=clauses,
            bindings=daily_contract_bindings(draft),
            supplements=(),
        )
    else:
        values = semantic_values(draft)
        # Client-provided human authority is discarded; restore only server-registered evidence.
        mapping = command.mapping.model_copy(
            update={
                "candidate_content_hash": digest,
                "bindings": tuple(
                    b
                    for b in command.mapping.bindings
                    if b.origin != "HUMAN_SUPPLEMENT"
                    and b.path in values
                    and type(b.value) is type(values[b.path])
                    and b.value == values[b.path]
                ),
                "supplements": (),
                "clauses": normalize_daily_exclusions(command.mapping.clauses, command.source_text),
            }
        )
    registered = await service.read_daily_supplements(candidate_json=command.candidate_json)
    if registered["content_hash"] != digest:
        raise ValueError("registered supplements differ from the current candidate")
    supplements = tuple(DailySupplement.model_validate(s) for s in registered["supplements"])
    registered_paths = {s.path for s in supplements}
    mapping = mapping.model_copy(
        update={
            "supplements": supplements,
            "bindings": (
                *(b for b in mapping.bindings if b.path not in registered_paths),
                *(
                    DailyFieldBinding(
                        path=s.path, value=s.value, origin="HUMAN_SUPPLEMENT", unit="JSON",
                        clause_ids=(), supplement_id=s.supplement_id,
                    )
                    for s in supplements
                ),
            ),
        }
    )
    if command.scope_selections:
        if any(s.origin != "HUMAN_SCOPE_SELECTION" for s in command.scope_selections):
            raise ValueError("scope selection must be an explicit human operation")
        treatments = {
            c.clause_id: c
            for c in daily_source_clauses(
                command.source_text,
                (
                    *[
                        s
                        for c in mapping.clauses
                        for s in c.exclusions
                        if s.origin == "HUMAN_SCOPE_SELECTION"
                    ],
                    *command.scope_selections,
                ),
            )
        }
        affected = {
            c.clause_id
            for c in mapping.clauses
            if any(c.start <= s.start < s.end <= c.end for s in command.scope_selections)
        }
        mapping = mapping.model_copy(
            update={
                "clauses": tuple(
                    treatments[c.clause_id] if c.clause_id in affected else c
                    for c in mapping.clauses
                )
            }
        )
    return DailyReviewPreview(
        candidate_json=daily_draft_json(draft),
        review=build_daily_review(draft, mapping, command.source_text),
        supplement_revision=registered["revision"],
    )


@router.post("/daily-plan-review-previews", response_model=DailyReviewPreview)
async def preview(
    command: DailyReviewPreviewCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
):
    from trade_plan_monitor.web.errors import ApiError
    from trade_plan_monitor.web.schemas import ApiErrorCode

    try:
        return await _preview(command, context, service)
    except ValueError:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


class DailyOfficialEvidence(ApiValue):
    issuer: str = Field(min_length=1, max_length=200)
    document_title: str = Field(min_length=1, max_length=500)
    document_url: str = Field(pattern=r"^https://[^\s]+$", max_length=2000)
    published_at: ShanghaiDatetime = Field(strict=False)
    verified_at: ShanghaiDatetime = Field(strict=False)
    applicable_assertion: str = Field(min_length=20, max_length=2000)


class DailyFactCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    content_hash: Sha256Hex
    fact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=128)
    kind: FactKind
    trade_date: date = Field(strict=False)
    signal_id: str | None = None
    evidence: str = Field(min_length=20, max_length=2000)
    official_evidence: DailyOfficialEvidence | None = None
    expected_revision: Qty

    @model_validator(mode="after")
    def official_required(self):
        if self.kind not in {"TRADABILITY", "FULL_SESSION_SUSPENSION"}:
            require_technical_text(self.evidence)
            if self.official_evidence is not None:
                require_technical_text(self.official_evidence.applicable_assertion)
        if (
            self.kind in {"TRADABILITY", "FULL_SESSION_SUSPENSION"}
            and self.official_evidence is None
        ):
            raise ValueError("this fact requires manually verified official evidence")
        if self.kind in {"INDEPENDENT_EVENT", "SIGNAL_INVALIDATION"} and self.signal_id is None:
            raise ValueError("fact must name the prior signal")
        return self


class DailyPositionCommand(ApiValue):
    symbol: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    core_qty: WholeQty
    tactical_qty: WholeQty
    expected_revision: Qty

    @model_validator(mode="after")
    def bounded_total(self):
        if self.core_qty + self.tactical_qty > 9_007_199_254_740_991:
            raise ValueError("aggregate simulation inventory exceeds the transport quantity bound")
        return self


class DailySimulationCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    cause_id: str = Field(min_length=1, max_length=128)
    expected_cause_revision: Qty
    expected_inventory_revision: Qty
    quantity: PositiveWholeQty


class DailyRiskReassessmentCommand(ApiValue):
    symbol: str = Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")
    risk_id: str
    plan_version_id: UUID = Field(strict=False)
    content_hash: Sha256Hex
    expected_revision: Qty
    removal_evidence: DailyOfficialEvidence
    target_core_qty: WholeQty
    target_tactical_qty: WholeQty
    involves_core: bool = Field(strict=True)
    scope_evidence: str = Field(min_length=20, max_length=2000)


class DailyInventoryApiView(DailyInventoryView, ApiValue):
    pass


class DailySimulationReceipt(ApiValue):
    simulation_id: str
    side: Literal["BUY", "SELL"]
    quantity: PositiveWholeQty
    price_fen: Annotated[int, Field(strict=True, gt=0)]
    simulated_at: ShanghaiDatetime
    inventory_revision: Qty
    inventory: DailyInventoryApiView
    signal_id: str | None


class DailySignalApiView(DailySignalState, ApiValue):
    pass


class DailyRiskApiView(DailyRiskState, ApiValue):
    pass


class DailyRiskActionApiView(DailyRiskAction, ApiValue):
    pass


class DailyEvaluationApiView(DailyEvaluationState, ApiValue):
    inventory: DailyInventoryApiView
    signals: tuple[DailySignalApiView, ...]
    risks: tuple[DailyRiskApiView, ...]
    risk_action: DailyRiskActionApiView


class DailyObsoleteRiskApiView(DailyObsoleteRisk, ApiValue):
    pass


class DailyStateView(ApiValue):
    symbol: str
    evaluated_at: ShanghaiDatetime | None
    status: Literal["CURRENT", "AWAITING_EVALUATION", "INACTIVE", "UNSUPPORTED"]
    reason: str | None = None
    risks: tuple[DailyObsoleteRiskApiView, ...] = Field(default=(), max_length=2)
    snapshot: DailyEvaluationApiView | None


class DailyInventoryResource(ApiValue):
    symbol: str
    evaluated_at: ShanghaiDatetime
    status: Literal["CURRENT", "UNSUPPORTED"]
    reason: str | None = None
    snapshot: DailyInventoryApiView | None


@router.post("/daily-plan-review-supplements", response_model=DailyMutationReceipt)
async def supplements(
    command: DailySupplementCommand,
    service: PlanServiceDependency,
    context: MutationContextDependency,
):
    return await service.mutate_daily(operation="SUPPLEMENT", command=command, context=context)


@router.post("/daily-plan-facts", response_model=DailyMutationReceipt)
async def facts(
    command: DailyFactCommand,
    service: PlanServiceDependency,
    context: MutationContextDependency,
    request: Request,
):
    result = await service.mutate_daily(operation="FACT", command=command, context=context)
    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is not None and hasattr(runtime, "reevaluate_daily"):
        await runtime.reevaluate_daily(command.plan_version_id)
    return result


@router.post("/daily-position-confirmations", response_model=DailyMutationReceipt)
async def positions(
    command: DailyPositionCommand,
    service: PlanServiceDependency,
    context: MutationContextDependency,
    request: Request,
):
    result = await service.mutate_daily(operation="POSITION", command=command, context=context)
    await _reevaluate_symbol(request, service, command.symbol)
    return result


@router.post("/daily-simulated-trades", response_model=DailySimulationReceipt)
async def simulations(
    command: DailySimulationCommand,
    service: PlanServiceDependency,
    context: MutationContextDependency,
    request: Request,
):
    result = await service.mutate_daily(operation="SIMULATION", command=command, context=context)
    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is not None and hasattr(runtime, "reevaluate_daily"):
        await runtime.reevaluate_daily(command.plan_version_id)
    return result


async def _reevaluate_symbol(request, service, symbol):
    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is not None and hasattr(runtime, "reevaluate_daily"):
        active = await service.get_plan_activation_state(symbol=symbol)
        if active is not None and active.plan_version_id is not None:
            await runtime.reevaluate_daily(active.plan_version_id)


@router.post("/daily-risk-reassessments", response_model=DailyMutationReceipt)
async def reassessments(
    command: DailyRiskReassessmentCommand,
    service: PlanServiceDependency,
    context: MutationContextDependency,
    request: Request,
):
    result = await service.mutate_daily(operation="REASSESSMENT", command=command, context=context)
    runtime = getattr(request.app.state, "runtime_lifecycle", None)
    if runtime is not None and hasattr(runtime, "reevaluate_daily"):
        await runtime.reevaluate_daily(command.plan_version_id)
    return result


@router.get("/daily-plan-runtime/{symbol}", response_model=DailyStateView)
async def runtime(symbol: PlanSymbolPath, service: PlanServiceDependency):
    return await service.read_daily(symbol=symbol, trade_date=None)


@router.get("/daily-position-inventory", response_model=DailyInventoryResource)
async def inventory(
    service: PlanServiceDependency,
    symbol: Annotated[str, Query(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")],
    as_of_trade_date: Annotated[date, Query(alias="asOfTradeDate")],
):
    return await service.read_daily(symbol=symbol, trade_date=as_of_trade_date)
