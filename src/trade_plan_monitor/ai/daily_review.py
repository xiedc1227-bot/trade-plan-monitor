"""Server-derived source fidelity and explicit human policy supplements for Schema 4."""

import re
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import Field, JsonValue

from trade_plan_monitor.ai.review import MappingValidationError, server_source_clauses
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier, Text
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_issues,
)
from trade_plan_monitor.domain.daily_scope import (
    EXCLUSION_REASON,
    excluded_spans,
    require_inventory_assertion,
    require_nontechnical_exclusion,
    scope_hash,
)

Digest = str


class DailySourceExclusion(DailyValue):
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    excerpt: str = Field(min_length=1, max_length=512)
    reason: Literal["FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION"]
    origin: Literal["REGISTERED_FRAGMENT", "HUMAN_SCOPE_SELECTION"] = "REGISTERED_FRAGMENT"


class DailyTechnicalRemainder(DailyValue):
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    excerpt: str = Field(min_length=1, max_length=512)
    disposition: Literal["POLICY", "UNRESOLVED", "UNSUPPORTED"]
    paths: tuple[str, ...] = Field(max_length=512)
    reason: Text


class DailyClause(DailyValue):
    clause_id: Identifier
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    excerpt: str = Field(min_length=1, max_length=512)
    disposition: Literal[
        "POLICY", "INVENTORY_ASSERTION", "BACKGROUND", "CONTEXT", "UNRESOLVED", "UNSUPPORTED"
    ]
    paths: tuple[str, ...] = Field(max_length=512)
    reason: Text
    exclusions: tuple[DailySourceExclusion, ...] = Field(default=(), max_length=50)
    remainders: tuple[DailyTechnicalRemainder, ...] = Field(default=(), max_length=51)
    semantic_role: Literal[
        "DIRECTIVE", "HISTORICAL", "ACCOUNT", "COMMENTARY", "AMBIGUOUS"
    ] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


def daily_source_clauses(source, selections=()):
    """Preserve legacy clauses and partition only finite registered exclusion spans."""
    clauses = server_source_clauses(source)
    for selection in selections:
        if (
            selection.source_hash != scope_hash(source)
            or selection.excerpt != source[selection.start : selection.end]
            or not any(c.start <= selection.start < selection.end <= c.end for c in clauses)
        ):
            raise ValueError("human scope exclusion differs from exact source clause/span")
        require_nontechnical_exclusion(selection.excerpt)
    result = []
    for clause in clauses:
        selected = tuple(s for s in selections if clause.start <= s.start < s.end <= clause.end)
        registered = tuple(
            (start, end)
            for start, end in excluded_spans(source, clause)
            if not any(s.start <= start and end <= s.end for s in selected)
        )
        exclusions = tuple(
            sorted(
                (
                    *selected,
                    *(
                        DailySourceExclusion(
                            source_hash=scope_hash(source),
                            start=start,
                            end=end,
                            excerpt=source[start:end],
                            reason=EXCLUSION_REASON,
                        )
                        for start, end in registered
                    ),
                ),
                key=lambda s: s.start,
            )
        )
        spans = tuple((s.start, s.end) for s in exclusions)
        if any(left[1] > right[0] for left, right in zip(spans, spans[1:], strict=False)):
            raise ValueError("source exclusion spans overlap")
        cursor = clause.start
        remainder = []
        for start, end in (*spans, (clause.end, clause.end)):
            # Keep connectors and punctuation visible; punctuation alone is not policy.
            text = source[cursor:start]
            if text.strip(" 。；，,;、.!?！？\n\r\t"):
                remainder.append(
                    DailyTechnicalRemainder(
                        start=cursor,
                        end=start,
                        excerpt=text,
                        disposition="UNRESOLVED",
                        paths=(),
                        reason="Review this technical remainder and its exact policy paths.",
                    )
                )
            cursor = end
        whole_background = bool(exclusions) and not remainder
        result.append(
            DailyClause(
                clause_id=clause.clause_id,
                start=clause.start,
                end=clause.end,
                excerpt=clause.excerpt,
                disposition="BACKGROUND" if whole_background else "UNRESOLVED",
                paths=(),
                reason=EXCLUSION_REASON
                if whole_background
                else "Define material technical source policy.",
                exclusions=exclusions,
                remainders=tuple(remainder) if exclusions else (),
            )
        )
    return tuple(result)


