"""Unknown source fields cannot borrow the candidate rule's trade scope."""

import json

import pytest
from tests.unit.test_source_coverage_semantics import _native_baseline

from trade_plan_monitor.ai.daily_review import DailyClause, DailyMapping, build_daily_review
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage

_REQUIREMENT = "所有风险退出必须先等蓝灯亮起才能执行。"
_PATH = "ordinary_rules[0].unregistered_policy"


@pytest.mark.parametrize("value", [_REQUIREMENT, {"instruction": _REQUIREMENT}],
                         ids=["scalar", "container"])
def test_unmapped_free_policy_at_unknown_path_keeps_global_uncertainty(value):
    draft, source, original = _native_baseline()
    extra_start = len(source) + 1
    source += "\n" + _PATH + " = " + json.dumps(value, ensure_ascii=False)
    extra = tuple(DailyClause.model_validate(clause.model_dump() | dict(
        disposition="CONTEXT", semantic_role="COMMENTARY", paths=(),
        reason="Provider claims the additional source field is commentary",
    )) for clause in server_source_clauses(source) if clause.start >= extra_start)
    mapping = DailyMapping.model_validate(original.model_dump(mode="python") | dict(
        clauses=(*original.clauses, *extra),
    ))
    assert build_daily_review(draft, mapping, source).issues == ()

    result = assess_source_coverage(draft, mapping, source)

    assert result.status == "BLOCKED"
    assert result.authority_granted is False
    unknown = [row for row in result.obligations if any(
        path == _PATH or path.startswith(_PATH + ".") for path in row.paths
    )]
    assert unknown
    assert all(row.scope == "UNKNOWN" for row in unknown)
    assert all(row.excerpt == source[row.start:row.end] for row in unknown)
