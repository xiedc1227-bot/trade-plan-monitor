from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_plan_monitor.ai.models import (
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanMapping,
)
from trade_plan_monitor.ai.review import build_server_review_snapshot, server_source_clauses

_CORPUS_PATH = (
    Path(__file__).parents[1] / "fixtures" / "ai" / "explicit-plan-semantic-corpus-v1.json"
)
_SEMANTIC_CODES = frozenset({"UNRESOLVED_SEMANTICS", "UNSUPPORTED_SEMANTICS"})


def _draft() -> ExplicitPlanDraft:
    return ExplicitPlanDraft.model_validate_json(
        json.dumps(
            {
                "schema_version": 3,
                "execution_mode": "EXPLICIT_RULES",
                "execution_version": "explicit-rules-v1",
                "plan_id": "semantic-corpus",
                "version": 1,
                "symbol": "003043.SZ",
                "name": "Semantic corpus oracle",
                "market": "SZSE",
                "metadata": {},
                "activation": None,
                "position": {
                    "inventory_scope": None,
                    "lot_size": None,
                    "max_qty": None,
                },
                "monitoring": {"timeframe_minutes": None, "indicator_formula_version": None},
                "rules": [
                    {
                        "rule_id": "risk",
                        "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": None},
                        "action": {"type": "RISK_ALERT"},
                        "confirmation": None,
                        "repeat_policy": None,
                        "safety_conditions": None,
                    }
                ],
                "conflict_policy": None,
            },
            ensure_ascii=False,
        )
    )


def _cases() -> list[dict[str, object]]:
    return json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))


def test_semantic_corpus_has_the_independently_fixed_8_6_6_distribution() -> None:
    cases = _cases()
    assert len(cases) == 20
    assert {category: sum(item["category"] == category for item in cases) for category in {
        "EXPLICIT", "AMBIGUOUS", "UNSUPPORTED"
    }} == {"EXPLICIT": 8, "AMBIGUOUS": 6, "UNSUPPORTED": 6}
    assert len({item["id"] for item in cases}) == 20


@pytest.mark.parametrize("case", _cases(), ids=lambda item: str(item["id"]))
def test_server_semantic_gate_matches_the_independent_oracle(case: dict[str, object]) -> None:
    source_text = str(case["sourceText"])
    clauses = server_source_clauses(source_text)
    evidence_values = (
        ("symbol", "003043.SZ"),
        ("name", "Semantic corpus oracle"),
        ("plan_id", "semantic-corpus"),
        ("version", 1),
    )
    mapping = PlanMapping(
        source_clauses=tuple(
            clause.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED,
                    "paths": (evidence_values[index][0],),
                }
            )
            for index, clause in enumerate(clauses)
        ),
        field_bindings=tuple(
            FieldBinding(
                path=evidence_values[index][0],
                value=evidence_values[index][1],
                unit=BindingUnit.NONE,
                origin=BindingOrigin.SOURCE,
                clause_ids=(clause.clause_id,),
            )
            for index, clause in enumerate(clauses)
        ),
    )
    actual = sorted(
        {
            issue.code
            for issue in build_server_review_snapshot(
                draft=_draft(),
                mapping=mapping,
                source_text=source_text,
            ).required_issues
            if issue.code in _SEMANTIC_CODES
        }
    )
    assert actual == sorted(case["expectedSemanticCodes"])
