"""Add the unified durable monitor-event ledger.

Revision ID: 0006_monitor_event
Revises: 0005_evaluation_kind
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import escape
from unicodedata import category
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision: str = "0006_monitor_event"
down_revision: str | Sequence[str] | None = "0005_evaluation_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = (
    "'symbol.snapshot.updated', "
    "'symbol.health.updated', "
    "'alert.created', "
    "'alert.acknowledged', "
    "'plan.extraction.updated', "
    "'plan.activated', "
    "'plan.deactivated', "
    "'position.updated', "
    "'ai.provider.updated', "
    "'system.health.updated'"
)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_HISTORICAL_PAYLOAD_BYTES = 4 * 1024 * 1024
_MAX_ALERT_EVIDENCE = 50
_MAX_ALERT_EVIDENCE_NODES = 250
_MAX_ALERT_FACTS = 512
_MAX_DISPLAY_NUMERIC_DIGITS = 256
_MAX_DISPLAY_INTEGER_MAGNITUDE = 10**_MAX_DISPLAY_NUMERIC_DIGITS
_MAX_ALERT_TEXT_CHARS = 16_384
_ALERT_PAYLOAD_FIELDS = frozenset(
    {
        "event_id",
        "dedup_key",
        "plan_id",
        "plan_version",
        "plan_hash",
        "symbol",
        "name",
        "signal_type",
        "severity",
        "trading_date",
        "cause_id",
        "evaluated_at",
        "market_data_at",
        "data_age_seconds",
        "price_fen",
        "quantity",
        "bucket",
        "target_lot_id",
        "matched_conditions",
        "satisfied_conditions",
        "unmet_conditions",
        "blockers",
        "zone",
        "relevant_zone",
        "risk_line_fen",
        "next_step",
    }
)
_SIGNAL_CONTRACTS = {
    "BUY_CORE_READY": ("ACTION", "CORE", False, "LOW_BUY", "RECORD_CONFIRMED_FILL"),
    "BUY_TACTICAL_READY": (
        "ACTION",
        "TACTICAL",
        False,
        "LOW_BUY",
        "RECORD_CONFIRMED_FILL",
    ),
    "PRESSURE_REDUCE_READY": (
        "RISK",
        "TACTICAL",
        True,
        "PRESSURE",
        "RECORD_CONFIRMED_FILL",
    ),
    "RISK_BREACH": ("RISK", None, False, "BELOW_RISK", "WAIT_FOR_NEXT_TRADING_DAY"),
    "RISK_EXIT_READY": ("CRITICAL", "LOT", True, "BELOW_RISK", "RECORD_CONFIRMED_FILL"),
    "RISK_EXIT_PENDING_SETTLEMENT": (
        "CRITICAL",
        "LOT",
        True,
        "BELOW_RISK",
        "WAIT_FOR_SETTLEMENT",
    ),
}
_CONDITION_FIELDS = {
    "PRICE_IN_ZONE": frozenset({"type", "zone"}),
    "NO_NEW_LOW_FOR_BARS": frozenset({"type", "bars"}),
    "NON_DECREASING_CLOSE": frozenset({"type"}),
    "VOLUME_TO_PREVIOUS_LTE": frozenset({"type", "max_ratio"}),
    "VOLUME_TO_MEDIAN_LTE": frozenset({"type", "max_ratio", "window_bars"}),
    "VOLUME_TO_MEDIAN_GTE": frozenset({"type", "minimum_ratio", "window_bars"}),
    "MACD_HIST_IMPROVEMENT_GTE": frozenset({"type", "minimum_improvement"}),
    "PRICE_RECLAIMS_INDICATOR": frozenset({"type", "indicator"}),
    "UPPER_WICK_RATIO_GTE": frozenset({"type", "minimum_ratio"}),
    "RETREAT_FROM_SESSION_HIGH_GTE": frozenset({"type", "minimum_ratio"}),
    "CLOSE_IN_BAR_LOWER_HALF": frozenset({"type"}),
    "CONSECUTIVE_CLOSES_BELOW_LEVEL": frozenset({"type", "level", "bars"}),
    "OFFICIAL_CLOSE_BELOW_LEVEL": frozenset({"type", "level"}),
    "NEXT_TRADING_DAY_RECOVERY": frozenset({"type", "level"}),
    "POSITION_BUCKET_AVAILABLE": frozenset({"type", "bucket"}),
    "SELLABLE_QUANTITY_GTE": frozenset({"type", "bucket", "quantity"}),
    "MANUAL_EVENT_RISK_CLEAR": frozenset({"type"}),
    "DISTANCE_FROM_LIMIT_DOWN_GTE": frozenset({"type", "minimum_ratio"}),
    "LOWER_BAND_HITS_LTE": frozenset({"type", "max_hits", "window_bars"}),
    "ALL": frozenset({"type", "conditions"}),
    "ANY": frozenset({"type", "conditions"}),
}
_EVIDENCE_FIELDS = frozenset({"condition", "outcome", "facts", "missing_inputs", "children"})
_RULE_EVIDENCE_FIELDS = frozenset({"code", "outcome", "facts", "missing_inputs"})
_FACT_FIELDS = frozenset({"key", "value", "unit"})
_OUTCOMES = frozenset({"SATISFIED", "UNSATISFIED", "MISSING_INPUT"})
_EVIDENCE_UNITS = frozenset(
    {"FEN", "SHARES", "RATIO", "BARS", "YUAN", "COUNT", "BOOLEAN", "DATE", "DATETIME", "CODE"}
)
_MISSING_INPUT_CODES = frozenset(
    {
        "COMPLETE_MINUTE_BAR",
        "PREVIOUS_MINUTE_BAR",
        "COMPLETE_5M_BAR",
        "PREVIOUS_5M_BAR",
        "COMPLETE_5M_BAR_WINDOW",
        "ROLLING_VOLUME_WINDOW",
        "SESSION_BARS",
        "DAILY_INDICATORS",
        "PROVISIONAL_DAILY_BAR",
        "FIVE_MINUTE_INDICATORS",
        "INDICATOR_VALUE",
        "OFFICIAL_DAILY_CLOSE",
        "TRADING_CALENDAR",
        "DAILY_LIMIT",
        "MANUAL_EVENT_RISK",
    }
)
_RULE_EVIDENCE_CODES = frozenset(
    {
        "PLAN_INACTIVE",
        "DATA_NOT_READY",
        "DAILY_LIMIT_UNKNOWN",
        "EPISODE_HISTORY_GAP",
        "BEARISH_VOLUME_EXPANSION",
        "RISK_PENDING",
        "PRESSURE_TOUCH",
        "RISK_RECOVERY",
        "RISK_DETERIORATION",
    }
)
_STRUCTURAL_RULE_EVIDENCE_CODES = frozenset(
    {
        "PLAN_INACTIVE",
        "DATA_NOT_READY",
        "DAILY_LIMIT_UNKNOWN",
        "EPISODE_HISTORY_GAP",
        "BEARISH_VOLUME_EXPANSION",
        "RISK_PENDING",
    }
)
_SIGNAL_LABELS = {
    "BUY_CORE_READY": "低吸底仓买点成立",
    "BUY_TACTICAL_READY": "低吸机动仓买点成立",
    "PRESSURE_REDUCE_READY": "压力位机动仓减仓条件成立",
    "RISK_BREACH": "官方收盘跌破风险线",
    "RISK_EXIT_READY": "风险退出条件成立",
    "RISK_EXIT_PENDING_SETTLEMENT": "风险退出待T+1结算",
}
_NEXT_STEP_LABELS = {
    "BUY_CORE_READY": "人工确认后自行决定是否下单",
    "BUY_TACTICAL_READY": "人工确认后自行决定是否下单",
    "PRESSURE_REDUCE_READY": "人工确认后自行决定是否减仓",
    "RISK_BREACH": "暂停加仓，等待下一交易日官方收盘",
    "RISK_EXIT_READY": "人工确认后自行决定是否减仓",
    "RISK_EXIT_PENDING_SETTLEMENT": "等待下一交易日解禁后重新评估",
}
_ZONE_LABELS = {"LOW_BUY": "低吸区", "PRESSURE": "压力区"}
_RULE_LABELS = {
    "PLAN_INACTIVE": "计划未激活",
    "DATA_NOT_READY": "所需行情未就绪",
    "DAILY_LIMIT_UNKNOWN": "当日涨跌停价未知",
    "EPISODE_HISTORY_GAP": "事件历史存在缺口",
    "BEARISH_VOLUME_EXPANSION": "阴线成交量异常放大",
    "RISK_PENDING": "风险状态待确认",
    "PRESSURE_TOUCH": "价格已触及压力区",
    "RISK_RECOVERY": "官方收盘已收回风险线",
    "RISK_DETERIORATION": "风险相对原始跌破继续恶化",
}
_FACT_LABELS = {
    "current_price_fen": "当前价",
    "risk_status": "风险状态",
    "price_fen": "价格",
    "quantity": "数量",
    "target_quantity": "目标数量",
    "volume_shares": "成交量",
    "bar_count": "K线数",
    "touch_at": "触价时间",
}
_OUTCOME_LABELS = {"SATISFIED": "成立", "UNSATISFIED": "未成立", "MISSING_INPUT": "缺少输入"}
_STABLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_PERSISTED_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_A_SHARE_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_EVIDENCE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def upgrade() -> None:
    connection = op.get_bind()
    _validate_historical_alerts(connection)
    op.create_table(
        "monitor_sequence",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_monitor_sequence_singleton"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_monitor_sequence_nonnegative"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO monitor_sequence (singleton_id, last_sequence) "
            "SELECT singleton_id, last_sequence FROM alert_sequence"
        )
    )
    op.drop_table("alert_sequence")
    op.create_table(
        "monitor_event",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("sequence", name="uq_monitor_event_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_monitor_event_sequence_positive"),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="ck_monitor_event_type",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_monitor_event_schema_version"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO monitor_event "
            "(id, sequence, event_type, schema_version, aggregate_id, payload_json, occurred_at) "
            "SELECT id, sequence, 'alert.created', 1, id, "
            "json_object('entityId', id, 'revision', 0, "
            "'symbol', json_extract(payload_json, '$.symbol')), created_at FROM alert_event"
        )
    )


def _validate_historical_alerts(connection: sa.Connection) -> None:
    high_water = connection.execute(
        sa.text("SELECT last_sequence FROM alert_sequence WHERE singleton_id = 1")
    ).scalar_one_or_none()
    maximum_sequence = connection.execute(
        sa.text("SELECT MAX(sequence) FROM alert_event")
    ).scalar_one_or_none()
    invalid = (
        type(high_water) is not int
        or high_water < 0
        or (
            maximum_sequence is not None
            and (type(maximum_sequence) is not int or maximum_sequence > high_water)
        )
    )
    rows = connection.execute(
        sa.text(
            "SELECT id, sequence, dedup_key, payload_json, message_text, created_at, "
            "acknowledged_at FROM alert_event ORDER BY sequence"
        )
    ).mappings()
    for row in rows:
        if invalid:
            break
        try:
            _validate_historical_alert_row(row)
        except TypeError, ValueError, UnicodeError, OverflowError, RecursionError:
            invalid = True
        if invalid:
            break
    if invalid:
        raise RuntimeError("0006_monitor_event refuses invalid historical alert payloads")


def _validate_historical_alert_row(row: sa.RowMapping) -> None:
    payload_json = row["payload_json"]
    if type(payload_json) is not str:
        raise ValueError("invalid payload")
    if len(payload_json.encode("utf-8")) > _MAX_HISTORICAL_PAYLOAD_BYTES:
        raise ValueError("invalid payload")
    payload = json.loads(
        payload_json,
        parse_float=Decimal,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_unique_json_object,
    )
    if type(payload) is not dict or frozenset(payload) != _ALERT_PAYLOAD_FIELDS:
        raise ValueError("invalid payload")

    event_id = _canonical_uuid(payload["event_id"])
    if row["id"] != event_id:
        raise ValueError("invalid identity")
    sequence = row["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ValueError("invalid sequence")

    plan_hash = _bounded_string(payload["plan_hash"], 64, 64, pattern=_SHA256)
    trading_date = _canonical_date(payload["trading_date"])
    signal_type = _bounded_string(payload["signal_type"], 1, 64)
    signal_contract = _SIGNAL_CONTRACTS.get(signal_type)
    if signal_contract is None:
        raise ValueError("invalid signal")
    cause_id = _bounded_string(
        payload["cause_id"],
        1,
        128,
        pattern=_STABLE_IDENTIFIER,
    )
    quantity = _optional_positive_board_lot(payload["quantity"])
    expected_dedup = sha256(
        "|".join(
            (
                plan_hash,
                trading_date,
                signal_type,
                cause_id,
                "" if quantity is None else str(quantity),
            )
        ).encode("utf-8")
    ).hexdigest()
    dedup_key = _bounded_string(payload["dedup_key"], 64, 64, pattern=_SHA256)
    if dedup_key != expected_dedup or row["dedup_key"] != dedup_key:
        raise ValueError("invalid dedup identity")

    plan_id = _bounded_string(payload["plan_id"], 1, 128, pattern=_STABLE_IDENTIFIER)
    plan_version = payload["plan_version"]
    if type(plan_version) is not int or plan_version < 1:
        raise ValueError("invalid plan version")
    symbol = _bounded_string(payload["symbol"], 9, 9, pattern=_A_SHARE_SYMBOL)
    name = _bounded_string(payload["name"], 1, 100)
    if _contains_disallowed_text(name):
        raise ValueError("invalid name")

    severity, expected_bucket, target_required, expected_zone, expected_next_step = signal_contract
    if payload["severity"] != severity or payload["zone"] != expected_zone:
        raise ValueError("invalid signal projection")
    bucket = payload["bucket"]
    if expected_bucket == "LOT":
        if bucket not in {"CORE", "TACTICAL"}:
            raise ValueError("invalid bucket")
    elif bucket != expected_bucket:
        raise ValueError("invalid bucket")
    if (quantity is None) != (expected_bucket is None):
        raise ValueError("invalid quantity")
    target_lot_id = payload["target_lot_id"]
    if target_required:
        _bounded_string(target_lot_id, 1, 36, pattern=_PERSISTED_IDENTIFIER)
    elif target_lot_id is not None:
        raise ValueError("invalid target lot")

    evaluated_at = _shanghai_datetime(payload["evaluated_at"])
    market_data_at = payload["market_data_at"]
    data_age_seconds = payload["data_age_seconds"]
    price_fen = payload["price_fen"]
    market_values = (market_data_at, data_age_seconds, price_fen)
    if any(value is None for value in market_values) != all(
        value is None for value in market_values
    ):
        raise ValueError("invalid market projection")
    if market_data_at is not None:
        normalized_market_at = _shanghai_datetime(market_data_at)
        if type(data_age_seconds) is not int or data_age_seconds < 0:
            raise ValueError("invalid market age")
        _validate_display_number(data_age_seconds)
        if type(price_fen) is not int or price_fen < 1:
            raise ValueError("invalid price")
        if normalized_market_at > evaluated_at:
            raise ValueError("invalid market time")
        if evaluated_at - normalized_market_at != timedelta(seconds=data_age_seconds):
            raise ValueError("invalid market age")

    matched_conditions = _validate_evidence_list(
        payload["matched_conditions"],
        minimum=1,
        condition_only=True,
    )
    evidence_budget = [0, 0]
    satisfied_conditions = _validate_evidence_list(
        payload["satisfied_conditions"],
        budget=evidence_budget,
    )
    unmet_conditions = _validate_evidence_list(
        payload["unmet_conditions"],
        budget=evidence_budget,
    )
    blockers = _validate_evidence_list(payload["blockers"], budget=evidence_budget)
    if any(item["outcome"] != "SATISFIED" for item in matched_conditions):
        raise ValueError("invalid matched evidence")
    if any(item["outcome"] != "SATISFIED" for item in satisfied_conditions):
        raise ValueError("invalid satisfied evidence")
    if any(item["outcome"] == "SATISFIED" for item in (*unmet_conditions, *blockers)):
        raise ValueError("invalid non-satisfied evidence")
    if any(item not in satisfied_conditions for item in matched_conditions):
        raise ValueError("invalid matched evidence")
    relevant_zone = _validate_relevant_zone(payload["relevant_zone"], expected_zone)
    risk_line_fen = payload["risk_line_fen"]
    if risk_line_fen is not None and (type(risk_line_fen) is not int or risk_line_fen < 1):
        raise ValueError("invalid risk line")
    _validate_next_step(payload["next_step"], expected_next_step)

    rendered_integers = (
        plan_version,
        data_age_seconds,
        price_fen,
        quantity,
        risk_line_fen,
        relevant_zone["low_fen"] if relevant_zone is not None else None,
        relevant_zone["high_fen"] if relevant_zone is not None else None,
    )
    if any(
        value is not None and abs(value) >= _MAX_DISPLAY_INTEGER_MAGNITUDE
        for value in rendered_integers
    ):
        raise ValueError("invalid numeric display")

    message_text = row["message_text"]
    if (
        type(message_text) is not str
        or not 1 <= len(message_text) <= 16_384
        or _contains_disallowed_text(message_text, allow_newline=True)
    ):
        raise ValueError("invalid message")
    rendered_message = _render_historical_alert(
        event_id=event_id,
        plan_id=plan_id,
        plan_version=plan_version,
        symbol=symbol,
        name=name,
        signal_type=signal_type,
        severity=severity,
        evaluated_at=evaluated_at,
        market_data_at=(None if market_data_at is None else _shanghai_datetime(market_data_at)),
        data_age_seconds=data_age_seconds,
        price_fen=price_fen,
        quantity=quantity,
        bucket=bucket,
        matched_conditions=matched_conditions,
        satisfied_conditions=satisfied_conditions,
        unmet_conditions=unmet_conditions,
        blockers=blockers,
        relevant_zone=relevant_zone,
        risk_line_fen=risk_line_fen,
        cause_id=cause_id,
    )
    if message_text != rendered_message:
        raise ValueError("invalid deterministic message")
    created_at = _shanghai_datetime(row["created_at"])
    if created_at < evaluated_at:
        raise ValueError("invalid creation time")
    if row["acknowledged_at"] is not None:
        acknowledged_at = _shanghai_datetime(row["acknowledged_at"])
        if acknowledged_at < created_at:
            raise ValueError("invalid acknowledgement time")


def _reject_json_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _bounded_string(
    value: object,
    minimum: int,
    maximum: int,
    *,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value) <= maximum
        or (pattern is not None and pattern.fullmatch(value) is None)
    ):
        raise ValueError("invalid string")
    return value


def _canonical_uuid(value: object) -> str:
    normalized = _bounded_string(value, 36, 36)
    parsed = UUID(normalized)
    if str(parsed) != normalized:
        raise ValueError("invalid UUID")
    return normalized


def _canonical_date(value: object) -> str:
    normalized = _bounded_string(value, 10, 10)
    parsed = date.fromisoformat(normalized)
    if parsed.isoformat() != normalized:
        raise ValueError("invalid date")
    return normalized


def _shanghai_datetime(value: object) -> datetime:
    normalized = _bounded_string(value, 25, 40)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid timestamp")
    shanghai_value = parsed.astimezone(_SHANGHAI)
    if parsed.utcoffset() != shanghai_value.utcoffset() or parsed.isoformat() != normalized:
        raise ValueError("invalid timestamp")
    return shanghai_value


def _optional_positive_board_lot(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 1 or value % 100:
        raise ValueError("invalid board lot")
    return value


def _validate_evidence_list(
    value: object,
    *,
    minimum: int = 0,
    condition_only: bool = False,
    budget: list[int] | None = None,
) -> list[dict[str, object]]:
    if type(value) is not list or not minimum <= len(value) <= _MAX_ALERT_EVIDENCE:
        raise ValueError("invalid evidence")
    return [
        _validate_evidence(item, condition_only=condition_only, budget=budget) for item in value
    ]


def _validate_evidence(
    value: object,
    *,
    condition_only: bool = False,
    budget: list[int] | None = None,
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("invalid evidence")
    if "condition" in value:
        return _validate_condition_evidence(value, budget=budget)
    if condition_only or "code" not in value:
        raise ValueError("invalid evidence")
    return _validate_rule_evidence(value, budget=budget)


def _validate_condition_evidence(
    value: dict[str, object],
    *,
    budget: list[int] | None,
) -> dict[str, object]:
    if frozenset(value) != _EVIDENCE_FIELDS:
        raise ValueError("invalid condition evidence")
    _consume_evidence_budget(budget, nodes=1)
    condition = _validate_condition(value["condition"])
    outcome = value["outcome"]
    if outcome not in _OUTCOMES:
        raise ValueError("invalid evidence outcome")
    facts = _validate_facts(value["facts"], maximum=512, budget=budget)
    missing_inputs = _validate_missing_inputs(value["missing_inputs"], maximum=16)
    children_value = value["children"]
    if type(children_value) is not list or len(children_value) > _MAX_ALERT_EVIDENCE:
        raise ValueError("invalid evidence children")
    children = [
        _validate_evidence(child, condition_only=True, budget=budget) for child in children_value
    ]

    condition_type = condition["type"]
    if condition_type in {"ALL", "ANY"}:
        conditions = condition["conditions"]
        if len(children) != len(conditions) or any(
            child["condition"] != expected
            for child, expected in zip(children, conditions, strict=True)
        ):
            raise ValueError("invalid logical evidence")
        child_outcomes = tuple(child["outcome"] for child in children)
        if condition_type == "ALL":
            expected_outcome = (
                "UNSATISFIED"
                if "UNSATISFIED" in child_outcomes
                else "MISSING_INPUT"
                if "MISSING_INPUT" in child_outcomes
                else "SATISFIED"
            )
        else:
            expected_outcome = (
                "SATISFIED"
                if "SATISFIED" in child_outcomes
                else "MISSING_INPUT"
                if "MISSING_INPUT" in child_outcomes
                else "UNSATISFIED"
            )
        if outcome != expected_outcome:
            raise ValueError("invalid logical outcome")
    elif children:
        raise ValueError("invalid leaf evidence")

    child_is_missing = any(child["outcome"] == "MISSING_INPUT" for child in children)
    if outcome == "MISSING_INPUT":
        if not missing_inputs and not child_is_missing:
            raise ValueError("invalid missing evidence")
    elif missing_inputs:
        raise ValueError("invalid evidence inputs")
    return {
        "kind": "condition",
        "condition": condition,
        "outcome": outcome,
        "facts": facts,
        "missing_inputs": missing_inputs,
        "children": children,
    }


def _validate_rule_evidence(
    value: dict[str, object],
    *,
    budget: list[int] | None,
) -> dict[str, object]:
    if frozenset(value) != _RULE_EVIDENCE_FIELDS:
        raise ValueError("invalid rule evidence")
    _consume_evidence_budget(budget, nodes=1)
    code = value["code"]
    outcome = value["outcome"]
    if code not in _RULE_EVIDENCE_CODES or outcome not in _OUTCOMES:
        raise ValueError("invalid rule evidence")
    facts = _validate_facts(value["facts"], maximum=16, budget=budget)
    missing_inputs = _validate_missing_inputs(value["missing_inputs"], maximum=4)
    if code in _STRUCTURAL_RULE_EVIDENCE_CODES and outcome == "SATISFIED":
        raise ValueError("invalid structural evidence")
    if outcome == "MISSING_INPUT":
        if not missing_inputs:
            raise ValueError("invalid missing rule evidence")
    elif missing_inputs:
        raise ValueError("invalid rule evidence inputs")
    return {
        "kind": "rule",
        "code": code,
        "outcome": outcome,
        "facts": facts,
        "missing_inputs": missing_inputs,
    }


def _consume_evidence_budget(
    budget: list[int] | None,
    *,
    nodes: int = 0,
    facts: int = 0,
) -> None:
    if budget is None:
        return
    budget[0] += nodes
    budget[1] += facts
    if budget[0] > _MAX_ALERT_EVIDENCE_NODES or budget[1] > _MAX_ALERT_FACTS:
        raise ValueError("invalid evidence budget")


def _validate_facts(
    value: object,
    *,
    maximum: int,
    budget: list[int] | None,
) -> list[dict[str, object]]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError("invalid evidence facts")
    _consume_evidence_budget(budget, facts=len(value))
    facts = [_validate_fact(item) for item in value]
    keys = tuple(fact["key"] for fact in facts)
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate evidence fact")
    return facts


def _validate_fact(value: object) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != _FACT_FIELDS:
        raise ValueError("invalid evidence fact")
    key = _bounded_string(value["key"], 1, 64, pattern=_EVIDENCE_KEY)
    unit = value["unit"]
    if unit not in _EVIDENCE_UNITS:
        raise ValueError("invalid evidence unit")
    raw = value["value"]
    if unit == "CODE":
        normalized = _bounded_string(raw, 1, 64, pattern=_EVIDENCE_CODE)
    elif unit == "BOOLEAN":
        if type(raw) is not bool:
            raise ValueError("invalid boolean evidence")
        normalized = raw
    elif unit == "DATE":
        normalized = date.fromisoformat(_canonical_date(raw))
    elif unit == "DATETIME":
        normalized = _shanghai_datetime(raw)
    elif unit in {"RATIO", "YUAN"}:
        normalized = _evidence_decimal(raw)
    elif unit in {"FEN", "BARS", "COUNT"}:
        if type(raw) is not int:
            raise ValueError("invalid integer evidence")
        normalized = raw
    else:
        if type(raw) is int:
            normalized = raw
        else:
            normalized = _evidence_decimal(raw)
    _validate_display_number(normalized)
    return {"key": key, "value": normalized, "unit": unit}


def _evidence_decimal(value: object) -> Decimal:
    if type(value) is int or type(value) is bool:
        raise ValueError("invalid decimal evidence")
    if isinstance(value, Decimal):
        normalized = value
    elif type(value) is str:
        try:
            normalized = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid decimal evidence") from None
    else:
        raise ValueError("invalid decimal evidence")
    if not normalized.is_finite():
        raise ValueError("invalid decimal evidence")
    return normalized


def _validate_display_number(value: object) -> None:
    if type(value) is int and abs(value) >= _MAX_DISPLAY_INTEGER_MAGNITUDE:
        raise ValueError("invalid numeric display")
    if isinstance(value, Decimal) and len(value.as_tuple().digits) > _MAX_DISPLAY_NUMERIC_DIGITS:
        raise ValueError("invalid numeric display")


def _validate_missing_inputs(value: object, *, maximum: int) -> list[str]:
    if (
        type(value) is not list
        or len(value) > maximum
        or any(item not in _MISSING_INPUT_CODES for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("invalid missing inputs")
    return value


def _validate_condition(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("invalid condition")
    condition_type = value.get("type")
    expected_fields = _CONDITION_FIELDS.get(condition_type)
    if expected_fields is None or frozenset(value) != expected_fields:
        raise ValueError("invalid condition")
    normalized = dict(value)

    if condition_type == "PRICE_IN_ZONE":
        if value["zone"] not in _ZONE_LABELS:
            raise ValueError("invalid condition zone")
    elif condition_type in {
        "NO_NEW_LOW_FOR_BARS",
        "VOLUME_TO_MEDIAN_LTE",
        "VOLUME_TO_MEDIAN_GTE",
        "CONSECUTIVE_CLOSES_BELOW_LEVEL",
    }:
        _bounded_condition_integer(value.get("bars", value.get("window_bars")), 1, 500)
    elif condition_type in {
        "VOLUME_TO_PREVIOUS_LTE",
        "VOLUME_TO_MEDIAN_LTE",
    }:
        normalized["max_ratio"] = _bounded_condition_decimal(value["max_ratio"], Decimal("10"))
    elif condition_type == "VOLUME_TO_MEDIAN_GTE":
        normalized["minimum_ratio"] = _bounded_condition_decimal(
            value["minimum_ratio"], Decimal("10")
        )
    elif condition_type == "MACD_HIST_IMPROVEMENT_GTE":
        normalized["minimum_improvement"] = _bounded_condition_decimal(
            value["minimum_improvement"], Decimal("100")
        )
    elif condition_type in {
        "UPPER_WICK_RATIO_GTE",
        "RETREAT_FROM_SESSION_HIGH_GTE",
        "DISTANCE_FROM_LIMIT_DOWN_GTE",
    }:
        normalized["minimum_ratio"] = _bounded_condition_decimal(
            value["minimum_ratio"], Decimal("1")
        )
    elif condition_type == "PRICE_RECLAIMS_INDICATOR":
        if value["indicator"] not in {"EMA10", "MA20", "MA50", "MA200", "BOLL_MIDDLE"}:
            raise ValueError("invalid condition indicator")
    elif condition_type == "CONSECUTIVE_CLOSES_BELOW_LEVEL":
        if value["level"] != "PRESSURE_REFERENCE":
            raise ValueError("invalid pressure level")
    elif condition_type in {"OFFICIAL_CLOSE_BELOW_LEVEL", "NEXT_TRADING_DAY_RECOVERY"}:
        if value["level"] != "RISK_LINE":
            raise ValueError("invalid risk level")
    elif condition_type == "POSITION_BUCKET_AVAILABLE":
        if value["bucket"] not in {"CORE", "TACTICAL"}:
            raise ValueError("invalid position bucket")
    elif condition_type == "SELLABLE_QUANTITY_GTE":
        if value["bucket"] not in {"CORE", "TACTICAL"}:
            raise ValueError("invalid position bucket")
        _positive_board_lot(value["quantity"])
    elif condition_type == "LOWER_BAND_HITS_LTE":
        max_hits = _bounded_condition_integer(value["max_hits"], 0, 500)
        window_bars = _bounded_condition_integer(value["window_bars"], 1, 500)
        if max_hits > window_bars:
            raise ValueError("invalid lower-band condition")
    elif condition_type in {"ALL", "ANY"}:
        conditions = value["conditions"]
        if type(conditions) is not list or not 1 <= len(conditions) <= 50:
            raise ValueError("invalid logical condition")
        normalized["conditions"] = [_validate_condition(item) for item in conditions]

    if condition_type == "VOLUME_TO_MEDIAN_LTE":
        normalized["max_ratio"] = _bounded_condition_decimal(value["max_ratio"], Decimal("10"))
    elif condition_type == "VOLUME_TO_MEDIAN_GTE":
        normalized["minimum_ratio"] = _bounded_condition_decimal(
            value["minimum_ratio"], Decimal("10")
        )
    if condition_type == "CONSECUTIVE_CLOSES_BELOW_LEVEL" and value["level"] != (
        "PRESSURE_REFERENCE"
    ):
        raise ValueError("invalid pressure level")
    return normalized


def _bounded_condition_integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid condition integer")
    return value


def _positive_board_lot(value: object) -> int:
    if type(value) is not int or value < 1 or value % 100:
        raise ValueError("invalid board lot")
    return value


def _bounded_condition_decimal(value: object, maximum: Decimal) -> Decimal:
    if isinstance(value, Decimal):
        normalized = value
    elif type(value) in {str, int}:
        try:
            normalized = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid condition decimal") from None
    else:
        raise ValueError("invalid condition decimal")
    if not normalized.is_finite() or normalized <= 0 or normalized > maximum:
        raise ValueError("invalid condition decimal")
    _validate_display_number(normalized)
    return normalized


def _validate_relevant_zone(value: object, expected_zone: str) -> dict[str, object] | None:
    if expected_zone not in {"LOW_BUY", "PRESSURE"}:
        if value is not None:
            raise ValueError("invalid relevant zone")
        return None
    if type(value) is not dict or frozenset(value) != {
        "zone",
        "low_fen",
        "high_fen",
        "include_low",
        "include_high",
    }:
        raise ValueError("invalid relevant zone")
    if value["zone"] != expected_zone:
        raise ValueError("invalid relevant zone")
    low_fen = value["low_fen"]
    high_fen = value["high_fen"]
    if (
        type(low_fen) is not int
        or type(high_fen) is not int
        or low_fen < 1
        or high_fen < low_fen
        or type(value["include_low"]) is not bool
        or type(value["include_high"]) is not bool
    ):
        raise ValueError("invalid relevant zone")
    return value


def _validate_next_step(value: object, expected_code: str) -> None:
    if type(value) is not dict or frozenset(value) != {
        "code",
        "not_before",
        "required_inputs",
    }:
        raise ValueError("invalid next step")
    if value["code"] != expected_code:
        raise ValueError("invalid next step")
    not_before = value["not_before"]
    if not_before is not None:
        normalized = _bounded_string(not_before, 10, 40)
        if len(normalized) == 10:
            _canonical_date(normalized)
        else:
            _shanghai_datetime(normalized)
    required_inputs = value["required_inputs"]
    if (
        type(required_inputs) is not list
        or len(required_inputs) > 16
        or any(item not in _MISSING_INPUT_CODES for item in required_inputs)
        or len(set(required_inputs)) != len(required_inputs)
    ):
        raise ValueError("invalid next step")


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("invalid decimal")
    sign, digits, exponent = value.as_tuple()
    if not any(digits):
        return "0"
    if not isinstance(exponent, int):
        raise ValueError("invalid decimal")
    end = len(digits)
    normalized_exponent = exponent
    while digits[end - 1] == 0:
        end -= 1
        normalized_exponent += 1
    coefficient = "".join(str(digit) for digit in digits[:end])
    prefix = "-" if sign else ""
    decimal_point = len(coefficient) + normalized_exponent
    if normalized_exponent >= 0 and decimal_point <= 256:
        return f"{prefix}{coefficient}{'0' * normalized_exponent}"
    if 0 < decimal_point <= 256:
        return f"{prefix}{coefficient[:decimal_point]}.{coefficient[decimal_point:]}"
    if -16 < decimal_point <= 0:
        return f"{prefix}0.{'0' * -decimal_point}{coefficient}"
    mantissa = coefficient[0]
    if len(coefficient) > 1:
        mantissa += f".{coefficient[1:]}"
    scientific_exponent = normalized_exponent + len(coefficient) - 1
    return f"{prefix}{mantissa}e{scientific_exponent}"


def _fen_text(value: int) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    return f"{sign}{absolute // 100}.{absolute % 100:02d}元"


def _fact_value(fact: dict[str, object]) -> str:
    value = fact["value"]
    unit = fact["unit"]
    if unit == "FEN":
        return _fen_text(value)
    if unit == "SHARES":
        return f"{_decimal_text(value) if isinstance(value, Decimal) else value}股"
    if unit == "RATIO":
        return _decimal_text(value)
    if unit == "BARS":
        return f"{value}根"
    if unit == "YUAN":
        return f"{_decimal_text(value)}元"
    if unit == "COUNT":
        return f"{value}个"
    if unit == "BOOLEAN":
        return "是" if value else "否"
    if unit == "DATE":
        return value.isoformat()
    if unit == "DATETIME":
        return value.strftime("%Y-%m-%d %H:%M")
    return escape(str(value), quote=True)


def _condition_label(condition: dict[str, object]) -> str:
    condition_type = condition["type"]
    if condition_type == "PRICE_IN_ZONE":
        return f"价格位于{_ZONE_LABELS[condition['zone']]}"
    if condition_type == "NO_NEW_LOW_FOR_BARS":
        return f"连续{condition['bars']}根5分钟K线未创新低"
    if condition_type == "NON_DECREASING_CLOSE":
        return "最新5分钟收盘不低于前一根"
    if condition_type == "VOLUME_TO_PREVIOUS_LTE":
        return f"成交量不高于前一根的{_decimal_text(condition['max_ratio'])}倍"
    if condition_type == "VOLUME_TO_MEDIAN_LTE":
        return (
            f"成交量不高于前{condition['window_bars']}根中位数的"
            f"{_decimal_text(condition['max_ratio'])}倍"
        )
    if condition_type == "VOLUME_TO_MEDIAN_GTE":
        return (
            f"成交量达到前{condition['window_bars']}根中位数的"
            f"{_decimal_text(condition['minimum_ratio'])}倍"
        )
    if condition_type == "MACD_HIST_IMPROVEMENT_GTE":
        return f"MACD柱改善至少{_decimal_text(condition['minimum_improvement'])}"
    if condition_type == "PRICE_RECLAIMS_INDICATOR":
        return f"价格重新站上{condition['indicator']}"
    if condition_type == "UPPER_WICK_RATIO_GTE":
        return f"上影线占振幅至少{_decimal_text(condition['minimum_ratio'])}"
    if condition_type == "RETREAT_FROM_SESSION_HIGH_GTE":
        return f"较当日高点回落至少{_decimal_text(condition['minimum_ratio'])}"
    if condition_type == "CLOSE_IN_BAR_LOWER_HALF":
        return "收盘位于K线下半部"
    if condition_type == "CONSECUTIVE_CLOSES_BELOW_LEVEL":
        return f"连续{condition['bars']}根收盘低于压力参考位"
    if condition_type == "OFFICIAL_CLOSE_BELOW_LEVEL":
        return "官方收盘低于风险线"
    if condition_type == "NEXT_TRADING_DAY_RECOVERY":
        return "后续交易日收回风险线"
    if condition_type == "POSITION_BUCKET_AVAILABLE":
        return f"{condition['bucket']}仓位可用"
    if condition_type == "SELLABLE_QUANTITY_GTE":
        return f"{condition['bucket']}可卖数量不少于{condition['quantity']}股"
    if condition_type == "MANUAL_EVENT_RISK_CLEAR":
        return "人工事件风险标记已清除"
    if condition_type == "DISTANCE_FROM_LIMIT_DOWN_GTE":
        return f"距跌停价至少{_decimal_text(condition['minimum_ratio'])}"
    if condition_type == "LOWER_BAND_HITS_LTE":
        return f"前{condition['window_bars']}根下轨命中不超过{condition['max_hits']}次"
    return "全部条件" if condition_type == "ALL" else "任一条件"


def _evidence_text(evidence: dict[str, object]) -> str:
    if evidence["kind"] == "rule":
        label = _RULE_LABELS[evidence["code"]]
    else:
        label = _condition_label(evidence["condition"])
    parts = [label, f"【{_OUTCOME_LABELS[evidence['outcome']]}】"]
    facts = evidence["facts"]
    if facts:
        parts.extend(
            (
                "（",
                "；".join(
                    f"{_FACT_LABELS.get(fact['key'], fact['key'])}={_fact_value(fact)}"
                    for fact in facts
                ),
                "）",
            )
        )
    missing_inputs = evidence["missing_inputs"]
    if missing_inputs:
        parts.extend(("（缺少：", "、".join(missing_inputs), "）"))
    children = evidence.get("children", [])
    if children:
        parts.extend(("{", "；".join(_evidence_text(child) for child in children), "}"))
    return "".join(parts)


def _evidence_line(label: str, evidence: list[dict[str, object]]) -> str:
    return f"{label}：{'；'.join(_evidence_text(item) for item in evidence) if evidence else '无'}"


def _suggestion(
    signal_type: str,
    *,
    quantity: int | None,
    bucket: object,
) -> str:
    if signal_type == "RISK_BREACH":
        return "暂停加仓"
    if quantity is None:
        raise ValueError("invalid alert action")
    if signal_type == "BUY_CORE_READY":
        return f"低吸底仓{quantity}股"
    if signal_type == "BUY_TACTICAL_READY":
        return f"低吸机动仓{quantity}股"
    if signal_type == "PRESSURE_REDUCE_READY":
        return f"减仓机动仓{quantity}股"
    bucket_label = "机动仓" if bucket == "TACTICAL" else "底仓"
    if signal_type == "RISK_EXIT_PENDING_SETTLEMENT":
        return f"目标{bucket_label}{quantity}股尚不可卖"
    return f"卖出{bucket_label}{quantity}股"


def _render_historical_alert(
    *,
    event_id: str,
    plan_id: str,
    plan_version: int,
    symbol: str,
    name: str,
    signal_type: str,
    severity: str,
    evaluated_at: datetime,
    market_data_at: datetime | None,
    data_age_seconds: int | None,
    price_fen: int | None,
    quantity: int | None,
    bucket: object,
    matched_conditions: list[dict[str, object]],
    satisfied_conditions: list[dict[str, object]],
    unmet_conditions: list[dict[str, object]],
    blockers: list[dict[str, object]],
    relevant_zone: dict[str, object] | None,
    risk_line_fen: int | None,
    cause_id: str,
) -> str:
    market_text = "不可用（延迟未知）"
    if market_data_at is not None:
        market_text = f"{market_data_at:%Y-%m-%d %H:%M}（延迟{data_age_seconds}秒）"
    price_text = "不可用" if price_fen is None else _fen_text(price_fen)
    lines = [
        f"【{_SIGNAL_LABELS[signal_type]}｜{severity}】{escape(name, quote=True)}（{symbol}）",
        f"时间：{evaluated_at:%Y-%m-%d %H:%M}  行情：{market_text}",
        (f"价格：{price_text}  建议：{_suggestion(signal_type, quantity=quantity, bucket=bucket)}"),
    ]
    if relevant_zone is not None:
        lower = "含下界" if relevant_zone["include_low"] else "不含下界"
        upper = "含上界" if relevant_zone["include_high"] else "不含上界"
        low_fen = _fen_text(relevant_zone["low_fen"])[:-1]
        high_fen = _fen_text(relevant_zone["high_fen"])
        lines.append(
            f"区间：{_ZONE_LABELS[relevant_zone['zone']]}{low_fen}～{high_fen}（{lower}、{upper}）"
        )
    lines.extend(
        (
            _evidence_line("信号成立", matched_conditions),
            _evidence_line("结果成立", satisfied_conditions),
            _evidence_line("结果未成立", unmet_conditions),
            _evidence_line("阻断", blockers),
            (
                f"风险线：{_fen_text(risk_line_fen) if risk_line_fen else '未提供'}"
                f"  计划：{escape(plan_id, quote=True)}-v{plan_version}"
            ),
            f"下一步：{_NEXT_STEP_LABELS[signal_type]}",
            f"原因：{escape(cause_id, quote=True)}",
            f"事件：{event_id}",
            "仅提醒，不会自动下单。",
        )
    )
    message = "\n".join(lines)
    if len(message) > _MAX_ALERT_TEXT_CHARS:
        raise ValueError("invalid rendered alert size")
    return message


def _contains_disallowed_text(value: str, *, allow_newline: bool = False) -> bool:
    return any(
        not (allow_newline and character == "\n")
        and category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    )


def downgrade() -> None:
    connection = op.get_bind()
    lossy_row = connection.execute(
        sa.text(
            "SELECT 1 FROM monitor_event AS monitor "
            "LEFT JOIN alert_event AS alert "
            "ON alert.id = monitor.id AND alert.sequence = monitor.sequence "
            "WHERE monitor.event_type != 'alert.created' OR alert.id IS NULL LIMIT 1"
        )
    ).scalar_one_or_none()
    if lossy_row is not None:
        raise RuntimeError("0006_monitor_event refuses to discard monitor event identities")
    op.drop_table("monitor_event")
    op.create_table(
        "alert_sequence",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_alert_sequence_singleton"),
        sa.CheckConstraint("last_sequence >= 0", name="ck_alert_sequence_nonnegative"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO alert_sequence (singleton_id, last_sequence) "
            "SELECT singleton_id, last_sequence FROM monitor_sequence"
        )
    )
    op.drop_table("monitor_sequence")