def normalize_daily_exclusions(clauses, source):
    """Server-own excluded spans; preserve explicit technical remainder review."""
    canonical = daily_source_clauses(source)
    result = []
    for original, treatment in zip(clauses, canonical, strict=True):
        if not treatment.exclusions:
            result.append(original)
        elif original.exclusions:
            result.append(original)  # build_daily_review validates exact coverage below.
        elif treatment.remainders:
            result.append(
                original.model_copy(
                    update={
                        "exclusions": treatment.exclusions,
                        "remainders": treatment.remainders,
                        "disposition": "UNRESOLVED",
                        "paths": (),
                    }
                )
            )
        else:
            result.append(treatment)
    return tuple(result)


class DailySupplement(DailyValue):
    supplement_id: Identifier
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(min_length=1, max_length=512)
    value: JsonValue
    reason: Text


class DailyFieldBinding(DailyValue):
    path: str = Field(min_length=1, max_length=512)
    value: JsonValue
    origin: Literal[
        "SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC", "HUMAN_SUPPLEMENT", "PRODUCT_CONTRACT"
    ]
    unit: Literal["JSON", "FEN_FROM_YUAN", "SHARES", "RATIO", "TEXT", "STRUCTURE"]
    clause_ids: tuple[Identifier, ...] = Field(max_length=50)
    supplement_id: Identifier | None


class DailyMapping(DailyValue):
    mapping_version: Literal["daily-mapping-v1"]
    candidate_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    clauses: tuple[DailyClause, ...] = Field(max_length=512)
    bindings: tuple[DailyFieldBinding, ...] = Field(max_length=2000)
    supplements: tuple[DailySupplement, ...] = Field(max_length=2000)


class DailyReviewIssue(DailyValue):
    issue_id: str
    path: str
    code: str
    reason: str


class DailyReviewSnapshot(DailyValue):
    content_hash: str
    source_hash: str
    evidence_hash: str
    mapping: DailyMapping
    issues: tuple[DailyReviewIssue, ...]


def semantic_values(draft):
    """All non-null policy leaves and ALL/ANY structure; identity/display are separate."""
    data = draft.executable_payload()
    for key in ("plan_id", "version", "name", "metadata"):
        data.pop(key)
    values = {}

    def visit(value, path):
        if isinstance(value, dict):
            if value.get("type") in {"ALL", "ANY"}:
                values[path] = value["type"]
            for key, child in value.items():
                visit(child, path + "." + key if path else key)
        elif isinstance(value, list):
            if not value:
                values[path] = []
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
        elif value is not None or (
            draft.schema_version in {5, 6, 7} and path in {"levels.low_buy", "levels.pressure"}
        ):
            values[path] = value

    visit(data, "")
    if draft.schema_version in {6, 7}:
        from trade_plan_monitor.domain.market_linkage_definitions import (
            EXPANDED_EXCEPTION_POLICY,
            EXPANDED_LINKAGE_POLICY,
        )
        definitions = (EXPANDED_EXCEPTION_POLICY if draft.schema_version == 7
                       else EXPANDED_LINKAGE_POLICY)
        for i, rule in enumerate(draft.ordinary_rules):
            if getattr(rule, "market_policy", None) is not None:
                values.update({f"ordinary_rules[{i}].market_policy.expanded.{key}": value
                               for key, value in definitions.items()})
    return values


_CONTRACT_VALUES = {
    "trading_rules.settlement": "NEXT_EXCHANGE_SESSION",
    "trading_rules.tick_size_fen": 1,
    "trading_rules.special_state_restrictions": "BLOCK_UNVERIFIED",
    "schema_version": 4,
    "execution_mode": "DAILY_CLOSE_PLAN",
    "execution_version": "daily-close-v1",
    "monitoring.timeframe": "DAILY",
    "monitoring.indicator_formula_version": "daily-ta-v2",
    "monitoring.price_basis": "QFQ",
    "monitoring.source_requirement": "ONE_VERIFIED_PROVIDER",
    "monitoring.comparability_requirement": "CURRENT_QUOTE_BASIS",
    "execution_policy.confirmation": "OFFICIAL_DAILY_CLOSE",
    "execution_policy.ordinary_window": "NEXT_EXCHANGE_SESSION_ONLY",
    "execution_policy.same_signal": "ONE_PLANNED_QUANTITY",
    "execution_policy.risk_priority": "SEVERE_THEN_ORDINARY",
    "execution_policy.ordinary_conflict": "BLOCK_BOTH",
}


