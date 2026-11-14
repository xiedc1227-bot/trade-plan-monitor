"""Trade scope comes from complete source evidence, never candidate intent."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_source_coverage_semantics import _native_baseline, _rebuilt_source

from trade_plan_monitor.ai.daily_review import DailyClause, DailyMapping, semantic_values
from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionOutput
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, SourceObligation
from trade_plan_monitor.domain.p3_validation import P3PlanDraft

_RULE = "ordinary_rules[0]"
_SIDE = _RULE + ".side"
_FROZEN_BARE = (
    ("symbol", "002240.SZ"), ("market", "SZSE"),
    (_RULE + ".status", "ENABLED"), (_SIDE, "BUY"), (_RULE + ".rule_id", "low-buy"),
    (_RULE + ".bucket", "TACTICAL"), (_RULE + ".condition.type", "MINUTE_CLOSE_BELOW"),
    (_RULE + ".confirmation.kind", "COMPLETED_BAR_CLOSE"),
    (_RULE + ".execution_window", "CURRENT_SESSION"),
    (_RULE + ".invalidation", "RISK_OR_REVIEWED_INVALIDATION"),
    (_RULE + ".independent_signal.mode", "REVIEWED_INDEPENDENT_EVENT"),
    (_RULE + ".independent_signal.evidence_requirement", "New structure linked to prior signal"),
)


def _rebuilt_rows(draft, original, rows, *, missing=None, one_ref_paths=()):
    """Give each row exact canonical spans; mappings cannot choose its true scope."""
    source = "\n".join(line for _, line, _ in rows)
    canonical = server_source_clauses(source)
    groups, owner, cursor = {}, {}, 0
    clauses = []
    for row_path, line, paths in rows:
        group = tuple(clause for clause in canonical if cursor <= clause.start < cursor + len(line))
        assert group
        groups[row_path] = group
        owner.update((path, row_path) for path in paths)
        clauses.extend(DailyClause.model_validate(clause.model_dump() | dict(
            disposition="POLICY", paths=paths, reason="Exact source declaration",
        )) for clause in group)
        cursor += len(line) + 1
    owner.update(missing or {})
    mapping = DailyMapping.model_validate(original.model_dump(mode="python") | dict(
        clauses=tuple(clauses),
        bindings=tuple(binding.model_copy(update={
            "clause_ids": tuple(clause.clause_id for clause in (
                groups[owner[binding.path]][:1] if binding.path in one_ref_paths
                else groups[owner[binding.path]]
            )),
        }) for binding in original.bindings),
    ))
    assert [(c.clause_id, c.start, c.end, c.excerpt) for c in mapping.clauses] == [
        (c.clause_id, c.start, c.end, c.excerpt) for c in canonical
    ]
    return source, mapping


def _ordinary_atoms(result, prefix=_RULE):
    return [row for row in result.obligations if any(
        path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[")
        for path in row.paths
    )]


def test_source_sell_candidate_buy_conflict_has_unknown_trade_scope():
    draft, _, original = _native_baseline()
    source, mapping, _ = _rebuilt_source(draft, original, replacements={_SIDE: "SELL"})

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def test_unstated_side_cannot_borrow_candidate_buy_scope():
    draft, _, original = _native_baseline()
    values = semantic_values(draft)
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items() if path != _SIDE]
    source, mapping = _rebuilt_rows(draft, original, rows, missing={
        _SIDE: _RULE + ".rule_id",
    })

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def test_conflicting_source_side_declarations_do_not_select_one_buy_claim():
    draft, _, original = _native_baseline()
    values = semantic_values(draft)
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items()]
    rows.append(("conflicting-side", f'{_SIDE} = "SELL"', (_SIDE,)))
    source, mapping = _rebuilt_rows(draft, original, rows)

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    atoms = _ordinary_atoms(result)
    assert atoms
    assert all(atom.scope == "UNKNOWN" for atom in atoms)


def _buy_and_sell_container():
    before, _, _ = _native_baseline()
    raw = before.model_dump(mode="json")
    sell = deepcopy(raw["ordinary_rules"][0])
    for key in ("market_policy", "quantity_policy", "pretrade_policy"):
        sell.pop(key)
    sell.update(side="SELL", rule_id="source-scoped-sell", quantity=100, zone="PRESSURE",
                condition=raw["alert_rules"][0]["condition"])
    raw["ordinary_rules"].append(sell)
    draft = P3PlanDraft.model_validate(raw)
    _, original = source_mapping(draft)
    values = semantic_values(draft)
    owned = tuple(path for path in values if path.startswith("ordinary_rules["))
    container = [rule.model_dump(mode="json") for rule in draft.ordinary_rules]
    rows = [(path, f"{path} = {json.dumps(value, ensure_ascii=False)}", (path,))
            for path, value in values.items() if path not in owned]
    rows.append(("ordinary_rules", "ordinary_rules = " + json.dumps(container), owned))
    # A container is one complete declaration; one genuine owning clause is a
    # bounded AI citation. The server must derive every child independently.
    source, mapping = _rebuilt_rows(draft, original, rows, one_ref_paths=owned)
    return draft, source, mapping


def test_complete_rules_container_scopes_each_native_atom_from_its_source_side():
    draft, source, mapping = _buy_and_sell_container()

    result = assess_source_coverage(draft, mapping, source)

    for index, side in enumerate(("BUY", "SELL")):
        atoms = _ordinary_atoms(result, f"ordinary_rules[{index}]")
        assert atoms
        assert all(atom.scope == side for atom in atoms)
        assert any(atom.kind == "RELATION" for atom in atoms)
        assert any(atom.kind == "PREDICATE" for atom in atoms)
    assert all(atom.excerpt == source[atom.start:atom.end] for atom in result.obligations)


def test_mapped_obligation_with_unknown_scope_cannot_make_current_complete():
    draft, source, mapping = _native_baseline()
    baseline = assess_source_coverage(draft, mapping, source)
    original = _ordinary_atoms(baseline)[0]
    unknown = SourceObligation.build(**(original.model_dump(mode="python", exclude={
        "obligation_id",
    }) | dict(scope="UNKNOWN", state="MAPPED")))

    result = CoverageAssessment.build(source_hash=baseline.source_hash,
        content_hash=baseline.content_hash, mapping_hash=baseline.mapping_hash,
        origin="AI_HISTORICAL", obligations=(unknown,), issues=())

    assert result.coverage_complete is False
    assert result.status == "BLOCKED"
    assert result.authority_granted is False


def test_unregistered_global_risk_requirement_inside_buy_keeps_unknown_scope():
    before, _, _ = _native_baseline()
    raw = before.model_dump(mode="json")
    path = _RULE + ".condition.conditions[0].evidence_requirement"
    requirement = "所有风险退出必须先等蓝灯亮起才能执行。"
    raw["ordinary_rules"][0]["condition"]["conditions"][0]["evidence_requirement"] = requirement
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    assert json.dumps(requirement, ensure_ascii=False) in source

    result = assess_source_coverage(draft, mapping, source)

    unknown = [atom for atom in result.obligations
               if path in atom.paths and atom.state == "UNRESOLVED"]
    assert result.status == "BLOCKED"
    assert result.authority_granted is False
    assert unknown
    assert all(atom.scope == "UNKNOWN" for atom in unknown)


def _monitor_loop_source():
    path = Path(__file__).parents[2] / "web/tests/fixtures/monitor-loop.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    output = LoopPlanExtractionOutput.model_validate_json(json.dumps(fixture["ai_output"]))
    return output.draft, fixture["source"]["text"]


def _monitor_proposal(draft, source, *, start=None, end=None, disposition="POLICY", role=None):
    """Rebuild real clause identities, retaining the original explicit human mapping values."""
    mapping = reviewed_mapping(draft, source)
    if start is not None:
        mapping = mapping.model_copy(update={"clauses": tuple(c.model_copy(update={
            "disposition": disposition, "semantic_role": role, "paths": (),
            "reason": "Untrusted proposed role; raw source remains independently checked",
        }) if c.start < end and c.end > start else c for c in mapping.clauses)})
    mapping = DailyMapping.model_validate_json(mapping.model_dump_json())
    assert [(c.clause_id, c.start, c.end, c.excerpt) for c in mapping.clauses] == [
        (c.clause_id, c.start, c.end, c.excerpt) for c in server_source_clauses(source)]
    return mapping


def test_exact_frozen_monitor_loop_human_mapping_has_complete_current_source_meaning():
    from hashlib import sha256

    from trade_plan_monitor.ai.daily_review import build_daily_review

    draft, source = _monitor_loop_source()
    mapping = _monitor_proposal(draft, source)
    assert sha256(source.encode()).hexdigest() == (
        "59dfb0208bd99f89d31665504435a66dc6b6687ee8f5066e32c5edf5e1955b04")
    assert build_daily_review(draft, mapping, source).issues == ()
    result = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert result.coverage_complete and result.status == "COMPLETE" and not result.issues
    assert result.authority_granted is False
    assert all(row.state != "UNRESOLVED" for row in result.obligations)


@pytest.mark.parametrize("path,value", _FROZEN_BARE)
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
def test_each_frozen_bare_leaf_cannot_be_erased_by_an_untrusted_role(
    path, value, role,
):
    draft, source = _monitor_loop_source()
    line = f"{path}={value}"
    start = source.index(line)
    mapping = _monitor_proposal(draft, source, start=start, end=start + len(line),
        disposition="CONTEXT", role=role)
    result = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    rows = [row for row in result.obligations if path in row.paths]
    assert result.coverage_complete and result.authority_granted is False
    assert rows and all(row.state == "MAPPED" for row in rows)
    assert all(row.scope == ("BUY" if path.startswith(_RULE) else "PLAN") for row in rows)
    assert all(source[row.start:row.end] == row.excerpt for row in rows)


@pytest.mark.parametrize("path,value", _FROZEN_BARE)
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
def test_background_bare_label_keeps_its_rejection_and_cannot_erase_the_raw_policy(
    path, value, role,
):
    draft, source = _monitor_loop_source()
    control = assess_source_coverage(
        draft, _monitor_proposal(draft, source), source, origin="HUMAN")
    assert control.coverage_complete and control.authority_granted is False
    line = f"{path}={value}"
    start = source.index(line)
    mapping = _monitor_proposal(draft, source, start=start, end=start + len(line),
        disposition="BACKGROUND", role=role)
    result = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert result.status == "BLOCKED" and result.authority_granted is False
    rows = [row for row in result.obligations if path in row.paths]
    assert rows and all(row.state == "MAPPED" for row in rows)
    assert all(row.scope == ("BUY" if path.startswith(_RULE) else "PLAN") for row in rows)
    assert all(source[row.start:row.end] == row.excerpt for row in rows)


@pytest.mark.parametrize("path,value", _FROZEN_BARE)
@pytest.mark.parametrize("tail", [
    " and only buy when turnover exceeds 3 percent", "; only buy when turnover exceeds 3 percent",
    "且仅当换手率超过3%才允许买入",
])
@pytest.mark.parametrize("role", ["ACCOUNT", "HISTORICAL", "COMMENTARY"])
@pytest.mark.parametrize("disposition", ["BACKGROUND", "CONTEXT"])
def test_every_new_bare_form_keeps_a_mandatory_tail_visible(path, value, tail, role, disposition):
    draft, source = _monitor_loop_source()
    control = assess_source_coverage(
        draft, _monitor_proposal(draft, source), source, origin="HUMAN")
    assert control.coverage_complete and control.authority_granted is False
    line = f"{path}={value}"
    start = source.index(line)
    changed = source[:start] + line + tail + source[start + len(line):]
    mapping = _monitor_proposal(draft, changed, start=start, end=start + len(line + tail),
        disposition=disposition, role=role)
    result = assess_source_coverage(draft, mapping, changed, origin="HUMAN")
    assert result.status == "BLOCKED" and not result.coverage_complete
    assert result.authority_granted is False
    local = [issue for issue in result.issues if issue.start is not None
             and start <= issue.start < start + len(line + tail)]
    assert local and all(0 <= issue.start < issue.end <= len(changed) for issue in local)
    assert any(row.state == "UNRESOLVED" and start <= row.start < start + len(line + tail)
               for row in result.obligations)


@pytest.mark.parametrize("path,invalid", [
    ("symbol", "002240.sz"), ("market", "szse"), (_RULE + ".status", "enabled"),
    (_SIDE, "NOT_BUY"), (_RULE + ".rule_id", "other-rule"), (_RULE + ".bucket", "CORE"),
    (_RULE + ".condition.type", "UNKNOWN_CONDITION"),
    (_RULE + ".confirmation.kind", "UNKNOWN_CLOSE"), (_RULE + ".execution_window", "ANY_TIME"),
    (_RULE + ".invalidation", "NEVER"), (_RULE + ".independent_signal.mode", "ONCE"),
    (_RULE + ".independent_signal.evidence_requirement",
     "Not New structure linked to prior signal"),
])
def test_unknown_or_conflicting_bare_values_cannot_borrow_the_candidate(path, invalid):
    draft, source = _monitor_loop_source()
    control = assess_source_coverage(
        draft, _monitor_proposal(draft, source), source, origin="HUMAN")
    assert control.coverage_complete and control.authority_granted is False
    original = next(value for key, value in _FROZEN_BARE if key == path)
    line = f"{path}={original}"
    changed = source.replace(line, f"{path}={invalid}", 1)
    start = changed.index(path + "=")
    mapping = _monitor_proposal(draft, changed, start=start, end=start + len(path + "=" + invalid),
        disposition="CONTEXT", role="COMMENTARY")
    result = assess_source_coverage(draft, mapping, changed, origin="HUMAN")
    assert result.status == "BLOCKED" and result.authority_granted is False
    assert any(row.start <= start < row.end and row.state in {"UNRESOLVED", "CONFLICT"}
               for row in result.obligations)


@pytest.mark.parametrize("change", ["SELL", "missing", "duplicate"])
def test_bare_source_side_is_independent_of_candidate_and_human_supplements(change):
    draft, source = _monitor_loop_source()
    control = assess_source_coverage(
        draft, _monitor_proposal(draft, source), source, origin="HUMAN")
    assert control.coverage_complete and control.authority_granted is False
    line = _SIDE + "=BUY"
    if change == "SELL":
        source = source.replace(line, _SIDE + "=SELL")
    elif change == "missing":
        source = source.replace(line + "\n", "")
    else:
        source += "\n" + _SIDE + "=SELL"
    result = assess_source_coverage(draft, _monitor_proposal(draft, source), source, origin="HUMAN")
    assert result.status == "BLOCKED" and result.authority_granted is False
    atoms = _ordinary_atoms(result)
    assert atoms and all(row.scope == "UNKNOWN" for row in atoms)
