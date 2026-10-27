"""Finite three-column mixed risk tables; neither atom is executable authority."""

import re
from collections import Counter
from decimal import Decimal

from pydantic import ValidationError

from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_obligations import bounded_clauses
from trade_plan_monitor.ai.source_risk_control_models import SourceRiskControlSpan
from trade_plan_monitor.ai.source_risk_controls import derive_source_risk_control
from trade_plan_monitor.ai.source_risk_table_models import (
    RiskTableFraming,
    SourceRiskTableAnalysis,
    SourceRiskTableGroup,
    StructuralRecoveryReference,
    risk_table_frame_id,
    risk_table_group_id,
)
from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.risk_scope import risk_identity

_HEADING = re.compile(r"## [1-9][0-9]{0,2}\. 核心价格位置更新")
_PRICE = re.compile(r"(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,2})?")
_SEPARATOR = re.compile(r":?-{3,}:?")
_MEANING = "已失守的原核心风险线；现在用于判断旧结构是否被重新收复，而不是给新仓位直接设止损"


def _cells(text, *, unwrap=True):
    text = text.strip(" \t")
    parts = text.split("|")
    if len(parts) != 5 or parts[0] or parts[-1]:
        return None
    cells = []
    for cell in parts[1:-1]:
        cell = cell.strip(" \t")
        if unwrap and cell.startswith("**") and cell.endswith("**") and cell.count("**") == 2:
            cell = cell[2:-2]
        elif "**" in cell:
            return None
        cells.append(cell)
    return tuple(cells)


def _price_row(text):
    cells = _cells(text)
    if (cells is None or cells[0] != "结构修复门槛" or cells[2] != _MEANING
            or _PRICE.fullmatch(cells[1]) is None):
        return None
    value = int(Decimal(cells[1]) * 100)
    return value if 0 < value <= 9_007_199_254_740_991 else None


class _Boundary:
    """Lexical closure only; unknown prose still remains in the returned ledger."""

    def __init__(self):
        self.pending = False
        self.quotes = []

    @property
    def closed(self):
        return not self.pending and not self.quotes

    def feed(self, text):
        openers = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
        cursor = 0
        while cursor < len(text):
            char = text[cursor]
            if self.quotes and char == "\\":
                cursor += 2
                continue
            if char == "`":
                stop = cursor + 1
                while stop < len(text) and text[stop] == "`":
                    stop += 1
                marker = text[cursor:stop]
                if self.quotes and self.quotes[-1] == marker:
                    self.quotes.pop()
                else:
                    self.quotes.append(marker)
                self.pending = True
                cursor = stop
                continue
            if not self.quotes and text[cursor:cursor + 2] == "**":
                cursor += 2  # Formatting never deletes text from the UNKNOWN ledger.
                continue
            if self.quotes and char == self.quotes[-1]:
                self.quotes.pop()
            elif char in openers:
                self.quotes.append(openers[char])
            elif not self.quotes and (char in "。！？!?" or char == "."
                                     and (cursor + 1 == len(text) or text[cursor + 1].isspace())):
                self.pending = False
                cursor += 1
                continue
            elif not char.isspace():
                self.pending = True
            cursor += 1


def _parent_price(base, fen):
    levels = base.draft.levels
    global_price = None if levels is None else levels.risk_line_fen
    global_comparator = None if levels is None else levels.risk_comparison
    matches = []
    for index, branch in enumerate(base.draft.risk_branches):
        if branch.kind != "ORDINARY_TECHNICAL":
            continue
        price = branch.risk_line_fen
        comparator = branch.risk_comparison
        if price is not None and global_price is not None and (
            price != global_price or comparator != global_comparator
        ):
            return None  # A price-role contradiction is not a unique source reference.
        if price is None:
            price, comparator, path = global_price, global_comparator, "levels.risk_line_fen"
        else:
            path = f"risk_branches[{index}].risk_line_fen"
        if price == fen and comparator in {"LT", "LTE"}:
            matches.append((risk_identity(branch), path))
    return matches[0] if len(matches) == 1 else None


def _group(source, base, parent, frame_id, start, end, price):
    selected = _parent_price(base, price)
    if selected is None:
        return None
    identifier, path = selected
    control = derive_source_risk_control(source, base, parent,
        grammar_id="RISK_TABLE_EXISTING_ONLY_ZH_V1", rule_id=identifier, action="MODIFY",
        scope_change="EXISTING_POSITIONS_ONLY", start=start, end=end)
    if control is None:
        return None
    identity = risk_table_group_id(frame_id, control.control_id, price, path)
    role = StructuralRecoveryReference.build(source_id=source.source_id,
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        parent_assurance_hash=parent.evidence_hash, base_review_hash=base.evidence_hash,
        start=start, end=end, excerpt=source.text[start:end], group_id=identity,
        scope_control_id=control.control_id, price_fen=price, parent_price_path=path)
    return SourceRiskTableGroup(frame_id=frame_id, group_id=identity, scope_control=control,
                               structural_reference=role)


