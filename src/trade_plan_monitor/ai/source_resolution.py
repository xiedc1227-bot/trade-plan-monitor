"""Conservative source repairs and reviewable natural-language evidence.

No source hash, filename, stock-specific rule or later document is used here.
Numbers remain exact evidence. Semantic interpretation remains subject to the
normal explicit review; it never verifies a future market condition.
"""

import re
from decimal import Decimal


def plain(text):
    return re.sub(r"[*_`]", "", text)


def _full_exit(text):
    """A literal liquidation statement, excluding questions and negation."""
    return bool(re.search(r"确认全部退出|退出全部(?:持仓|仓位|\d+股)", text)) and not re.search(
        r"不确认|不退出|不应|不得|不能|并非|不是|是否|取消|撤销|\?|？", text
    )


def ordinary_full_exit_line(text, risk_fen):
    if risk_fen is None:
        return None
    # Bind scope to this exact risk price and branch on the same source line.
    # A separate tactical line or a severe-only exit cannot fill ordinary scope.
    for line in text.splitlines():
        price = re.search(r"首次收盘跌破(\d+(?:\.\d+)?)但只是普通破位", line)
        if price and Decimal(price[1]) * 100 == risk_fen and _full_exit(line):
            return line
    return None


def is_structural_heading(excerpt):
    text = excerpt.strip()
    return bool(
        re.fullmatch(r"#{1,6}\s+(?:\d+[.、]\s*)?[\w\s与及和：:（）()]+", text)
    ) and not re.search(
        r"如果|若|必须|买入|卖出|清仓|加仓|减仓|止损|跌破|高于|低于|if\b|buy|sell",
        text,
        re.I,
    )


def can_be_context(excerpt):
    """Do not let a model background label erase a forward trading instruction."""
    if is_structural_heading(excerpt):
        return True
    if plain(excerpt).startswith("最好") and not re.search(
        r"必须|不得|才买|才卖|如果|若|买入|卖出|清仓", plain(excerpt)
    ):
        return True  # Explicit preference, not a hard prerequisite.
    if re.fullmatch(
        r"(?:你(?:本身|目前|当前)?(?:已经|仍是|仍|已)?0股|你没有持仓)[，。；]*", plain(excerpt)
    ):
        return True
    if re.fullmatch(
        r"(?:所以|实际|\d+月\d+日|\d+日)?(?:买入|卖出)0股[。；;]*", plain(excerpt).strip()
    ):
        return True
    return not re.search(
        r"如果|若|必须|买入|卖出|清仓|加仓|减仓|才(?:考虑|买|卖|确认)|需要|不得|不要|不追|不买|不接刀|"
        r"继续0股|保持0股|取消|暂不|第一笔|第二笔|最后100股|最大计划|"
        r"回踩|站稳|重新收|不下移|不向下|不机械|不能异常|"
        r"\b(?:if|must|shall|until|buy|sell|stop.loss|maximum)\b",
        plain(excerpt),
        re.I,
    )


def recover_zero_inventory(account, source):
    from trade_plan_monitor.ai.loop_plan_extraction import OpeningFact, _check_fact
    from trade_plan_monitor.ai.review import server_source_clauses

    if account.lots or (
        account.inventory_quantity is not None and account.inventory_quantity.value != 0
    ):
        return account
    clauses = server_source_clauses(source)
    # A competing explicit positive holding prevents recovery from a zero mention.
    for clause in clauses:
        if re.search(
            r"(?:持仓|持有|库存|holdings|inventory)\s*[：:=]?\s*[1-9]\d*\s*(?:股|shares)"
            r"|[1-9]\d*\s*(?:股|shares)\s*(?:持仓|库存|holdings|inventory)",
            plain(clause.excerpt),
            re.I,
        ):
            return account.model_copy(update={"inventory_quantity": None})
    if account.inventory_quantity is not None:
        try:
            _check_fact(account.inventory_quantity, "quantity", source, clauses)
            return account
        except ValueError:
            account = account.model_copy(update={"inventory_quantity": None})
    for clause in clauses:
        fact = OpeningFact[int](value=0, start=clause.start, end=clause.end, excerpt=clause.excerpt)
        try:
            _check_fact(fact, "quantity", source, clauses)
        except ValueError:
            continue
        return account.model_copy(update={"inventory_quantity": fact})
    return account