def _contract_values(draft):
    if draft.schema_version not in {5, 6, 7}:
        return _CONTRACT_VALUES
    return {
        **{
            key: value
            for key, value in _CONTRACT_VALUES.items()
            if key
            not in {
                "monitoring.timeframe",
                "execution_policy.confirmation",
                "execution_policy.ordinary_window",
            }
        },
        **({f"reference_market.{key}": value for key, value in
            draft.reference_market.model_dump(mode="json").items()}
           if draft.schema_version in {6, 7} and draft.reference_market is not None else {}),
        "schema_version": draft.schema_version,
        "execution_mode": "CONDITION_PLAN",
        "execution_version": draft.execution_version,
        "monitoring.macd_min_observations": 26,
        **{
            f"risk_branches[{index}].priority":
                {"ORDINARY_TECHNICAL": 3, "SEVERE_TECHNICAL": 2}[branch.kind]
            for index, branch in enumerate(draft.risk_branches)
        },
        **{
            path: []
            for path in ("ordinary_rules", "risk_branches", "alert_rules")
            if not getattr(draft, path)
        },
        **(
            {"activation.mode": "MANUAL"}
            if draft.activation is not None and draft.activation.mode == "MANUAL"
            else {}
        ),
        **{
            f"ordinary_rules[{index}].validity.mode": "PLAN_ACTIVE"
            for index, rule in enumerate(draft.ordinary_rules)
            if rule.validity is not None and rule.validity.mode == "PLAN_ACTIVE"
        },
    }


