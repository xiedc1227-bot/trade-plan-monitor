"""Daily reminders carry signal authority and risk scope separately from five-minute payloads."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, WholeQty
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.daily_repository import daily_hash


class DailyAlertPayload(DailyValue):
    payload_schema_version: Literal["daily-simulation-alert-v1"] = "daily-simulation-alert-v1"
    event_id: UUID
    dedup_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_id: str
    plan_version: int = Field(strict=True, gt=0)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_version_id: str
    review_id: str
    activation_revision: int = Field(strict=True, ge=1)
    symbol: str
    name: str
    signal_type: Literal["BUY", "SELL", "RISK_EXIT", "REMINDER"]
    severity: Literal["ACTION", "RISK", "INFO"]
    trading_date: date
    evaluated_at: ShanghaiDatetime
    cause_id: str
    rule_id: str | None = None
    alert_kind: Literal["RISK_ALERT"] | None = None
    confirmed_trade_date: date | None
    execution_date: date | None
    quantity: WholeQty | None
    simulated_qty: WholeQty
    risk_scope: dict | None
    evidence: tuple[dict, ...] = Field(max_length=50)
    next_step: Literal[
        "CONFIRM_SIMULATED_TRADE", "REVIEW_RISK_EXIT", "REVIEW_ALERT"
    ]

    @model_validator(mode="after")
    def identity(self):
        expected = daily_alert_key(
            self.cause_id,
            self.plan_hash,
            self.signal_type,
            self.simulated_qty,
            self.quantity,
            self.risk_scope,
            self.confirmed_trade_date,
        )
        expected_severity = ("RISK" if self.signal_type in {"RISK_EXIT", "REMINDER"}
            else "ACTION")
        if self.dedup_key != expected or self.severity != expected_severity:
            raise ValueError("daily alert identity/severity is invalid")
        if self.signal_type == "REMINDER" and (
            self.quantity is not None or self.simulated_qty != 0
            or self.risk_scope is not None or self.execution_date is not None
            or self.confirmed_trade_date is None or self.next_step != "REVIEW_ALERT"
            or self.rule_id is None or self.alert_kind != "RISK_ALERT"
        ):
            raise ValueError("reminder cannot carry simulation authority")
        return self


class DailyAlertEvent(DailyAlertPayload):
    sequence: int = Field(strict=True, gt=0)
    message_text: str
    created_at: ShanghaiDatetime
    acknowledged_at: ShanghaiDatetime | None = None

    @model_validator(mode="after")
    def event(self):
        if self.created_at < self.evaluated_at or self.message_text != render_daily_alert(self):
            raise ValueError("daily event rendering/time is invalid")
        return self


def daily_alert_key(
    cause_id,
    plan_hash,
    side,
    simulated_qty,
    quantity=None,
    risk_scope=None,
    confirmed_trade_date=None,
):
    identity = {
        "cause_id": cause_id,
        "plan_hash": plan_hash,
        "side": side,
        "simulated_qty": simulated_qty,
    }
    if side == "RISK_EXIT":
        identity.update(
            quantity=quantity, risk_scope=risk_scope, confirmed_trade_date=str(confirmed_trade_date)
        )
    elif side == "REMINDER":
        identity["confirmed_trade_date"] = str(confirmed_trade_date)
    return daily_hash("daily-simulation-alert-v1", identity)


def render_daily_alert(payload):
    if payload.signal_type == "REMINDER":
        return (
            f"{payload.name} {payload.symbol} 风险提醒：规则 {payload.rule_id} "
            f"于 {payload.confirmed_trade_date} 确认。请查看证据；此提醒不改变模拟仓位。"
        )
    if payload.signal_type == "RISK_EXIT":
        scope = payload.risk_scope or {}
        detail = (
            f"CORE {scope.get('core_qty', '待核验')} 股 / "
            f"TACTICAL {scope.get('tactical_qty', '待核验')} 股"
        )
        quantity = payload.quantity if payload.quantity is not None else "待核验"
        return (
            f"{payload.name} {payload.symbol} 风险退出；范围 {detail}；数量 {quantity} 股。"
            "提醒不会修改模拟仓位。请确认当前完整整手模拟交易。"
        )
    return (
        f"{payload.name} {payload.symbol} {payload.signal_type} 提醒："
        f"原收盘确认 {payload.confirmed_trade_date}，仅 {payload.execution_date} 收盘前有效，"
        f"完整数量 {payload.quantity} 股。信号 {payload.cause_id}；"
        "当前仍须在区间并核验可交易条件。提醒不会修改模拟仓位；模拟交易需要独立确认。"
    )


class ObsoleteDailyAlertEvent(DailyValue):
    """Preserved development reminder metadata has no simulation/send authority."""
    payload_schema_version: Literal["daily-plan-alert-v1"] = "daily-plan-alert-v1"
    status: Literal["UNSUPPORTED"] = "UNSUPPORTED"
    reason: Literal["DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"] = (
        "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
    )
    event_id: UUID
    sequence: int = Field(strict=True, gt=0)
    dedup_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_id: str
    plan_version: int = Field(strict=True, gt=0)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    symbol: str
    name: str
    signal_type: Literal["BUY", "SELL", "RISK_EXIT"]
    trading_date: date
    evaluated_at: ShanghaiDatetime
    message_text: str = Field(max_length=10000)
    created_at: ShanghaiDatetime
    acknowledged_at: ShanghaiDatetime | None