def normalize_source_draft(data, source):
    """Remove demonstrably false authority; retain all source clauses for review."""
    text = plain(source.text)
    limits = set(re.findall(r"(?:最大(?:计划)?持仓|最大计划|持仓上限)\s*[：:]?\s*(\d+)\s*股", text))
    if data["position"].get("max_qty") is None and len(limits) == 1:
        limit = int(next(iter(limits)))
        if limit > 0 and limit % 100 == 0:
            data["position"]["max_qty"] = limit

    def fixed_dates(value):
        if isinstance(value, dict):
            if value.get("mode") == "FIXED" and value.get("unit") == "FEN":
                if value.get("as_of") and value["as_of"] not in source.text:
                    value["as_of"] = None
            for child in value.values():
                fixed_dates(child)
        elif isinstance(value, list):
            for child in value:
                fixed_dates(child)

    fixed_dates(data)
    levels = data.get("levels")
    if levels:
        for field, label in (("low_buy", "低吸观察区"), ("pressure", "主要压力区")):
            ranges = set(
                re.findall(
                    rf"\|\s*{label}\s*\|\s*(\d+(?:\.\d+)?)\s*[—–－~-]\s*(\d+(?:\.\d+)?)\s*\|",
                    text,
                )
            )
            if levels.get(field) is None and len(ranges) == 1:
                low, high = (Decimal(value) * 100 for value in next(iter(ranges)))
                if low == int(low) and high == int(high) and 0 < low <= high:
                    # Display observation bounds. Inclusivity remains a proposed
                    # source interpretation; this does not attach an order zone.
                    levels[field] = dict(
                        low_fen=int(low), high_fen=int(high), include_low=True, include_high=True
                    )
        if re.search(r"低吸观察区\s*\|\s*暂不(?:设置|启用)", text):
            levels["low_buy"] = None
            for rule in data["ordinary_rules"]:
                if rule.get("zone") == "LOW_BUY":
                    rule["zone"] = None
        if re.search(r"(?:不是|并非).{0,12}(?:新仓|新仓位).{0,12}止损", text):
            levels["risk_line_fen"] = None
            levels["risk_comparison"] = None
    # Schedule dates are already confirmed preparation metadata. They are not
    # literal source dates and must not create another date evidence request.
    if source.effective_trade_date and data.get("activation", {}).get("mode") == "TRADING_DAY":
        if data["activation"].get("trading_day") == str(source.effective_trade_date):
            data["activation"] = {"mode": "MANUAL"}
    # 'Re-establish a zone and evaluate the first lot' grants evaluation only.
    evaluation_only = bool(re.search(r"再重新设置低吸区并评估第一笔", text))
    if evaluation_only:
        data["ordinary_rules"] = []
    # Staying empty/cancelling entry does not authorize selling hypothetical lots.
    explicit_exit = re.search(
        r"确认普通风险退出|清仓|卖出\s*[1-9]\d*股|减仓\s*[1-9]\d*股", text
    ) or _full_exit(text)
    if not explicit_exit:
        alerts = data.setdefault("alert_rules", [])
        for index, branch in enumerate(data["risk_branches"]):
            if branch.get("condition") and len(alerts) < 10:
                alerts.append(
                    dict(
                        kind="RISK_ALERT",
                        rule_id=f"source-entry-risk-{index + 1}",
                        condition=branch["condition"],
                        confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
                    )
                )
        data["risk_branches"] = []
    elif "下一交易日收盘若仍未收回" in text:
        for branch in data["risk_branches"]:
            if branch["kind"] == "ORDINARY_TECHNICAL":
                # The ordinary risk engine already owns the two-close sequence.
                branch["condition"] = None
                if not re.search(r"核心仓|核心持仓|core.position", text, re.I):
                    # A core price defense is not evidence of a CORE lot bucket.
                    branch["involves_core"] = None
    full_exit = ordinary_full_exit_line(text, (levels or {}).get("risk_line_fen"))
    if full_exit:
        ordinary = [b for b in data["risk_branches"] if b["kind"] == "ORDINARY_TECHNICAL"]
        if len(ordinary) == 1:
            ordinary[0].update(
                involves_core=True,
                target_core_qty=0,
                target_tactical_qty=0,
                scope_evidence=full_exit,
            )
    for branch in data["risk_branches"]:
        branch["priority"] = {"ORDINARY_TECHNICAL": 3, "SEVERE_TECHNICAL": 2}[branch["kind"]]
    # Observing an old buy zone is not a requirement to execute the next-day
    # breakout inside that same zone (which would make close > upper impossible).
    for rule in data["ordinary_rules"]:
        if rule.get("zone") == "LOW_BUY" and re.search(r"收盘重新站上", text):
            rule["zone"] = None
    # Suggestions introduced by '最好' are not mandatory prerequisites.
    optional = re.findall(r"最好(?:还)?(?:能)?(?:看到)?([^。\n]+)", text)

    def remove_optional(value):
        if isinstance(value, dict):
            if value.get("type") == "REVIEWED_FACT":
                for phrase in optional:
                    value["evidence_requirement"] = (
                        value["evidence_requirement"].replace(phrase, "").strip("；;、，, ")
                    )
            for child in value.values():
                remove_optional(child)
        elif isinstance(value, list):
            for child in value:
                remove_optional(child)

    remove_optional(data)
    normalize_source_conditions(data, text)
    normalize_prior_recovery(data, source)
    buys = [r for r in data["ordinary_rules"] if r["side"] == "BUY"]
    if buys and re.search(rf"第一笔\s*{buys[0]['quantity']}股", text):
        buys[0]["independent_signal"] = {"mode": "ONCE_PER_RULE"}
        if len(buys) == 2 and re.search(rf"第二笔\s*{buys[1]['quantity']}股", text):
            buys[1]["independent_signal"] = {
                "mode": "AFTER_RULE_COMPLETED",
                "prior_rule_id": buys[0]["rule_id"],
            }
    return data


