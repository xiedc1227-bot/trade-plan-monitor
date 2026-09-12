from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.ai.models import (
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanMapping,
    SourceClause,
    UserSupplement,
)
from trade_plan_monitor.ai.review import (
    build_server_review_snapshot,
    dump_explicit_plan_draft_json,
    explicit_draft_content_sha256,
    explicit_draft_sha256,
    reconcile_plan_mapping,
    server_source_clauses,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SOURCE = (
    "003043.SZ现有100股且今日可卖，最高300股。"
    "五分钟收盘价在9.80至10.00元（含端点）且当前成交量不少于前5根已完成五分钟K线"
    "成交量算术平均值的1.5倍时买入100股；五分钟收盘价在10.80至11.00元（含端点）时卖出100股；"
    "五分钟收盘价低于9.50元时风险提醒。提醒和确认不代表成交。"
)


def _draft_payload() -> dict[str, object]:
    return {
        "schema_version": 3,
        "execution_mode": "EXPLICIT_RULES",
        "execution_version": "explicit-rules-v1",
        "plan_id": "synthetic-r11",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "SYNTHETIC R11",
        "market": "SZSE",
        "metadata": {},
        "activation": None,
        "position": {
            "inventory_scope": "ALL_REGISTERED",
            "lot_size": 100,
            "max_qty": 300,
        },
        "monitoring": {
            "timeframe_minutes": 5,
            "indicator_formula_version": "ta-v1",
        },
        "rules": [
            {
                "rule_id": "buy-100",
                "condition": {
                    "type": "ALL",
                    "conditions": [
                        {
                            "type": "COMPLETED_CLOSE_IN_RANGE",
                            "low_fen": 980,
                            "high_fen": 1000,
                            "include_low": True,
                            "include_high": True,
                        },
                        {
                            "type": "VOLUME_TO_MEAN_GTE",
                            "window_bars": 5,
                            "minimum_ratio": "1.5",
                            "history_scope": None,
                        },
                    ],
                },
                "action": {"type": "BUY", "quantity": 100},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": None,
                "safety_conditions": None,
            },
            {
                "rule_id": "sell-100",
                "condition": {
                    "type": "COMPLETED_CLOSE_IN_RANGE",
                    "low_fen": 1080,
                    "high_fen": 1100,
                    "include_low": True,
                    "include_high": True,
                },
                "action": {
                    "type": "SELL",
                    "quantity": 100,
                    "inventory_scope": "ALL_REGISTERED",
                },
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": None,
                "safety_conditions": None,
            },
            {
                "rule_id": "risk-950",
                "condition": {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 950},
                "action": {"type": "RISK_ALERT"},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": None,
                "safety_conditions": None,
            },
        ],
        "conflict_policy": None,
    }


def _draft() -> ExplicitPlanDraft:
    return ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload()))


def _mapping_for_source(source: str, *, mapped: bool = False) -> PlanMapping:
    clauses = server_source_clauses(source)
    return PlanMapping(
        source_clauses=tuple(
            clause.model_copy(
                update={
                    "disposition": (
                        ClauseDisposition.MAPPED if mapped else ClauseDisposition.UNRESOLVED
                    ),
                    "paths": ("symbol",) if mapped else (),
                }
            )
            for clause in clauses
        ),
        field_bindings=(
            FieldBinding(
                path="symbol",
                value="003043.SZ",
                unit=BindingUnit.NONE,
                origin=BindingOrigin.SOURCE,
                clause_ids=(clauses[0].clause_id,),
            ),
        )
        if mapped
        else (),
    )


def test_partial_explicit_draft_preserves_typed_nulls_and_canonical_identity() -> None:
    draft = _draft()

    assert draft.activation is None
    assert draft.rules[0].repeat_policy is None
    assert draft.rules[0].condition.conditions[1].history_scope is None
    assert draft.conflict_policy is None
    assert draft.to_executable() is None
    assert explicit_draft_sha256(draft) == explicit_draft_sha256(draft)
    assert dump_explicit_plan_draft_json(draft).startswith('{"activation":null,')