def parse_source_risk_table_controls(source, base_review, verified_parent):
    """Keep scope and structural-price meanings separate, with no coverage verdict.

    The only heading production is ``## N. 核心价格位置更新`` (N=1..999).
    It cannot close an unfinished antecedent/quote/fence. Other prose and table
    rows remain UNKNOWN, even when adjacent to a positively recognized row.
    """
    source = PreparationSource.model_validate_json(source.model_dump_json())
    bounded_clauses(source.text)
    base = PlanCandidateReview.model_validate_json(base_review.model_dump_json())
    parent = SourceCandidateAssurance.model_validate_json(verified_parent.model_dump_json())
    if (parent.binding.review_evidence_hash != base.evidence_hash
            or parent.content_hash != daily_draft_content_sha256(base.draft)
            or parent.binding.source_id != base.source_id
            or parent.binding.source_binding_hash != base.source_hash):
        raise ValueError("risk table differs from its exact verified parent")
    lines = list(re.finditer(r"[^\r\n]*", source.text))
    lines = [line for line in lines if line.start() < line.end()]
    groups, framing, unresolved, issues = [], [], [], []
    boundary, active_frame, cursor = _Boundary(), None, 0

    def unknown(start, end):
        for offset in range(start, end, 512):
            stop = min(offset + 512, end)
            unresolved.append(SourceRiskControlSpan(source_hash=source.source_hash,
                start=offset, end=stop, excerpt=source.text[offset:stop]))
            if len(unresolved) > 4096:
                raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")

    def syntax(line, kind):
        if len(line.group()) > 512 or len(framing) >= 512:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        row = RiskTableFraming(source_hash=source.source_hash, start=line.start(), end=line.end(),
                               excerpt=line.group(), kind=kind)
        framing.append(row)
        return row

    if not parent.coverage_complete:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
            message="Risk table meanings require a complete current predecessor proof."))
    while cursor < len(lines):
        line = lines[cursor]
        text = line.group()
        if cursor and source.text[lines[cursor - 1].end():line.start()].count("\n") > 1:
            active_frame = None
        stripped = text.strip(" \t")
        cells = _cells(text)
        if (boundary.closed and cells == ("位置", "价格", "当前含义")
                and cursor + 1 < len(lines)):
            separator = lines[cursor + 1]
            separator_cells = _cells(separator.group(), unwrap=False)
            adjacent = source.text[line.end():separator.start()] in {"\n", "\r\n"}
            if (adjacent and separator_cells is not None
                    and all(_SEPARATOR.fullmatch(value) for value in separator_cells)):
                header = syntax(line, "HEADER")
                rule = syntax(separator, "SEPARATOR")
                active_frame = risk_table_frame_id(header, rule)
                cursor += 2
                continue
        if (active_frame is not None and boundary.closed
                and stripped.startswith("|") and stripped.endswith("|")):
            price = _price_row(text)
            group = None
            if price is not None and len(text) <= 512 and parent.coverage_complete:
                try:
                    group = _group(source, base, parent, active_frame,
                                   line.start(), line.end(), price)
                except ValueError as error:
                    limit = "SOURCE_COVERAGE_LIMIT_EXCEEDED"
                    if str(error) == limit or isinstance(error, ValidationError) and any(
                        str(row.get("ctx", {}).get("error")) == limit
                        for row in error.errors(include_input=False, include_url=False)
                    ):
                        raise ValueError(limit) from error
                    issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
                        start=line.start(), end=line.end(), path="risk_branches",
                        message="The mixed risk row has no exact applicability derivation."))
            if group is None:
                unknown(line.start(), line.end())
                boundary.feed(text)
                if not boundary.quotes:
                    # A complete pipe row owns its unknown cells. Open quotes or
                    # fences still own subsequent lines, including other rows.
                    boundary.pending = False
            else:
                groups.append(group)
                if len(groups) > 64:
                    raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
            cursor += 1
            continue
        active_frame = None
        if boundary.closed and _HEADING.fullmatch(stripped):
            syntax(line, "HEADING")
        else:
            unknown(line.start(), line.end())
            boundary.feed(text)
        cursor += 1
    counts = Counter(group.scope_control.rule_id for group in groups)
    kept = []
    for group in groups:
        if counts[group.scope_control.rule_id] > 1:
            unknown(group.scope_control.start, group.scope_control.end)
        else:
            kept.append(group)
    if len(kept) != len(groups):
        issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
            message="Repeated mixed risk rows cannot select independent scope authority."))
    return SourceRiskTableAnalysis.build(source_id=source.source_id,
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        source_length=len(source.text), effective_trade_date=source.effective_trade_date,
        parent_assurance_hash=parent.evidence_hash, base_review_hash=base.evidence_hash,
        framing=tuple(framing), groups=tuple(kept),
        unresolved=tuple(sorted(unresolved, key=lambda row: row.start)), issues=tuple(issues))
