"""Owned current simulation resources; previews write nothing and grant nothing."""

from trade_plan_monitor.decision.market_exception_policy import exception_quantity_grid
from trade_plan_monitor.decision.p3_capital import assess_capital
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.p2_evidence import FrozenPretrade
from trade_plan_monitor.domain.plan_codec import PlanDocumentError, load_plan_json
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.market_exceptions import current_exception_authority
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError
from trade_plan_monitor.state.market_linkage_authority import linked_index_current
from trade_plan_monitor.state.p3_capital_repository import CapitalCommandConflict, CapitalRepository
from trade_plan_monitor.state.p3_capital_service import (
    CapitalInventoryLot,
    CapitalOpeningCommand,
    CapitalOpeningContext,
    CapitalOpeningError,
    confirm_capital_opening,
)
from trade_plan_monitor.state.p3_current import current_capital_inputs
from trade_plan_monitor.state.repositories import IdempotencyKeyReuseError
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay
from trade_plan_monitor.web.p3_schemas import (
    CapitalBookView,
    CapitalOpeningReceipt,
    CapitalPreviewView,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, ErrorDetail


def _reject(reason, status=409):
    code = {404: ApiErrorCode.NOT_FOUND, 422: ApiErrorCode.VALIDATION_ERROR}.get(
        status, ApiErrorCode.CONFLICT)
    raise ApiError(code, details=(ErrorDetail(code=reason, location=("capital",),
        message="Current reviewed simulation capital evidence is required"),))


def _reviewed(work, version_id):
    details = work.plans.get_version_details(str(version_id))
    if details is None:
        _reject("CAPITAL_PLAN_NOT_FOUND", 404)
    try:
        plan = load_plan_json(details.payload_json)
    except PlanDocumentError:
        _reject("CAPITAL_SCHEMA_NOT_ADMITTED")
    active = work.plans.get_active(plan.symbol)
    review = work.daily.get("review-"+str(version_id))
    if (plan.schema_version != 9 or details.daily_issues or active is None
            or active.plan_version_id != str(version_id) or review is None
            or not review["payload"].get("confirmed")
            or review["payload"]["content_hash"] != details.content_hash):
        _reject("CAPITAL_CURRENT_REVIEW_REQUIRED")
    return details, plan, active, review["payload"]


def read_capital_book(lifecycle, *, symbol):
    now = lifecycle._clock()
    with lifecycle._unit_of_work() as work:
        accounting = DailyAccounting(work.daily)
        inventory = accounting.snapshot(symbol, now.date())
        values = current_capital_inputs(accounting, symbol, now)
        book = CapitalRepository(work.daily.session).get(symbol)
        position = accounting._position(symbol)
        return CapitalBookView(computed_at=now, symbol=symbol,
            inventory_known=inventory["known"], inventory_revision=inventory["revision"],
            inventory_lots=() if position is None else tuple(CapitalInventoryLot(
                lot_id=lot["id"], bucket=lot["bucket"], quantity=lot["quantity"])
                for lot in position["payload"]["batches"]), book=book, **values)


def _opening_context(work, command):
    details, plan, _, review = _reviewed(work, command.plan_version_id)
    # Same symbol write fence as explicit simulation; no stale inventory snapshot.
    work.daily.lock_symbol(plan.symbol)
    work.daily.session.expire_all()
    accounting = DailyAccounting(work.daily)
    inventory = accounting.snapshot(plan.symbol, command.observed_at.date())
    position = accounting._position(plan.symbol)
    return CapitalOpeningContext(plan_version_id=command.plan_version_id,
        symbol=plan.symbol, content_hash=details.content_hash,
        review_binding_hash=daily_hash("capital-opening-review-v1", review), reviewed=True,
        inventory_known=inventory["known"], inventory_revision=inventory["revision"],
        lots=() if position is None else tuple(CapitalInventoryLot(lot_id=lot["id"],
            bucket=lot["bucket"], quantity=lot["quantity"])
            for lot in position["payload"]["batches"]), blockers=())


def open_capital(lifecycle, *, command, context, request_hash):
    now = lifecycle._clock()
    try:
        with lifecycle._unit_of_work() as work:
            prior = claim_replay(work, context=context, request_hash=request_hash,
                                 model_type=CapitalOpeningReceipt)
            if prior is not None:
                return prior
            event = confirm_capital_opening(work.daily.session,
                CapitalOpeningCommand.model_validate(command.model_dump(mode="python")),
                command_id=context.idempotency_key, now=now,
                current=lambda c: _opening_context(work, c))
            receipt = CapitalOpeningReceipt(event=event)
            complete_replay(work, context=context, request_hash=request_hash, response=receipt)
            work.commit()
            return receipt
    except CapitalOpeningError as error:
        _reject(error.reason, error.status)
    except CapitalCommandConflict:
        _reject("CAPITAL_IDEMPOTENCY_CONFLICT")
    except IdempotencyKeyReuseError:
        _reject("CAPITAL_IDEMPOTENCY_CONFLICT")


def preview_capital(lifecycle, *, command):
    now = lifecycle._clock()
    with lifecycle._unit_of_work() as work:
        details, plan, active, review = _reviewed(work, command.plan_version_id)
        head = work.daily.get("evaluation-head-"+plan.symbol)
        if head is None:
            _reject("CAPITAL_CURRENT_EVALUATION_REQUIRED")
        state = head["payload"]
        accounting = DailyAccounting(work.daily)
        inventory = accounting.snapshot(plan.symbol, now.date())
        if (state["review_id"] != review["review_id"]
                or state["activation_revision"] != active.revision
                or not linked_index_current(work.daily.session, state, now)
                or not accounting.evaluation_current(state, plan_version_id=details.id,
                    content_hash=details.content_hash, inventory=inventory, now=now,
                    require_daily_data=False)):
            _reject("CAPITAL_CURRENT_EVALUATION_REQUIRED")
        frozen = next((FrozenPretrade.model_validate(p) for p in state.get("pretrade", ())
                       if p["rule_id"] == command.rule_id), None)
        rule = next((r for r in plan.ordinary_rules if r.rule_id == command.rule_id), None)
        if (frozen is None or rule is None or not hasattr(rule, "pretrade_policy")
                or frozen.content_hash != details.content_hash
                or frozen.policy != rule.pretrade_policy):
            _reject("CAPITAL_RULE_EVIDENCE_REQUIRED")
        if command.occurrence_id is not None:
            row = work.daily.get(command.occurrence_id)
            if row is None or row["kind"] != "EXCEPTION_CANDIDATE":
                _reject("CAPITAL_OCCURRENCE_REQUIRED")
            candidate = ExceptionCandidate.model_validate(row["payload"])
            b = candidate.binding
            if b.plan_version_id != details.id or b.rule_id != command.rule_id:
                _reject("CAPITAL_OCCURRENCE_MISMATCH")
            try:
                context = current_exception_authority(work, candidate, now)
            except ExceptionAuthorityError as error:
                _reject(error.reason, error.status)
            if context.blockers:
                _reject(context.blockers[0])
            quantity = exception_quantity_grid(route=b.route, base_quantity=b.base_quantity,
                minimum=b.minimum, increment=b.increment,
                proposed_quantity=command.proposed_quantity)
            if quantity.blockers:
                _reject(quantity.blockers[0], 422)
            quantity = quantity.candidate_quantity
        else:
            if command.proposed_quantity is not None:
                _reject("CAPITAL_ORDINARY_QUANTITY_IS_FROZEN", 422)
            decision = next((d for d in state.get("market_linkage", ())
                             if d["rule_id"] == command.rule_id), None)
            if decision is not None and decision["calculation"]["route"] is not None:
                _reject("CAPITAL_OCCURRENCE_REQUIRED")
            quantity = None if decision is None else decision["calculation"]["candidate_quantity"]
        close = frozen.sizing.close_fen
        price = int(close) if close is not None and close == int(close) else None
        if now.date() != frozen.decision_session:
            try:
                price = DailyExecutionQuote.model_validate({
                    **(state.get("quote") or {}), "evaluated_at": now}).price_fen
            except ValueError:
                _reject("CAPITAL_CURRENT_QUOTE_REQUIRED")
        assessment = assess_capital(plan.position, quantity=quantity, price_fen=price,
            total_qty=inventory["total_qty"] if inventory["known"] else None,
            symbol=plan.symbol, session=now.date(), inventory_revision=inventory["revision"],
            **current_capital_inputs(accounting, plan.symbol, now))
        return CapitalPreviewView(computed_at=now, plan_version_id=details.id,
            rule_id=command.rule_id, quantity=quantity, evidence=frozen, assessment=assessment)