def test_content_hash_excludes_only_version_name_metadata_and_plan_id() -> None:
    draft = _draft()
    metadata_only = ExplicitPlanDraft.model_validate_json(
        json.dumps(
            draft.model_dump(mode="json")
            | {"plan_id": "other", "version": 2, "name": "OTHER", "metadata": {}}
        )
    )
    semantic = ExplicitPlanDraft.model_validate_json(
        json.dumps(
            draft.model_dump(mode="json")
            | {
                "position": {
                    "inventory_scope": "ALL_REGISTERED",
                    "lot_size": 100,
                    "max_qty": 400,
                }
            }
        )
    )

    assert explicit_draft_content_sha256(metadata_only) == explicit_draft_content_sha256(draft)
    assert explicit_draft_sha256(metadata_only) != explicit_draft_sha256(draft)
    assert explicit_draft_content_sha256(semantic) != explicit_draft_content_sha256(draft)


def test_server_clause_offsets_are_unicode_codepoints_and_cover_exact_source() -> None:
    source = "企稳后买入。🙂放量突破；收盘受阻"
    clauses = server_source_clauses(source)

    assert "".join(clause.excerpt for clause in clauses) == source
    assert all(source[item.start : item.end] == item.excerpt for item in clauses)
    assert len({item.clause_id for item in clauses}) == len(clauses)


def test_mapping_rejects_duplicate_clause_ids_and_unknown_binding_origins() -> None:
    clause = SourceClause(
        clause_id="clause-0000000000000001",
        start=0,
        end=4,
        excerpt="测试文本",
        disposition=ClauseDisposition.UNRESOLVED,
        paths=(),
    )
    with pytest.raises(ValidationError):
        PlanMapping(
            source_clauses=(clause, clause),
            field_bindings=(),
        )
    with pytest.raises(ValidationError):
        FieldBinding(
            path="rules[0].action.quantity",
            value=100,
            unit=BindingUnit.SHARES,
            origin=BindingOrigin.CONTRACT,
            contract_id="schema-literal",
        )


def test_mapping_rejects_a_business_value_with_the_wrong_unit() -> None:
    source = "买入100股。"
    clause = server_source_clauses(source)[0]
    mapping = PlanMapping(
        source_clauses=(
            clause.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED,
                    "paths": ("rules[0].action.quantity",),
                }
            ),
        ),
        field_bindings=(
            FieldBinding(
                path="rules[0].action.quantity",
                value=100,
                unit=BindingUnit.FEN,
                origin=BindingOrigin.SOURCE,
                clause_ids=(clause.clause_id,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="unit"):
        build_server_review_snapshot(
            source_text=source,
            draft=_draft(),
            mapping=mapping,
        )


def test_reconcile_keeps_unreferenced_source_clauses_unresolved() -> None:
    source = "买入100股。提醒和确认不代表成交。"
    mapped, unresolved = server_source_clauses(source)
    mapping = PlanMapping(
        source_clauses=(
            mapped.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED,
                    "paths": ("rules[0].action.quantity",),
                }
            ),
            unresolved,
        ),
        field_bindings=(
            FieldBinding(
                path="rules[0].action.quantity",
                value=100,
                unit=BindingUnit.SHARES,
                origin=BindingOrigin.SOURCE,
                clause_ids=(mapped.clause_id,),
            ),
        ),
    )

    reconciled = reconcile_plan_mapping(draft=_draft(), mapping=mapping)

    assert reconciled.source_clauses[0].disposition is ClauseDisposition.MAPPED
    assert reconciled.source_clauses[1].disposition is ClauseDisposition.UNRESOLVED
    assert reconciled.source_clauses[1].paths == ()


def test_server_snapshot_reports_every_unresolved_policy_without_client_issue_input() -> None:
    snapshot = build_server_review_snapshot(
        source_text=_SOURCE,
        draft=_draft(),
        mapping=_mapping_for_source(_SOURCE),
    )
    codes_and_paths = {(issue.code, issue.path) for issue in snapshot.required_issues}

    assert ("UNRESOLVED_EXECUTION_POLICY", "activation") in codes_and_paths
    assert ("UNRESOLVED_EXECUTION_POLICY", "rules[0].repeat_policy") in codes_and_paths
    assert ("UNRESOLVED_EXECUTION_POLICY", "rules[1].repeat_policy") in codes_and_paths
    assert ("UNRESOLVED_EXECUTION_POLICY", "rules[2].repeat_policy") in codes_and_paths
    assert ("UNRESOLVED_EXECUTION_POLICY", "conflict_policy") in codes_and_paths
    assert snapshot.can_activate is False
    assert snapshot.source_hash == __import__("hashlib").sha256(_SOURCE.encode()).hexdigest()