def normalize_source_conditions(data, text):
    """Resolve only exact source alternatives and explicitly optional preferences."""

    def words(value):
        return re.sub(r"[^\w.]", "", re.sub(r"（[^）]*）|\([^)]*\)", "", plain(value)))

    preferences = [words(p) for p in re.findall(r"最好(?:还)?(?:能)?(?:看到)?([^。\n]+)", text)]

    def rewrite(node, prices):
        if node.get("type") == "REVIEWED_FACT":
            value = node["evidence_requirement"]
            if words(value) in preferences and words(value):
                return None
            exact = re.fullmatch(
                r"完整日K止跌[：:]明显下影、止跌阳线或连续两个收盘不再下移"
                r"(?:（三者任一）)?(?:，同时量能不能异常放大；随后收盘重新站上(\d+(?:\.\d+)?)元。)?",
                value,
            )
            if (
                exact
                and "连续两个收盘不再下移" in text
                and (exact[1] is None or Decimal(exact[1]) * 100 in prices)
            ):
                shape = {**node, "evidence_requirement": "明显下影或止跌阳线"}
                sequence = dict(
                    type="DAILY_CLOSE_SEQUENCE",
                    offset=0,
                    sessions=2,
                    mode="PAIRWISE_NONDECREASING",
                    comparator=None,
                    reference=None,
                )
                alternative = dict(type="ANY", conditions=[shape, sequence])
                if exact[1] is not None:
                    return dict(
                        type="ALL",
                        conditions=[
                            alternative,
                            {
                                **node,
                                "fact_kind": "VOLUME_OR_CANDLE",
                                "evidence_requirement": "量能不能异常放大",
                            },
                        ],
                    )
                return alternative
        if node.get("type") == "ALL":
            children = [
                child for c in node["conditions"] if (child := rewrite(c, prices)) is not None
            ]
            if children:
                return {**node, "conditions": children}
        return node

    def prices(node):
        if node.get("type") == "DAILY_PRICE_COMPARE" and node.get("field") == "close":
            reference = node.get("reference", {})
            if reference.get("mode") == "FIXED" and node.get("comparator") in ("GT", "GTE"):
                return {Decimal(str(reference["value"]))}
        return set().union(*(prices(c) for c in node.get("conditions", [])))

    for rule in data["ordinary_rules"]:
        condition = rule.get("condition")
        if condition:
            rule["condition"] = rewrite(condition, prices(condition)) or condition


