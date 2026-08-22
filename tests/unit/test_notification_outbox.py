"""Deterministic alert identity and rendering contract tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DataHealthSnapshot,
    DataHealthStatus,
    DecisionZone,
    EvaluationResult,
    EvidenceFact,
    EvidenceUnit,
    IntradayEvaluationIdentity,
    MissingInputCode,
    NextStep,
    NextStepCode,
    PositionSummary,
    RiskStateSnapshot,
    RiskStatus,
    RuleEvidence,
    RuleEvidenceCode,
    SignalIntent,
    SignalType,
    SymbolDecisionSnapshot,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    AnyCondition,
    OfficialCloseBelowLevelCondition,
    PriceInZoneCondition,
    RetreatFromSessionHighGteCondition,
    UpperWickRatioGteCondition,
)
from trade_plan_monitor.notifications.channels import (
    ChannelErrorCode,
    ConsoleChannel,
    DeliveryChannel,
    WebhookChannel,
    WebhookConfig,
)
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import (
    AlertEvent,
    AlertPayload,
    AlertPriceZone,
    AlertSeverity,
    build_alert_payload,
)
from trade_plan_monitor.notifications.render import AlertRenderError, render_alert

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = "003043.SZ"
PLAN_HASH = "a" * 64
TRADE_DATE = date(2026, 8, 7)
MARKET_DATA_AT = datetime(2026, 8, 7, 10, 25, tzinfo=SHANGHAI)
EVALUATED_AT = datetime(2026, 8, 7, 10, 25, 18, tzinfo=SHANGHAI)
EVENT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _satisfied_price_evidence(
    *, facts: tuple[EvidenceFact, ...] | None = None
) -> ConditionEvidence:
    return ConditionEvidence(
        condition=PriceInZoneCondition(zone="LOW_BUY"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=6420,
                unit=EvidenceUnit.FEN,
            ),
        )
        if facts is None
        else facts,
    )


def _pressure_reduction_evidence() -> ConditionEvidence:
    wick = UpperWickRatioGteCondition(minimum_ratio=Decimal("0.40"))
    retreat = RetreatFromSessionHighGteCondition(minimum_ratio=Decimal("0.01"))
    condition = AnyCondition(conditions=(wick, retreat))
    return ConditionEvidence(
        condition=condition,
        outcome=ConditionOutcome.SATISFIED,
        facts=(EvidenceFact(key="bar_count", value=3, unit=EvidenceUnit.BARS),),
        children=(
            ConditionEvidence(
                condition=wick,
                outcome=ConditionOutcome.SATISFIED,
                facts=(
                    EvidenceFact(
                        key="observed_ratio",
                        value=Decimal("0.50"),
                        unit=EvidenceUnit.RATIO,
                    ),
                ),
            ),
            ConditionEvidence(
                condition=retreat,
                outcome=ConditionOutcome.MISSING_INPUT,
                missing_inputs=(MissingInputCode.SESSION_BARS,),
            ),
        ),
    )


def _risk_line_evidence() -> ConditionEvidence:
    return ConditionEvidence(
        condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(EvidenceFact(key="current_price_fen", value=6070, unit=EvidenceUnit.FEN),),
    )


def _signal(
    signal_type: ActionableSignalType = ActionableSignalType.BUY_CORE_READY,
    *,
    matched_conditions: tuple[ConditionEvidence, ...] | None = None,
) -> SignalIntent:
    quantity: int | None = 100
    bucket: str | None = "CORE"
    target_lot_id: str | None = None
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    if signal_type is ActionableSignalType.BUY_TACTICAL_READY:
        bucket = "TACTICAL"
    elif signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
        bucket = "TACTICAL"
        target_lot_id = "lot-tactical-001"
    elif signal_type is ActionableSignalType.RISK_BREACH:
        quantity = None
        bucket = None
        next_step = NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY)
    elif signal_type is ActionableSignalType.RISK_EXIT_READY:
        bucket = "TACTICAL"
        target_lot_id = "lot-tactical-001"
    elif signal_type is ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT:
        bucket = "TACTICAL"
        target_lot_id = "lot-tactical-001"
        next_step = NextStep(code=NextStepCode.WAIT_FOR_SETTLEMENT)

    return SignalIntent(
        signal_type=signal_type,
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        trading_date=TRADE_DATE,
        cause_id=("risk-20260807" if signal_type.value.startswith("RISK_") else "episode-001"),
        quantity=quantity,
        bucket=bucket,
        target_lot_id=target_lot_id,
        matched_conditions=matched_conditions or (_satisfied_price_evidence(),),
        blockers=(),
        next_step=next_step,
    )


def _severity(signal_type: ActionableSignalType) -> AlertSeverity:
    return {
        ActionableSignalType.BUY_CORE_READY: AlertSeverity.ACTION,
        ActionableSignalType.BUY_TACTICAL_READY: AlertSeverity.ACTION,
        ActionableSignalType.PRESSURE_REDUCE_READY: AlertSeverity.RISK,
        ActionableSignalType.RISK_BREACH: AlertSeverity.RISK,
        ActionableSignalType.RISK_EXIT_READY: AlertSeverity.CRITICAL,
        ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT: AlertSeverity.CRITICAL,
    }[signal_type]


def _payload(
    signal_type: ActionableSignalType = ActionableSignalType.BUY_CORE_READY,
    *,
    name: str = "华亚智能",
    market_data_at: datetime | None = MARKET_DATA_AT,
    data_age_seconds: int | None = 18,
    price_fen: int | None = 6420,
    matched_conditions: tuple[ConditionEvidence, ...] | None = None,
    blockers: tuple[RuleEvidence, ...] = (),
) -> AlertPayload:
    signal = _signal(signal_type, matched_conditions=matched_conditions)
    relevant_zone = None
    zone = DecisionZone.BELOW_RISK
    if signal_type in {
        ActionableSignalType.BUY_CORE_READY,
        ActionableSignalType.BUY_TACTICAL_READY,
    }:
        zone = DecisionZone.LOW_BUY
        relevant_zone = AlertPriceZone(
            zone=DecisionZone.LOW_BUY,
            low_fen=6300,
            high_fen=6450,
            include_low=True,
            include_high=True,
        )
    elif signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
        zone = DecisionZone.PRESSURE
        relevant_zone = AlertPriceZone(
            zone=DecisionZone.PRESSURE,
            low_fen=6880,
            high_fen=7020,
            include_low=True,
            include_high=True,
        )

    return AlertPayload(
        event_id=EVENT_ID,
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        name=name,
        signal_type=signal.signal_type,
        severity=_severity(signal.signal_type),
        trading_date=TRADE_DATE,
        cause_id=signal.cause_id,
        evaluated_at=EVALUATED_AT,
        market_data_at=market_data_at,
        data_age_seconds=data_age_seconds,
        price_fen=price_fen,
        quantity=signal.quantity,
        bucket=signal.bucket,
        target_lot_id=signal.target_lot_id,
        matched_conditions=signal.matched_conditions,
        satisfied_conditions=signal.matched_conditions,
        unmet_conditions=(),
        blockers=blockers,
        zone=zone,
        relevant_zone=relevant_zone,
        risk_line_fen=6080,
        next_step=signal.next_step,
    )


def _contract_payload(signal_type: ActionableSignalType) -> AlertPayload:
    matched = (_satisfied_price_evidence(),)
    price_fen = 6420
    satisfied: tuple[ConditionEvidence | RuleEvidence, ...] = matched
    if signal_type is ActionableSignalType.PRESSURE_REDUCE_READY:
        matched = (_pressure_reduction_evidence(),)
        price_fen = 6900
        satisfied = (
            *matched,
            RuleEvidence(
                code=RuleEvidenceCode.PRESSURE_TOUCH,
                outcome=ConditionOutcome.SATISFIED,
            ),
        )
    elif signal_type in {
        ActionableSignalType.RISK_BREACH,
        ActionableSignalType.RISK_EXIT_READY,
        ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
    }:
        matched = (_risk_line_evidence(),)
        price_fen = 6070
        satisfied = matched
        if signal_type is not ActionableSignalType.RISK_BREACH:
            satisfied = (
                *matched,
                RuleEvidence(
                    code=RuleEvidenceCode.RISK_DETERIORATION,
                    outcome=ConditionOutcome.SATISFIED,
                ),
            )
    base = _payload(signal_type, price_fen=price_fen, matched_conditions=matched)
    return AlertPayload.model_validate(
        {
            **base.model_dump(mode="python", round_trip=True),
            "satisfied_conditions": satisfied,
            "unmet_conditions": (),
        }
    )


def _sample_plan():
    document = (Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml").read_text(
        encoding="utf-8"
    )
    return load_plan_yaml(document)


def _buy_result():
    plan = _sample_plan()
    plan_hash = plan_sha256(plan)
    evidence = _satisfied_price_evidence()
    next_step = NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL)
    signal = SignalIntent(
        signal_type=ActionableSignalType.BUY_CORE_READY,
        plan_hash=plan_hash,
        symbol=plan.symbol,
        trading_date=TRADE_DATE,
        cause_id="episode-001",
        quantity=100,
        bucket="CORE",
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=next_step,
    )
    risk = RiskStateSnapshot(
        symbol=plan.symbol,
        plan_hash=plan_hash,
        status=RiskStatus.CLEAR,
        breach_trade_date=None,
        prior_close_fen=6080,
        revision=0,
        updated_at=MARKET_DATA_AT,
    )
    data_health = DataHealthSnapshot(
        symbol=plan.symbol,
        status=DataHealthStatus.LIVE,
        latest_bar_end=MARKET_DATA_AT,
        data_age_seconds=18,
        required_data_complete=True,
        fresh=True,
    )
    snapshot = SymbolDecisionSnapshot(
        symbol=plan.symbol,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_hash=plan_hash,
        evaluated_at=EVALUATED_AT,
        market_data_at=MARKET_DATA_AT,
        price_fen=6420,
        zone=DecisionZone.LOW_BUY,
        signal_type=SignalType.BUY_CORE_READY,
        position=PositionSummary(
            core_quantity=0,
            tactical_quantity=0,
            total_quantity=0,
            sellable_core_quantity=0,
            sellable_tactical_quantity=0,
        ),
        episode=None,
        risk=risk,
        data_health=data_health,
        condition_evidence=(evidence,),
        next_step=next_step,
    )
    return plan, EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=signal,
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        next_step=next_step,
        evaluation_identity=IntradayEvaluationIdentity(
            plan_hash=plan_hash,
            symbol=plan.symbol,
            bucket_end=MARKET_DATA_AT,
        ),
    )


def test_alert_identity_matches_exact_five_field_sha256_input() -> None:
    signal = _signal()
    expected_preimage = (
        f"{signal.plan_hash}|{signal.trading_date.isoformat()}|"
        f"{signal.signal_type.value}|{signal.cause_id}|100"
    )
    assert alert_dedup_key(signal) == hashlib.sha256(expected_preimage.encode("utf-8")).hexdigest()

    risk_breach = _signal(ActionableSignalType.RISK_BREACH)
    expected_risk_preimage = (
        f"{risk_breach.plan_hash}|{risk_breach.trading_date.isoformat()}|"
        f"{risk_breach.signal_type.value}|{risk_breach.cause_id}|"
    )
    assert (
        alert_dedup_key(risk_breach)
        == hashlib.sha256(expected_risk_preimage.encode("utf-8")).hexdigest()
    )
    assert alert_dedup_key(signal) == alert_dedup_key(signal.model_copy())


def test_build_alert_payload_consumes_only_validated_decision_and_plan_facts() -> None:
    plan, result = _buy_result()

    payload = build_alert_payload(event_id=EVENT_ID, plan=plan, result=result)

    assert payload.plan_id == plan.plan_id
    assert payload.plan_version == plan.version
    assert payload.plan_hash == plan_sha256(plan)
    assert payload.dedup_key == alert_dedup_key(result.signal_intent)
    assert payload.relevant_zone == AlertPriceZone(
        zone=DecisionZone.LOW_BUY,
        low_fen=6300,
        high_fen=6450,
        include_low=True,
        include_high=True,
    )
    assert payload.risk_line_fen == 6080
    assert payload.blockers == result.blockers

    non_actionable_snapshot = result.snapshot.model_copy(update={"signal_type": SignalType.WAIT})
    non_actionable_result = EvaluationResult.build(
        snapshot=non_actionable_snapshot,
        transitions=(),
        signal_intent=None,
        satisfied_conditions=result.satisfied_conditions,
        unmet_conditions=(),
        blockers=(),
        next_step=result.next_step,
        evaluation_identity=result.evaluation_identity,
    )
    with pytest.raises(ValueError, match="actionable"):
        build_alert_payload(
            event_id=EVENT_ID,
            plan=plan,
            result=non_actionable_result,
        )


def test_payload_builder_uses_the_displayed_market_fact_for_data_age() -> None:
    plan, result = _buy_result()
    earlier_market_data_at = MARKET_DATA_AT.replace(minute=20)
    stale_health = result.snapshot.data_health.model_copy(
        update={
            "status": DataHealthStatus.STALE,
            "fresh": False,
        }
    )
    stale_snapshot = result.snapshot.model_copy(
        update={
            "market_data_at": earlier_market_data_at,
            "data_health": stale_health,
        }
    )
    stale_result = EvaluationResult.build(
        snapshot=stale_snapshot,
        transitions=(),
        signal_intent=result.signal_intent,
        satisfied_conditions=result.satisfied_conditions,
        unmet_conditions=(),
        blockers=(),
        next_step=result.next_step,
        evaluation_identity=result.evaluation_identity,
    )

    payload = build_alert_payload(
        event_id=EVENT_ID,
        plan=plan,
        result=stale_result,
    )

    assert payload.market_data_at == earlier_market_data_at
    assert payload.data_age_seconds == 318


def test_payload_builder_preserves_every_result_evidence_partition() -> None:
    plan, result = _buy_result()
    pressure_touch = RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=ConditionOutcome.SATISFIED,
        facts=(EvidenceFact(key="touch_at", value=MARKET_DATA_AT, unit=EvidenceUnit.DATETIME),),
    )
    deterioration = RuleEvidence(
        code=RuleEvidenceCode.RISK_DETERIORATION,
        outcome=ConditionOutcome.UNSATISFIED,
    )
    snapshot = result.snapshot.model_copy(
        update={
            "condition_evidence": (
                *result.satisfied_conditions,
                pressure_touch,
                deterioration,
            )
        }
    )
    enriched = EvaluationResult.build(
        snapshot=snapshot,
        transitions=(),
        signal_intent=result.signal_intent,
        satisfied_conditions=(*result.satisfied_conditions, pressure_touch),
        unmet_conditions=(deterioration,),
        blockers=(),
        next_step=result.next_step,
        evaluation_identity=result.evaluation_identity,
    )

    payload = build_alert_payload(event_id=EVENT_ID, plan=plan, result=enriched)

    assert payload.satisfied_conditions == enriched.satisfied_conditions
    assert payload.unmet_conditions == enriched.unmet_conditions
    assert payload.blockers == enriched.blockers


def test_renderer_preserves_composite_grouping_outcomes_and_parent_facts() -> None:
    matched = _pressure_reduction_evidence()
    pressure_touch = RuleEvidence(
        code=RuleEvidenceCode.PRESSURE_TOUCH,
        outcome=ConditionOutcome.SATISFIED,
    )
    deterioration = RuleEvidence(
        code=RuleEvidenceCode.RISK_DETERIORATION,
        outcome=ConditionOutcome.UNSATISFIED,
    )
    blocker = RuleEvidence(
        code=RuleEvidenceCode.RISK_PENDING,
        outcome=ConditionOutcome.UNSATISFIED,
    )
    base = _payload(
        ActionableSignalType.PRESSURE_REDUCE_READY,
        matched_conditions=(matched,),
        blockers=(blocker,),
    )
    payload = AlertPayload.model_validate(
        {
            **base.model_dump(mode="python", round_trip=True),
            "satisfied_conditions": (matched, pressure_touch),
            "unmet_conditions": (deterioration,),
        }
    )

    text = render_alert(payload)

    assert (
        "信号成立：任一条件【成立】（K线数=3根）{"
        "上影线占振幅至少0.4【成立】（observed_ratio=0.5）；"
        "较当日高点回落至少0.01【缺少输入】（缺少：SESSION_BARS）}"
    ) in text
    assert "结果成立：任一条件【成立】" in text
    assert "价格已触及压力区【成立】" in text
    assert "结果未成立：风险相对原始跌破继续恶化【未成立】" in text
    assert "阻断：风险状态待确认【未成立】" in text


def test_decimal_evidence_rendering_is_scale_sign_and_context_independent() -> None:
    def payload_for(value: Decimal) -> AlertPayload:
        evidence = _satisfied_price_evidence(
            facts=(EvidenceFact(key="observed_ratio", value=value, unit=EvidenceUnit.RATIO),)
        )
        base = _payload(matched_conditions=(evidence,))
        return AlertPayload.model_validate(
            {
                **base.model_dump(mode="python", round_trip=True),
                "satisfied_conditions": (evidence,),
                "unmet_conditions": (),
            }
        )

    scaled = payload_for(Decimal("1.50"))
    canonical = payload_for(Decimal("1.5"))
    negative_zero = payload_for(Decimal("-0.000"))
    positive_zero = payload_for(Decimal("0"))

    assert render_alert(scaled) == render_alert(canonical)
    assert "observed_ratio=1.5" in render_alert(scaled)
    assert render_alert(negative_zero) == render_alert(positive_zero)

    with localcontext() as context:
        context.prec = 2
        low_precision = render_alert(scaled)
    with localcontext() as context:
        context.prec = 50
        high_precision = render_alert(scaled)
    assert low_precision == high_precision


def test_buy_core_alert_matches_the_chinese_golden_text() -> None:
    assert render_alert(_payload()) == "\n".join(
        (
            "【低吸底仓买点成立｜ACTION】华亚智能（003043.SZ）",
            "时间：2026-08-07 10:25  行情：2026-08-07 10:25（延迟18秒）",
            "价格：64.20元  建议：低吸底仓100股",
            "区间：低吸区63.00～64.50元（含下界、含上界）",
            "信号成立：价格位于低吸区【成立】（当前价=64.20元）",
            "结果成立：价格位于低吸区【成立】（当前价=64.20元）",
            "结果未成立：无",
            "阻断：无",
            "风险线：60.80元  计划：huaya-smart-v1",
            "下一步：人工确认后自行决定是否下单",
            "原因：episode-001",
            "事件：00000000-0000-0000-0000-000000000001",
            "仅提醒，不会自动下单。",
        )
    )


@pytest.mark.parametrize(
    ("signal_type", "heading", "severity", "suggestion", "next_step"),
    (
        (
            ActionableSignalType.BUY_CORE_READY,
            "低吸底仓买点成立",
            "ACTION",
            "低吸底仓100股",
            "人工确认后自行决定是否下单",
        ),
        (
            ActionableSignalType.BUY_TACTICAL_READY,
            "低吸机动仓买点成立",
            "ACTION",
            "低吸机动仓100股",
            "人工确认后自行决定是否下单",
        ),
        (
            ActionableSignalType.PRESSURE_REDUCE_READY,
            "压力位机动仓减仓条件成立",
            "RISK",
            "减仓机动仓100股",
            "人工确认后自行决定是否减仓",
        ),
        (
            ActionableSignalType.RISK_BREACH,
            "官方收盘跌破风险线",
            "RISK",
            "暂停加仓",
            "暂停加仓，等待下一交易日官方收盘",
        ),
        (
            ActionableSignalType.RISK_EXIT_READY,
            "风险退出条件成立",
            "CRITICAL",
            "卖出机动仓100股",
            "人工确认后自行决定是否减仓",
        ),
        (
            ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
            "风险退出待T+1结算",
            "CRITICAL",
            "目标机动仓100股尚不可卖",
            "等待下一交易日解禁后重新评估",
        ),
    ),
)
def test_every_actionable_signal_has_a_fixed_label_severity_and_guidance(
    signal_type: ActionableSignalType,
    heading: str,
    severity: str,
    suggestion: str,
    next_step: str,
) -> None:
    text = render_alert(_payload(signal_type))

    assert text.startswith(f"【{heading}｜{severity}】")
    assert f"建议：{suggestion}" in text
    assert f"下一步：{next_step}" in text
    assert text.endswith("仅提醒，不会自动下单。")


@pytest.mark.parametrize(
    (
        "signal_type",
        "heading",
        "suggestion",
        "zone_line",
        "signal_line",
        "result_line",
        "next_step",
    ),
    (
        (
            ActionableSignalType.BUY_CORE_READY,
            "【低吸底仓买点成立｜ACTION】华亚智能（003043.SZ）",
            "价格：64.20元  建议：低吸底仓100股",
            "区间：低吸区63.00～64.50元（含下界、含上界）",
            "信号成立：价格位于低吸区【成立】（当前价=64.20元）",
            "结果成立：价格位于低吸区【成立】（当前价=64.20元）",
            "人工确认后自行决定是否下单",
        ),
        (
            ActionableSignalType.BUY_TACTICAL_READY,
            "【低吸机动仓买点成立｜ACTION】华亚智能（003043.SZ）",
            "价格：64.20元  建议：低吸机动仓100股",
            "区间：低吸区63.00～64.50元（含下界、含上界）",
            "信号成立：价格位于低吸区【成立】（当前价=64.20元）",
            "结果成立：价格位于低吸区【成立】（当前价=64.20元）",
            "人工确认后自行决定是否下单",
        ),
        (
            ActionableSignalType.PRESSURE_REDUCE_READY,
            "【压力位机动仓减仓条件成立｜RISK】华亚智能（003043.SZ）",
            "价格：69.00元  建议：减仓机动仓100股",
            "区间：压力区68.80～70.20元（含下界、含上界）",
            (
                "信号成立：任一条件【成立】（K线数=3根）{"
                "上影线占振幅至少0.4【成立】（observed_ratio=0.5）；"
                "较当日高点回落至少0.01【缺少输入】（缺少：SESSION_BARS）}"
            ),
            (
                "结果成立：任一条件【成立】（K线数=3根）{"
                "上影线占振幅至少0.4【成立】（observed_ratio=0.5）；"
                "较当日高点回落至少0.01【缺少输入】（缺少：SESSION_BARS）}；"
                "价格已触及压力区【成立】"
            ),
            "人工确认后自行决定是否减仓",
        ),
        (
            ActionableSignalType.RISK_BREACH,
            "【官方收盘跌破风险线｜RISK】华亚智能（003043.SZ）",
            "价格：60.70元  建议：暂停加仓",
            None,
            "信号成立：官方收盘低于风险线【成立】（当前价=60.70元）",
            "结果成立：官方收盘低于风险线【成立】（当前价=60.70元）",
            "暂停加仓，等待下一交易日官方收盘",
        ),
        (
            ActionableSignalType.RISK_EXIT_READY,
            "【风险退出条件成立｜CRITICAL】华亚智能（003043.SZ）",
            "价格：60.70元  建议：卖出机动仓100股",
            None,
            "信号成立：官方收盘低于风险线【成立】（当前价=60.70元）",
            (
                "结果成立：官方收盘低于风险线【成立】（当前价=60.70元）；"
                "风险相对原始跌破继续恶化【成立】"
            ),
            "人工确认后自行决定是否减仓",
        ),
        (
            ActionableSignalType.RISK_EXIT_PENDING_SETTLEMENT,
            "【风险退出待T+1结算｜CRITICAL】华亚智能（003043.SZ）",
            "价格：60.70元  建议：目标机动仓100股尚不可卖",
            None,
            "信号成立：官方收盘低于风险线【成立】（当前价=60.70元）",
            (
                "结果成立：官方收盘低于风险线【成立】（当前价=60.70元）；"
                "风险相对原始跌破继续恶化【成立】"
            ),
            "等待下一交易日解禁后重新评估",
        ),
    ),
)
def test_every_actionable_signal_has_a_complete_exact_golden_text(
    signal_type: ActionableSignalType,
    heading: str,
    suggestion: str,
    zone_line: str | None,
    signal_line: str,
    result_line: str,
    next_step: str,
) -> None:
    payload = _contract_payload(signal_type)
    lines = [
        heading,
        "时间：2026-08-07 10:25  行情：2026-08-07 10:25（延迟18秒）",
        suggestion,
    ]
    if zone_line is not None:
        lines.append(zone_line)
    lines.extend(
        (
            signal_line,
            result_line,
            "结果未成立：无",
            "阻断：无",
            "风险线：60.80元  计划：huaya-smart-v1",
            f"下一步：{next_step}",
            (
                "原因：risk-20260807"
                if signal_type.value.startswith("RISK_")
                else "原因：episode-001"
            ),
            "事件：00000000-0000-0000-0000-000000000001",
            "仅提醒，不会自动下单。",
        )
    )

    assert render_alert(payload) == "\n".join(lines)


def test_missing_optional_market_fields_are_explicit_and_stable() -> None:
    payload = _payload(
        ActionableSignalType.RISK_BREACH,
        market_data_at=None,
        data_age_seconds=None,
        price_fen=None,
    )

    text = render_alert(payload)

    assert "行情：不可用（延迟未知）" in text
    assert "价格：不可用  建议：暂停加仓" in text
    assert "区间：" not in text
    assert text == render_alert(payload.model_copy())


def test_renderer_preserves_blockers_and_supplemental_rule_evidence() -> None:
    blocker = RuleEvidence(
        code=RuleEvidenceCode.RISK_PENDING,
        outcome=ConditionOutcome.UNSATISFIED,
        facts=(
            EvidenceFact(
                key="risk_status",
                value="RISK_PENDING",
                unit=EvidenceUnit.CODE,
            ),
        ),
    )

    text = render_alert(_payload(blockers=(blocker,)))

    assert "阻断：风险状态待确认【未成立】（风险状态=RISK_PENDING）" in text


def test_html_is_escaped_and_control_characters_are_rejected() -> None:
    payload = _payload(name="<script>alert('x')</script>")

    text = render_alert(payload)

    assert "<script>" not in text
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in text

    with pytest.raises(ValidationError, match="control"):
        _payload(name="华亚智能\n伪造标题")


@pytest.mark.parametrize("separator", ("\u2028", "\u2029", "\ud800", "\u202e"))
def test_visual_line_separators_surrogates_and_bidi_controls_are_rejected(
    separator: str,
) -> None:
    with pytest.raises(ValidationError):
        _payload(name=f"华亚{separator}伪造标题")


def test_notification_values_are_frozen_copy_revalidated_and_json_round_trip_safe() -> None:
    payload = _payload()

    with pytest.raises(ValidationError):
        payload.name = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="dedup"):
        payload.model_copy(update={"dedup_key": "b" * 64})

    assert AlertPayload.model_validate_json(payload.model_dump_json()) == payload

    message = render_alert(payload)
    event = AlertEvent(
        **payload.model_dump(mode="python", round_trip=True),
        sequence=1,
        message_text=message,
        created_at=EVALUATED_AT,
        acknowledged_at=None,
    )
    assert AlertEvent.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        event.model_copy(update={"sequence": 0})


def test_renderer_fails_closed_when_the_final_message_is_too_large() -> None:
    facts = tuple(
        EvidenceFact(
            key=f"fact_{index:04d}",
            value="X" * 64,
            unit=EvidenceUnit.CODE,
        )
        for index in range(512)
    )
    oversized_evidence = _satisfied_price_evidence(facts=facts)
    payload = _payload(matched_conditions=(oversized_evidence,))

    with pytest.raises(AlertRenderError, match="too large") as error:
        render_alert(payload)

    assert error.value.__context__ is None
    assert error.value.__cause__ is None
    assert "X" * 64 not in str(error.value)


def test_payload_rejects_excessive_total_evidence_before_rendering() -> None:
    evidence = tuple(
        _satisfied_price_evidence(
            facts=tuple(
                EvidenceFact(
                    key=f"fact_{group}_{index:03d}",
                    value=index,
                    unit=EvidenceUnit.COUNT,
                )
                for index in range(300)
            )
        )
        for group in range(2)
    )
    with pytest.raises(ValidationError, match="evidence budget"):
        _payload(matched_conditions=evidence)


def test_payload_rejects_an_unbounded_numeric_display_before_rendering() -> None:
    evidence = _satisfied_price_evidence(
        facts=(
            EvidenceFact(
                key="target_quantity",
                value=10**256,
                unit=EvidenceUnit.SHARES,
            ),
        )
    )
    with pytest.raises(ValidationError, match="numeric display"):
        _payload(matched_conditions=(evidence,))


def _delivery_event() -> AlertEvent:
    payload = _payload()
    return AlertEvent(
        **payload.model_dump(mode="python", round_trip=True),
        sequence=1,
        message_text=render_alert(payload),
        created_at=EVALUATED_AT,
        acknowledged_at=None,
    )


def test_console_channel_emits_the_stable_event_id_and_rendered_message() -> None:
    lines: list[str] = []

    result = asyncio.run(ConsoleChannel(write_line=lines.append).deliver(_delivery_event()))

    assert result.channel is DeliveryChannel.CONSOLE
    assert result.delivered is True
    assert result.retryable is False
    assert str(EVENT_ID) in lines[0]
    assert _delivery_event().message_text in lines[0]


def test_webhook_is_disabled_by_default_and_requires_an_https_allowlisted_host() -> None:
    assert WebhookConfig().enabled is False

    with pytest.raises(ValidationError, match="endpoint"):
        WebhookConfig(enabled=True, allowlisted_hosts=("hooks.example.test",))
    with pytest.raises(ValidationError, match="HTTPS"):
        WebhookConfig(
            enabled=True,
            endpoint="http://hooks.example.test/alerts",
            allowlisted_hosts=("hooks.example.test",),
        )
    with pytest.raises(ValidationError, match="allowlisted"):
        WebhookConfig(
            enabled=True,
            endpoint="https://other.example.test/alerts",
            allowlisted_hosts=("hooks.example.test",),
        )
    with pytest.raises(ValidationError):
        WebhookConfig(
            enabled=True,
            endpoint="https://hooks.example.test/alerts",
            allowlisted_hosts=("*.example.test",),
            allow_redirects=True,
        )


def test_webhook_configuration_validation_redacts_credential_and_query_inputs() -> None:
    marker = "webhook-secret-must-not-escape"
    candidates = (
        lambda: WebhookConfig(
            enabled=True,
            endpoint=f"https://user:{marker}@hooks.example.test/alerts",
            allowlisted_hosts=("hooks.example.test",),
        ),
        lambda: WebhookConfig.model_validate_json(
            json.dumps(
                {
                    "enabled": True,
                    "endpoint": f"https://hooks.example.test/alerts?token={marker}",
                    "allowlisted_hosts": ["hooks.example.test"],
                }
            )
        ),
    )

    for construct in candidates:
        with pytest.raises(ValidationError) as error_info:
            construct()
        public_error = error_info.value
        assert marker not in str(public_error)
        assert marker not in repr(public_error)
        assert marker not in repr(public_error.errors())
        assert public_error.__context__ is None
        assert public_error.__cause__ is None


def test_webhook_configuration_strict_json_preserves_array_to_tuple_conversion() -> None:
    config = WebhookConfig.model_validate_json(
        json.dumps(
            {
                "enabled": True,
                "endpoint": "https://hooks.example.test/alerts",
                "allowlisted_hosts": ["hooks.example.test"],
            }
        )
    )

    assert config.allowlisted_hosts == ("hooks.example.test",)


def test_webhook_configuration_copy_revalidates_the_security_boundary() -> None:
    disabled = WebhookConfig(
        enabled=False,
        endpoint="https://not-allowlisted.example.test/private",
        allowlisted_hosts=("hooks.example.test",),
    )

    with pytest.raises(ValidationError):
        disabled.model_copy(update={"enabled": True})
    with pytest.raises(ValidationError):
        WebhookConfig().model_copy(
            update={
                "enabled": True,
                "endpoint": "http://127.0.0.1/private",
                "allowlisted_hosts": ("127.0.0.1",),
            }
        )


def test_webhook_channel_cannot_enable_a_disabled_non_allowlisted_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    async def deliver() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            channel = WebhookChannel(
                client=client,
                config=WebhookConfig(
                    enabled=False,
                    endpoint="https://not-allowlisted.example.test/private",
                    allowlisted_hosts=("hooks.example.test",),
                ),
            )
            with pytest.raises(AttributeError):
                channel.enabled = True
            return await channel.deliver(_delivery_event())

    result = asyncio.run(deliver())

    assert result.error_code is ChannelErrorCode.WEBHOOK_DISABLED
    assert requests == []


def test_webhook_channel_revalidates_an_exact_but_untrusted_config_instance() -> None:
    forged = WebhookConfig.model_construct(
        enabled=True,
        endpoint="http://127.0.0.1/private",
        allowlisted_hosts=("127.0.0.1",),
        timeout_seconds=5,
        allow_redirects=False,
    )

    async def construct() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValidationError):
                WebhookChannel(client=client, config=forged)

    asyncio.run(construct())


def _webhook_result(status_code: int, *, response_body: str = "") -> tuple[object, bytes]:
    request_body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_body
        request_body = request.content
        return httpx.Response(status_code, text=response_body, request=request)

    async def deliver() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            channel = WebhookChannel(
                client=client,
                config=WebhookConfig(
                    enabled=True,
                    endpoint="https://hooks.example.test/alerts",
                    allowlisted_hosts=("hooks.example.test",),
                ),
            )
            return await channel.deliver(_delivery_event())

    return asyncio.run(deliver()), request_body


@pytest.mark.parametrize(
    ("status_code", "delivered", "retryable", "error_code"),
    (
        (200, True, False, None),
        (204, True, False, None),
        (400, False, False, ChannelErrorCode.WEBHOOK_REJECTED),
        (408, False, True, ChannelErrorCode.WEBHOOK_TRANSIENT),
        (429, False, True, ChannelErrorCode.WEBHOOK_TRANSIENT),
        (500, False, True, ChannelErrorCode.WEBHOOK_TRANSIENT),
    ),
)
def test_webhook_classifies_bounded_http_outcomes(
    status_code: int,
    delivered: bool,
    retryable: bool,
    error_code: ChannelErrorCode | None,
) -> None:
    result, _request_body = _webhook_result(status_code)

    assert result.channel is DeliveryChannel.WEBHOOK
    assert result.delivered is delivered
    assert result.retryable is retryable
    assert result.response_code == status_code
    assert result.error_code is error_code


def test_webhook_sends_only_the_bounded_public_alert_envelope() -> None:
    response_marker = "raw-provider-body-must-not-escape"

    result, request_body = _webhook_result(400, response_body=response_marker)
    payload = json.loads(request_body)

    assert payload == {
        "createdAt": EVALUATED_AT.isoformat(),
        "eventId": str(EVENT_ID),
        "messageText": _delivery_event().message_text,
        "sequence": 1,
        "severity": "ACTION",
        "signalType": "BUY_CORE_READY",
        "symbol": SYMBOL,
    }
    assert response_marker not in str(result)
    assert response_marker not in repr(result)


def test_webhook_rejects_redirects_without_following_them() -> None:
    result, _request_body = _webhook_result(302, response_body="redirect-secret")

    assert result.delivered is False
    assert result.retryable is False
    assert result.error_code is ChannelErrorCode.UNSAFE_REDIRECT
    assert "redirect-secret" not in repr(result)


def test_webhook_timeout_is_retryable_and_redacted() -> None:
    marker = "transport-secret-must-not-escape"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(marker, request=request)

    async def deliver() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            channel = WebhookChannel(
                client=client,
                config=WebhookConfig(
                    enabled=True,
                    endpoint="https://hooks.example.test/alerts",
                    allowlisted_hosts=("hooks.example.test",),
                ),
            )
            return await channel.deliver(_delivery_event())

    result = asyncio.run(deliver())

    assert result.delivered is False
    assert result.retryable is True
    assert result.error_code is ChannelErrorCode.WEBHOOK_TIMEOUT
    assert marker not in str(result)
    assert marker not in repr(result)
