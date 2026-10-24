"""HTTP idempotency and stable errors around the owned exception transaction."""

from trade_plan_monitor.runtime.market_exceptions import (
    apply_exception_decision,
    current_exception_authority,
)
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    ExceptionRevocationCommand,
    preview_exception,
    revoke_exception,
)
from trade_plan_monitor.state.repositories import IdempotencyKeyReuseError
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay
from trade_plan_monitor.web.routers.plan_exceptions import (
    ExceptionPreviewApiView,
    ExceptionReceiptApiView,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, ErrorDetail


def mutate_exception(lifecycle, *, operation_name, command, context, request_hash):
    response_model = (ExceptionPreviewApiView if operation_name == "PREVIEW"
                      else ExceptionReceiptApiView)
    try:
        with lifecycle._unit_of_work() as work:
            replay = claim_replay(work, context=context, request_hash=request_hash,
                                  model_type=response_model)
            if replay is not None:
                return replay
            now = lifecycle._clock()
            raw = command.model_dump(mode="python")
            if operation_name == "PREVIEW":
                result = preview_exception(work.daily, ExceptionPreviewCommand.model_validate(raw),
                    current=lambda c: current_exception_authority(work, c, now), now=now)
            elif operation_name == "DECISION":
                result = apply_exception_decision(work,
                    ExceptionDecisionCommand.model_validate(raw), now=now)
            elif operation_name == "REVOKE":
                result = revoke_exception(work.daily,
                    ExceptionRevocationCommand.model_validate(raw), now=now)
            else:
                raise ValueError("unknown exception operation")
            result = response_model.model_validate_json(result.model_dump_json())
            complete_replay(work, context=context, request_hash=request_hash, response=result)
            work.commit()
            return result
    except ExceptionAuthorityError as error:
        code = {404: ApiErrorCode.NOT_FOUND, 422: ApiErrorCode.VALIDATION_ERROR}.get(
            error.status, ApiErrorCode.CONFLICT)
        raise ApiError(code, details=(ErrorDetail(
            code=error.reason, message="Exception occurrence requires current explicit authority",
            location=("body",)),)) from None
    except IdempotencyKeyReuseError:
        raise ApiError(ApiErrorCode.CONFLICT) from None