def normalize_prior_recovery(data, source):
    """Expose a source's explicit recovery-before-retest stage; never quantify the retest.

    Only start a new recovery window when this source explicitly states that the
    price has not yet recovered. Its confirmed effective date is preparation
    metadata, not an invented historical observation or lookback parameter.
    """
    text = plain(source.text)
    matches = re.findall(
        r"如果完整日K(?:首次)?重新(?:收盘站上|收回)(\d+(?:\.\d+)?)(以上)?", text
    )
    if not source.effective_trade_date or len(set(matches)) != 1:
        return
    price, above = matches[0]
    unrecovered = rf"仍未重新收复{re.escape(price)}|收盘\d+(?:\.\d+)?仍低于{re.escape(price)}"
    if not re.search(unrecovered, text):
        return
    if not re.search(r"之后.{0,30}回踩|收复\d+(?:\.\d+)?后，再出现一次回踩", text):
        return
    threshold = Decimal(price) * 100
    if threshold != int(threshold):
        return
    for rule in data['ordinary_rules']:
        root = rule.get('condition')
        if rule['side'] != 'BUY' or not root or root.get('type') != 'ALL':
            continue
        children = root['conditions']
        if any(c.get('type') == 'DAILY_PRIOR_CLOSE' for c in children):
            continue
        if not any(c.get('type') == 'REVIEWED_FACT' and '回踩' in c['evidence_requirement']
                   and ('再次收回向上' in c['evidence_requirement'] or
                        '重新收起' in c['evidence_requirement']) for c in children):
            continue
        # A current-day close compare incorrectly changes an earlier stage into
        # a same-day gate. Keep other conditions and their unquantified wording.
        retained = [c for c in children if not (
            c.get('type') == 'DAILY_PRICE_COMPARE' and c.get('field') == 'close'
            and c.get('offset') == 0 and c.get('comparator') in ('GT', 'GTE')
            and c.get('reference', {}).get('mode') == 'FIXED'
            and re.search(r'完整日K(?:首次)?重新(?:收盘站上|收回)',
                          c['reference'].get('source', ''))
            and Decimal(str(c['reference']['value'])) == threshold)]
        root['conditions'] = [dict(type='DAILY_PRIOR_CLOSE',
            since_date=str(source.effective_trade_date), price_fen=int(threshold),
            comparator='GTE' if above else 'GT'), *retained]


def interpretation_matches(path, value, excerpt, draft):
    """Exact numbers plus a bounded proposed semantic translation, never attestation."""
    text = plain(excerpt)
    if re.fullmatch(
        r"risk_branches\[\d+\]\.(?:involves_core|target_core_qty|target_tactical_qty)", path
    ) and _full_exit(text):
        return (
            value is True if path.endswith("involves_core") else type(value) is int and value == 0
        )
    if value is None:
        return path in {"levels.low_buy", "levels.pressure"} and bool(
            re.search(r"暂不设置|暂不启用|取消", text)
        )
    if isinstance(value, bool):
        # Inclusivity remains visible in the candidate for overall review.
        return path.endswith(("include_low", "include_high")) and bool(
            re.search(r"\d+(?:\.\d+)?\s*[—–－~-]\s*\d", text)
        )
    if isinstance(value, list):
        return False
    numeric = isinstance(value, int) or (
        path.endswith(".reference.value") and re.fullmatch(r"\d+(?:\.\d+)?", str(value))
    )
    if numeric:
        if path.endswith(".sessions") and value == 2:
            if "连续两个收盘不再下移" in text:
                return True
        if path.endswith("quantity"):
            return bool(re.search(rf"(?<!\d){value}\s*股", text))
        if path.endswith(".offset") and value == 0:
            return bool(re.search(r"日K|收盘|回踩", text))
        multiplier = 100 if path.endswith("_fen") else 1
        if path.endswith(".reference.value"):
            from trade_plan_monitor.ai.daily_review import semantic_values

            values = semantic_values(draft)
            if values.get(path.removesuffix("value") + "unit") == "FEN":
                multiplier = 100
        return any(
            Decimal(number) * multiplier == Decimal(str(value))
            for number in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", text)
        )
    if path == "symbol":
        return value in text or draft.name in text
    if path == "market":
        return draft.name in text or draft.symbol in text
    if path.endswith(".comparator"):
        markers = {
            "GT": r"站上|高于|超过|大于|以上|站稳",
            "GTE": r"收回|收复|不低于|至少|站稳",
            "LT": r"跌破|低于|小于|未收回|以下|下方",
            "LTE": r"不高于|至多|不超过",
            "EQ": r"等于",
        }
        return bool(re.search(markers.get(value, r"(?!)"), text))
    if path.endswith(".confirmation.kind") and value == "OFFICIAL_DAILY_CLOSE":
        return bool(re.search(r"收盘|日K|日线|daily|close", text, re.I))
    if path.endswith(".independent_signal.mode") and value in {
        "ONCE_PER_RULE",
        "AFTER_RULE_COMPLETED",
    }:
        return bool(re.search(r"第一笔|第二笔|一次", text))
    if path.endswith(".side"):
        return bool(
            re.search(r"买|低吸|建仓|第一笔|第二笔" if value == "BUY" else r"卖|减仓|退出", text)
        )
    if path.endswith(".reference.as_of"):
        return str(value) in text  # Never invent historical dates for fixed constants.
    # These are representations of source-linked conditions, not extra facts.
    return bool(text.strip()) and not is_structural_heading(text)