def _persistent_deadline_issues(draft, mapping):
    """Guard recognizable source limits only for new persistent/default authority.

    This deliberately does not change reconstruction of historical dated reviews.
    Exact clause review remains responsible for meaning outside these narrow cues.
    A scoped human conversion must quote each affected clause in its reason.
    """
    if draft.schema_version not in {5, 6, 7}:
        return ()
    paths = {
        f"ordinary_rules[{i}].validity.mode": rule.side
        for i, rule in enumerate(draft.ordinary_rules)
        if rule.validity is not None and rule.validity.mode == "PLAN_ACTIVE"
    }
    if not paths:
        return ()
    limit = re.compile(
        r"(?:规则|计划|买入|卖出|交易).{0,24}(?:有效至|有效期|截止|到期|仅限|期限)"
        r"|(?:有效至|截止日期|到期日期|有效期限)"
        r"|直到人工停用或(?=\d{4}[-年]|未来|本周|下周)"
        r"|\b(?:rule|plan|buy|sell|trade).{0,32}\b(?:expires?|until|deadline|only for)\b",
        re.IGNORECASE,
    )
    supplements = {s.supplement_id: s for s in mapping.supplements}
    issues = []
    for clause in mapping.clauses:
        lifetime = re.sub(
            r"(?:计划|规则)?有效(?:期限|期)[：:]?\s*持续有效"
            r"(?:(?:[，,]\s*)?直到人工停用(?:或(?:审核启用新版本替换|新版本正式替换))?"
            r"|(?!(?:[，,]\s*)?直到人工))(?=[，,。；;\n]|$)",
            "",
            clause.excerpt,
        )
        lifetime = re.sub(
            r"\buntil\s+(?:(?:manually deactivated|manual deactivation)"
            r"(?: or replaced by a reviewed (?:new )?version)?|"
            r"replaced by a reviewed (?:new )?version)(?=\s*[.;,\n]|$)",
            "",
            lifetime,
            flags=re.I,
        )
        # Remove only a recognized local occurrence window. Never exempt the whole
        # fragment: another cutoff can occur before or after it without punctuation.
        lifetime = re.sub(
            r"单(?:次|个)(?:日线|买入|卖出)?(?:信号|指令)(?:的)?"
            r"(?:有效执行窗口)?(?:仅限|仅|只在)?(?:确认后的)?"
            r"下一(?:个)?交易日(?:收盘前|收盘)?(?:可执行|执行|有效)",
            "",
            lifetime,
        )
        lifetime = re.sub(
            r"\b(?:a )?single(?:[- ](?:buy|sell))?[- ]signal "
            r"(?:executes? )?only (?:for )?next (?:trading day|(?:exchange )?session)\b",
            "",
            lifetime,
            flags=re.I,
        )
        fragments = re.split(r"[。；;,，\n]", lifetime)
        scoped = r"规则|计划|买入|卖出|\brule\b|\bplan\b|\bbuy\b|\bsell\b"
        limited = []
        for part in fragments:
            cue = limit.search(part)
            if cue is None:
                continue
            if re.search(
                r"报告|行情|数据|指标|资料|证据|\breport\b|\bevidence\b", part, re.I
            ) and not re.search(scoped, part, re.I):
                continue
            limited.append(part)
        unresolved = set()
        for part in limited:
            dates = set(re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", part))
            date_bindings = [
                b
                for b in mapping.bindings
                if b.origin == "SOURCE"
                and clause.clause_id in b.clause_ids
                and re.fullmatch(
                    r"(?:activation|ordinary_rules\[\d+\]\.validity)"
                    r"\.(?:start_date|end_date)",
                    b.path,
                )
            ]
            # A start date cannot discharge a cutoff; one retained restriction cannot
            # hide a second deadline or an ambiguous relative duration in its clause.
            sides = {
                side
                for side, cue in (("BUY", r"买入|\bbuy\b"), ("SELL", r"卖出|\bsell\b"))
                if re.search(cue, part, re.I)
            }
            plan_limit = bool(re.search(r"计划|\bplan\b", part, re.I)) and not (
                sides or re.search(r"规则|\brule\b", part, re.I)
            )
            for path, side in paths.items():
                if sides and side not in sides:
                    continue
                prefix = "activation" if plan_limit else path.removesuffix(".mode")
                if dates and (
                    dates <= {b.value for b in date_bindings if b.path.startswith(prefix + ".")}
                    and any(
                        b.path == prefix + ".end_date" and b.value in dates for b in date_bindings
                    )
                ):
                    continue
                unresolved.add(path)
        if not unresolved:
            continue
        pending = []
        for path in sorted(unresolved):
            binding = next((b for b in mapping.bindings if b.path == path), None)
            supplement = None if binding is None else supplements.get(binding.supplement_id)
            if (
                binding is not None
                and binding.origin == "HUMAN_SUPPLEMENT"
                and supplement is not None
                and clause.excerpt in supplement.reason
                and re.search(r"改为持续有效|convert to PLAN_ACTIVE", supplement.reason)
            ):
                continue
            pending.append(path)
        if pending:
            issues.append(
                {
                    "path": "source." + clause.clause_id,
                    "code": "PLAN_SOURCE_TIME_LIMIT_REQUIRED",
                    "reason": "受影响参数："
                    + ", ".join(pending)
                    + "。保留原文期限为DATE_RANGE或待确认；"
                    "如需改为持续有效，"
                    "请在该规则有效期模式的人工补充理由中引用完整原句并写明“改为持续有效”，"
                    "重新审核后明确启用。",
                }
            )
    return tuple(issues)


def daily_contract_bindings(draft):
    values = semantic_values(draft)
    return tuple(
        DailyFieldBinding(
            path=path,
            value=value,
            origin="PRODUCT_CONTRACT",
            unit="JSON",
            clause_ids=(),
            supplement_id=None,
        )
        for path, value in _contract_values(draft).items()
        if values.get(path) == value
    )


def build_daily_review(draft, mapping, source_text):
    mapping = DailyMapping.model_validate(mapping.model_dump())
    # These fixed software values need no source or human broker-rule evidence.
    existing_paths = {binding.path for binding in mapping.bindings}
    product_rules = tuple(
        binding
        for binding in daily_contract_bindings(draft)
        if binding.path.startswith("trading_rules.") and binding.path not in existing_paths
    )
    mapping = mapping.model_copy(update={"bindings": (*mapping.bindings, *product_rules)})
    digest = daily_draft_content_sha256(draft)
    if mapping.candidate_content_hash != digest:
        raise ValueError("mapping candidate content changed")
    expected = server_source_clauses(source_text)
    if len(mapping.clauses) != len(expected):
        raise MappingValidationError("source clause count differs", "source_clauses")
    for index, (actual_clause, expected_clause) in enumerate(
        zip(mapping.clauses, expected, strict=True)
    ):
        for field in ("clause_id", "start", "end", "excerpt"):
            if getattr(actual_clause, field) != getattr(expected_clause, field):
                raise MappingValidationError(
                    "source clause differs from exact source",
                    f"source_clauses[{index}].{field}" if index <= 255 else "source_clauses",
                )
    values = semantic_values(draft)
    selections = tuple(
        s for c in mapping.clauses for s in c.exclusions if s.origin == "HUMAN_SCOPE_SELECTION"
    )
    for selection in selections:
        if (
            selection.source_hash != scope_hash(source_text)
            or selection.excerpt != source_text[selection.start : selection.end]
        ):
            raise ValueError("human scope exclusion differs from exact source span")
        require_nontechnical_exclusion(selection.excerpt)
    canonical_treatments = {c.clause_id: c for c in daily_source_clauses(source_text, selections)}
    for clause in mapping.clauses:
        canonical = canonical_treatments[clause.clause_id]
        if clause.exclusions != canonical.exclusions:
            raise ValueError("exact fundamental source exclusion is required")
        if canonical.exclusions:
            expected_spans = tuple((r.start, r.end, r.excerpt) for r in canonical.remainders)
            actual_spans = tuple((r.start, r.end, r.excerpt) for r in clause.remainders)
            if expected_spans != actual_spans:
                raise ValueError("technical remainder coverage differs from source")
            if not canonical.remainders:
                if (
                    clause.disposition != "BACKGROUND"
                    or clause.paths
                    or clause.reason != EXCLUSION_REASON
                ):
                    raise ValueError("excluded source cannot bind executable policy")
            elif clause.disposition == "BACKGROUND" or set(clause.paths) != {
                path for remainder in clause.remainders for path in remainder.paths
            }:
                raise ValueError("mixed technical remainder must retain its scoped paths")
        elif clause.disposition == "CONTEXT":
            from trade_plan_monitor.ai.source_resolution import can_be_context

            semantic_context = (clause.semantic_role in {"HISTORICAL", "ACCOUNT", "COMMENTARY"}
                                and bool(clause.reason.strip()))
            if clause.paths or not (semantic_context or can_be_context(clause.excerpt)):
                raise ValueError("context cannot hide a forward trading instruction")
        elif clause.disposition == "BACKGROUND":
            raise ValueError("BACKGROUND requires a registered exact scope exclusion")
        elif clause.remainders:
            raise ValueError("technical remainder requires exact exclusion coverage")
    clauses = {c.clause_id: c for c in mapping.clauses}
    supplements = {s.supplement_id: s for s in mapping.supplements}
    if len(supplements) != len(mapping.supplements):
        raise ValueError("duplicate supplement")
    bound = set()
    used = set()
    for binding_index, binding in enumerate(mapping.bindings):
        diagnostic_path = (
            f"field_bindings[{binding_index}]" if binding_index <= 255 else "field_bindings"
        )
        if binding.path in bound or binding.path not in values:
            raise MappingValidationError(
                "duplicate or unknown binding path", diagnostic_path + ".path"
            )
        actual = values[binding.path]
        if type(actual) is not type(binding.value) or actual != binding.value:
            raise MappingValidationError(
                "binding value differs from current candidate", diagnostic_path + ".value"
            )
        if binding.origin == "PRODUCT_CONTRACT":
            if (
                binding.clause_ids
                or binding.supplement_id
                or _contract_values(draft).get(binding.path) != actual
            ):
                raise ValueError("trading policy cannot be inferred from product contract")
        elif binding.origin == "HUMAN_SUPPLEMENT":
            supplement = supplements.get(binding.supplement_id)
            if (
                binding.clause_ids
                or supplement is None
                or supplement.candidate_content_hash != digest
            ):
                raise ValueError("human supplement is missing or belongs to another candidate")
            if (
                supplement.path != binding.path
                or type(supplement.value) is not type(actual)
                or supplement.value != actual
            ):
                raise ValueError("supplement differs from scoped candidate policy")
            used.add(supplement.supplement_id)
        else:
            if binding.supplement_id or not binding.clause_ids:
                raise ValueError("source binding requires source clauses")
            excerpts = []
            for identity in binding.clause_ids:
                clause = clauses.get(identity)
                if (
                    clause is None
                    or clause.disposition != "POLICY"
                    or binding.path not in clause.paths
                ):
                    raise ValueError("source binding is absent from its exact clause")
                if clause.exclusions:
                    excerpts.extend(
                        r.excerpt
                        for r in clause.remainders
                        if binding.path in r.paths and r.disposition == "POLICY"
                    )
                else:
                    excerpts.append(clause.excerpt)
            excerpt = " ".join(excerpts)
            if draft.schema_version == 7 and (
                ".market_policy.expanded." in binding.path
                or ".market_policy.exception_routes." in binding.path
            ):
                from trade_plan_monitor.ai.semantic_validation import (
                    semantic_interpretation_matches,
                )

                if not semantic_interpretation_matches(binding.path, actual, excerpt, draft):
                    raise ValueError("exception permission differs from source evidence")
            if binding.origin == "SOURCE_SEMANTIC":
                from trade_plan_monitor.ai.semantic_validation import (
                    semantic_interpretation_matches,
                )

                if draft.schema_version not in {5, 6, 7} or not semantic_interpretation_matches(
                    binding.path, actual, excerpt, draft,
                ):
                    raise ValueError("semantic source value differs from its exact evidence")
            elif binding.origin == "SOURCE_INTERPRETATION":
                from trade_plan_monitor.ai.source_resolution import interpretation_matches

                if draft.schema_version not in {5, 6, 7} or not interpretation_matches(
                    binding.path,
                    actual,
                    excerpt,
                    draft,
                ):
                    raise ValueError("source interpretation differs from its evidence")
            elif binding.unit == "FEN_FROM_YUAN":
                if type(actual) is not int or not any(
                    Decimal(x) * 100 == actual
                    for x in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", excerpt)
                ):
                    raise MappingValidationError(
                        "source price does not match exact yuan amount", diagnostic_path + ".unit"
                    )
            elif type(actual) is bool and draft.schema_version in {5, 6, 7}:
                literal = excerpt.strip(" \t\r\n。；;.")
                if not binding.path.endswith((".include_low", ".include_high")) or not re.fullmatch(
                    re.escape(binding.path) + r"\s*=\s*" + str(actual).lower(),
                    literal,
                ):
                    raise ValueError(
                        "range boundary requires an explicit scoped source declaration"
                    )
            elif actual == [] and type(actual) is list and draft.schema_version in {5, 6, 7}:
                labels = {
                    "ordinary_rules": "普通规则",
                    "risk_branches": "风险分支",
                    "alert_rules": "提醒规则",
                }
                name = labels.get(binding.path)
                literal = excerpt.strip(" \t\r\n。；;.")
                if name is None or not re.fullmatch(
                    rf"(?:{re.escape(binding.path)}\s*=\s*\[\]|无{name})",
                    literal,
                ):
                    raise ValueError("empty rules require an explicit scoped source declaration")
            elif isinstance(actual, bool | list) or str(actual) not in excerpt:
                raise ValueError("source value requires an explicit scoped human definition")
        bound.add(binding.path)
    if used != set(supplements):
        raise ValueError("orphan human supplement")
    issues = list(daily_draft_issues(draft))
    issues.extend(_persistent_deadline_issues(draft, mapping))
    unbound_paths = values.keys() - bound
    for path in sorted(unbound_paths) if draft.schema_version in {5, 6, 7} else unbound_paths:
        issues.append(
            {
                "path": path,
                "code": "DAILY_SOURCE_BINDING_REQUIRED",
                "reason": "Bind this exact policy value to source or a scoped human supplement.",
            }
        )
    for clause in mapping.clauses:
        if clause.semantic_role == "AMBIGUOUS":
            issues.append({"path": "source." + clause.clause_id,
                           "code": "SOURCE_CONTENT_AMBIGUOUS", "reason": clause.reason})
        if any(path not in values for path in clause.paths):
            raise ValueError("source clause has unknown candidate path")
        if any(r.disposition != "POLICY" or not r.paths for r in clause.remainders):
            issues.append(
                {
                    "path": "source." + clause.clause_id,
                    "code": "DAILY_SOURCE_CLAUSE_REQUIRED",
                    "reason": "Define each remaining technical source span and its scoped paths.",
                }
            )
        if clause.disposition in {"UNRESOLVED", "UNSUPPORTED"} or (
            clause.disposition == "POLICY" and not clause.paths
        ):
            issues.append(
                {
                    "path": "source." + clause.clause_id,
                    "code": "DAILY_SOURCE_CLAUSE_REQUIRED",
                    "reason": clause.reason,
                }
            )
        elif clause.disposition == "INVENTORY_ASSERTION":
            require_inventory_assertion(clause.excerpt)
            # Such assertions never attest holdings or authorize a trade. Require a
            # scoped treatment rather than a generic ignore/acknowledgement label.
            if (
                clause.paths
                or len(clause.reason) < 20
                or any(
                    x in clause.reason.casefold() for x in ("ignore", "acknowledge", "忽略", "已阅")
                )
            ):
                raise ValueError("source treatment must explain the concrete non-policy assertion")
    return DailyReviewSnapshot(
        content_hash=digest,
        source_hash=sha256(source_text.encode()).hexdigest(),
        evidence_hash=daily_hash("daily-plan-review-evidence-v1", mapping.model_dump(mode="json")),
        mapping=mapping,
        issues=tuple(
            DailyReviewIssue(issue_id=daily_hash("daily-plan-review-issue-v1", issue), **issue)
            for issue in issues
        ),
    )
