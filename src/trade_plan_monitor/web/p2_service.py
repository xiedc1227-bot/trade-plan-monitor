"""Read-only estimates from owned plan/evaluation evidence, never a trade grant."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from trade_plan_monitor.decision.p2_economics import EconomicsResult, calculate_economics
from trade_plan_monitor.domain.p2_evidence import FrozenPretrade
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.runtime.market_exceptions import current_exception_authority
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError, _quantity
from trade_plan_monitor.state.market_linkage_authority import linked_index_current
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode, ApiValue, ErrorDetail


class P2PreviewCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    rule_id: str = Field(min_length=1, max_length=128)
    occurrence_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposed_quantity: int | None = Field(default=None, strict=True, gt=0,
                                          le=9_007_199_254_740_991)


class P2PreviewView(ApiValue):
    computed_at: ShanghaiDatetime
    plan_version_id: str
    rule_id: str
    quantity: int | None
    evidence: FrozenPretrade
    economics: EconomicsResult
    authority_granted: Literal[False] = False


def preview_economics(lifecycle, *, command):
    now = lifecycle._clock()

    def reject(message):
        raise ApiError(ApiErrorCode.CONFLICT, details=(ErrorDetail(
            code=message, location=("pretrade",),
            message="Current pretrade evidence is unavailable"),))

    with lifecycle._unit_of_work() as work:
        details = work.plans.get_version_details(str(command.plan_version_id))
        if details is None or details.daily_issues:
            reject("P2_REVIEW_REQUIRED")
        plan = load_plan_json(details.payload_json)
        active = work.plans.get_active(plan.symbol)
        head = work.daily.get("evaluation-head-" + plan.symbol)
        review = work.daily.get("review-" + str(command.plan_version_id))
        if (plan.schema_version != 8 or active is None or head is None or review is None
                or not review["payload"].get("confirmed")
                or active.plan_version_id != str(command.plan_version_id)):
            reject("P2_CURRENT_EVALUATION_REQUIRED")
        state = head["payload"]
        account = DailyAccounting(work.daily)
        inventory = account.snapshot(plan.symbol, now.date())
        if (state["content_hash"] != details.content_hash
                or not linked_index_current(work.daily.session, state, now)
                or not account.evaluation_current(state,
                    plan_version_id=str(command.plan_version_id),
                    content_hash=details.content_hash, inventory=inventory, now=now,
                    require_daily_data=False)):
            reject("P2_CURRENT_EVALUATION_REQUIRED")
        frozen = next((FrozenPretrade.model_validate(item) for item in state.get("pretrade", ())
                       if item["rule_id"] == command.rule_id), None)
        if frozen is None:
            reject("P2_RULE_EVIDENCE_REQUIRED")
        if command.occurrence_id is not None:
            row = work.daily.get(command.occurrence_id)
            if row is None or row["kind"] != "EXCEPTION_CANDIDATE":
                reject("P2_OCCURRENCE_REQUIRED")
            candidate = ExceptionCandidate.model_validate(row["payload"])
            if (candidate.binding.plan_version_id != str(command.plan_version_id)
                    or candidate.binding.rule_id != command.rule_id):
                reject("P2_OCCURRENCE_MISMATCH")
            try:
                context = current_exception_authority(work, candidate, now)
                if context.blockers:
                    reject(context.blockers[0])
                # Estimate failed gates too; quantity validation grants no authority.
                quantity = _quantity(candidate, context.model_copy(update={"pretrade": None}),
                                     command.proposed_quantity)
            except ExceptionAuthorityError as error:
                reject(error.reason)
        else:
            if command.proposed_quantity is not None:
                reject("P2_ORDINARY_QUANTITY_IS_FROZEN")
            decision = next((item for item in state.get("market_linkage", ())
                             if item["rule_id"] == command.rule_id), None)
            if decision is not None and decision["calculation"]["route"] is not None:
                reject("P2_OCCURRENCE_REQUIRED")
            quantity = None if decision is None else decision["calculation"]["candidate_quantity"]
        quote = state.get("quote")
        close = frozen.sizing.close_fen
        price = (int(close) if close is not None and close == int(close) else None)
        if now.date() != frozen.decision_session:
            price = None if quote is None else quote["price_fen"]
        result = calculate_economics(frozen.policy.economics, quantity=quantity, entry_fen=price,
                                     symbol=plan.symbol, session=now.date())
        return P2PreviewView(computed_at=now, plan_version_id=str(command.plan_version_id),
            rule_id=command.rule_id, quantity=quantity, evidence=frozen, economics=result)
