"""Finite complete Chinese minute-rule sentences, without candidate-derived meanings."""

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash

_N = r"[1-9][0-9]{0,8}"
_P = r"[0-9]{1,9}(?:\.[0-9]{1,2})?"
_RANGE = (
    rf"当(?P<one>一根)?已完成的?(?P<tf>{_N})分钟K线收盘价"
    rf"(?P<range>处于)(?P<low>{_P})至(?P<high>{_P})元之间，\s*"
    r"(?P<inclusive>包含两端边界)"
)
_VOLUME = (
    rf"，(?P<and>且)该根成交量(?P<gte>不低于)前(?P<window>{_N})根"
    rf"已完成(?P<vtf>{_N})分钟K线\s*平均成交量的(?P<ratio>{_P})倍"
)
_TRADE = re.compile(_RANGE + rf"(?:{_VOLUME})?时，(?P<side>提醒买入|提醒卖出)(?P<qty>{_N})股。")
_ALERT = re.compile(
    rf"当已完成(?P<tf>{_N})分钟K线收盘价(?P<lt>低于)(?P<price>{_P})元时，"
    r"(?P<alert>发出风险提醒)。"
)
_CAP = re.compile(rf"最大计划持仓(?P<qty>{_N})股。")
_HOLDINGS = re.compile(
    rf"(?P<symbol>[0-9]{{6}}\.(?:SZ|SH|BJ))当前持仓{_N}股，"
    r"均为测试日前已持有且当日可卖；"
)
_NO_FILL = "提醒及确认收到提醒不代表成交，未登记成交时持仓不变。"


@dataclass(frozen=True, slots=True)
class LiteralSentence:
    start: int
    end: int
    group_id: str
    scope: str
    expected: tuple
    atoms: tuple
    context: str | None = None
    collection_sizes: tuple = ()

    def matched(self, payload, metadata):
        from trade_plan_monitor.ai.source_obligations import MISSING, value_at

        return all((actual := value_at(metadata if path == "symbol" else payload, path))
                   is not MISSING and canonical(actual) == canonical(value)
                   for path, value in self.expected) and all(
                       isinstance(actual := value_at(payload, path), list) and len(actual) == size
                       for path, size in self.collection_sizes)

    def paths_at(self, start, end):
        return tuple(path for path, begin, stop in self.atoms if begin < end and stop > start)


def literal_sentences(source):
    """Unrecognized sentences and every unknown suffix remain outside this registry."""
    result, ordinary_index, alert_index = [], 0, 0
    digest = scope_hash(source)
    for sentence in re.finditer(r"[^。；]*(?:[。；]|\Z)", source):
        text = sentence.group().lstrip()
        start = sentence.start() + len(sentence.group()) - len(text)
        expected, atoms, context, scope = [], [], None, "PLAN"
        collection_sizes = []

        def atom(path, value, capture, *, expected=expected, atoms=atoms, start=start):
            expected.append((path, value))
            atoms.append((path, start + match.start(capture), start + match.end(capture)))

        if (match := _HOLDINGS.fullmatch(text)) is not None:
            expected.append(("symbol", match["symbol"]))
            context = "REPORTED_INVENTORY_WITHOUT_INITIALIZATION"
        elif text == _NO_FILL:
            context = "REMINDER_ACKNOWLEDGMENT_DOES_NOT_RECORD_A_FILL"
        elif (match := _CAP.fullmatch(text)) is not None:
            atom("position.max_qty", int(match["qty"]), "qty")
        elif (match := _TRADE.fullmatch(text)) is not None:
            if match["vtf"] is not None and (match["tf"] != match["vtf"]
                    or Decimal(match["ratio"]) <= 0):
                continue
            if Decimal(match["low"]) > Decimal(match["high"]):
                continue
            root = f"ordinary_rules[{ordinary_index}]"
            ordinary_index += 1
            scope = "BUY" if match["side"] == "提醒买入" else "SELL"
            condition = root + ".condition"
            if match["and"] is not None:
                collection_sizes.append((condition + ".conditions", 2))
                atom(condition + ".type", "ALL", "and")
                volume = condition + ".conditions[1]"
                condition += ".conditions[0]"
                atom(volume + ".type", "MINUTE_VOLUME_TO_MEAN_GTE", "gte")
                atom(volume + ".timeframe_minutes", int(match["vtf"]), "vtf")
                atom(volume + ".window_bars", int(match["window"]), "window")
                atom(volume + ".minimum_ratio", format(Decimal(match["ratio"]).normalize(), "f"),
                     "ratio")
            atom(root + ".side", scope, "side")
            atom(root + ".quantity", int(match["qty"]), "qty")
            atom(condition + ".type", "MINUTE_CLOSE_IN_RANGE", "range")
            atom(condition + ".timeframe_minutes", int(match["tf"]), "tf")
            atom(condition + ".low_fen", int(Decimal(match["low"]) * 100), "low")
            atom(condition + ".high_fen", int(Decimal(match["high"]) * 100), "high")
            atom(condition + ".include_low", True, "inclusive")
            atom(condition + ".include_high", True, "inclusive")
            atom(root + ".confirmation.kind", "COMPLETED_BAR_CLOSE", "tf")
            atom(root + ".confirmation.timeframe_minutes", int(match["tf"]), "tf")
        elif (match := _ALERT.fullmatch(text)) is not None:
            root = f"alert_rules[{alert_index}]"
            alert_index += 1
            scope = "ALERT"
            atom(root + ".kind", "RISK_ALERT", "alert")
            atom(root + ".condition.type", "MINUTE_CLOSE_BELOW", "lt")
            atom(root + ".condition.timeframe_minutes", int(match["tf"]), "tf")
            atom(root + ".condition.price_fen", int(Decimal(match["price"]) * 100), "price")
            atom(root + ".confirmation.kind", "COMPLETED_BAR_CLOSE", "tf")
            atom(root + ".confirmation.timeframe_minutes", int(match["tf"]), "tf")
        else:
            continue
        end = sentence.end()
        identity = daily_hash("source-literal-sentence-v1", dict(
            source_hash=digest, start=start, end=end, expected=expected, context=context,
            collection_sizes=collection_sizes))
        result.append(LiteralSentence(start, end, identity, scope,
                                      tuple(expected), tuple(atoms), context,
                                      tuple(collection_sizes)))
    # This finite grammar describes a closed literal rule graph. Additional
    # context cannot cancel its cardinality. Other policy grammars may require
    # an explicit future composition adapter; unknown text still blocks.
    if ordinary_index or alert_index:
        sizes = (("ordinary_rules", ordinary_index), ("alert_rules", alert_index),
                 ("risk_branches", 0))
        result = [replace(row,
                          group_id=daily_hash("source-literal-complete-v1", dict(
                              group_id=row.group_id,
                              collection_sizes=(*row.collection_sizes, *sizes))),
                          collection_sizes=(*row.collection_sizes, *sizes))
                  if row.context is None else row for row in result]
    return tuple(result)