def test_absent_optional_safety_conditions_do_not_create_execution_policy_issues() -> None:
    snapshot = build_server_review_snapshot(
        source_text=_SOURCE,
        draft=_draft(),
        mapping=_mapping_for_source(_SOURCE),
    )

    unresolved_paths = {
        issue.path
        for issue in snapshot.required_issues
        if issue.code == "UNRESOLVED_EXECUTION_POLICY"
    }
    assert not {path for path in unresolved_paths if path.endswith(".safety_conditions")}


def test_ambiguous_and_unsupported_phrases_cannot_become_generic_confirmations() -> None:
    source = "企稳后买入，放量突破；先买入再卖出；有效跌破9.50元时提醒。"
    snapshot = build_server_review_snapshot(
        source_text=source,
        draft=_draft(),
        mapping=_mapping_for_source(source, mapped=True),
    )
    semantic = [
        issue
        for issue in snapshot.required_issues
        if issue.code in {"UNRESOLVED_SEMANTICS", "UNSUPPORTED_SEMANTICS"}
    ]

    assert {issue.code for issue in semantic} >= {
        "UNRESOLVED_SEMANTICS",
        "UNSUPPORTED_SEMANTICS",
    }
    assert all("CONFIRM_MAPPING" not in issue.allowed_resolutions for issue in semantic)


def test_explicit_five_minute_context_qualifies_the_following_close_clause() -> None:
    source = "仅监控已完成5分钟K线；收盘价低于9.50元时发出风险提醒。"

    snapshot = build_server_review_snapshot(
        source_text=source,
        draft=_draft(),
        mapping=_mapping_for_source(source),
    )

    assert not [
        issue for issue in snapshot.required_issues if "unqualified close" in issue.reason.lower()
    ]


def test_explicit_numeric_definitions_do_not_trigger_term_only_semantic_blockers() -> None:
    source = (
        "放量定义为当前已完成5分钟K线成交量不少于此前5根已完成5分钟K线成交量算术平均值的1.5倍；"
        "有效跌破定义为已完成5分钟K线收盘价低于9.50元；"
        "满足上述放量时买入100股；满足上述有效跌破时发出风险提醒。"
    )

    snapshot = build_server_review_snapshot(
        source_text=source,
        draft=_draft(),
        mapping=_mapping_for_source(source),
    )

    term_only_blockers = [
        issue
        for issue in snapshot.required_issues
        if "phrase 放量" in issue.reason or "unsupported confirmation or sequencing" in issue.reason
    ]
    assert term_only_blockers == []


def test_undefined_terms_remain_semantic_blockers() -> None:
    source = "价格企稳后买入100股；有效跌破9.50元时卖出100股。"

    snapshot = build_server_review_snapshot(
        source_text=source,
        draft=_draft(),
        mapping=_mapping_for_source(source),
    )

    codes = {issue.code for issue in snapshot.required_issues}
    assert {"UNRESOLVED_SEMANTICS", "UNSUPPORTED_SEMANTICS"} <= codes


def test_user_supplement_is_separate_from_source_and_participates_in_evidence_hash() -> None:
    mapping = _mapping_for_source(_SOURCE)
    snapshot = build_server_review_snapshot(
        source_text=_SOURCE,
        draft=_draft(),
        mapping=mapping,
    )
    supplement = UserSupplement(
        supplement_id="supplement-repeat-buy",
        path="rules[0].repeat_policy.mode",
        value="ONCE_PER_ACTIVATION",
        unit=BindingUnit.NONE,
        supplied_at=datetime(2026, 9, 12, 15, 0, tzinfo=_SHANGHAI),
        label="human_confirmed_test_supplement",
    )
    with_supplement = build_server_review_snapshot(
        source_text=_SOURCE,
        draft=_draft(),
        mapping=mapping.model_copy(update={"user_supplements": (supplement,)}),
    )

    assert with_supplement.review_evidence_hash != snapshot.review_evidence_hash
    assert _SOURCE == _SOURCE
