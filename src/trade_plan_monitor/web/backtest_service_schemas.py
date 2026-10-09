"""Closed transport values for inert status and explicit lifecycle controls."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.service_contract import BacktestServiceState
from trade_plan_monitor.web.schemas import ApiValue

Epoch = Annotated[str, Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")]
Revision = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]
ServiceJobId = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


class BacktestServiceView(ApiValue):
    epoch: Epoch | None
    revision: Revision
    generation: Revision
    state: BacktestServiceState
    can_read: bool
    can_submit: bool
    can_cancel: bool
    can_export: bool
    physically_drained: bool
    authorized_job_ids: tuple[ServiceJobId, ...] = Field(max_length=1)
    reason: Literal["SERVICE_REPAIR_REQUIRED"] | None


class BacktestServiceStopCommand(ApiValue):
    epoch: Epoch
    expected_revision: Revision


class BacktestServiceRecoveryCommand(BacktestServiceStopCommand):
    action: Literal["RETRY_PREPARATION", "RESUME_JOBS"]
    resume_job_ids: tuple[ServiceJobId, ...] = Field(strict=False, max_length=1)

    @model_validator(mode="after")
    def selected(self) -> Self:
        if (self.action == "RESUME_JOBS") != (len(self.resume_job_ids) == 1):
            raise ValueError("recovery requires exactly the selected action inputs")
        return self


class BacktestServiceControlReceipt(ApiValue):
    epoch: Epoch
    revision: Revision
    action: Literal["STOP", "RETRY_PREPARATION", "RESUME_JOBS"]
    accepted: Literal[True] = True
