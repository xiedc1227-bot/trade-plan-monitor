from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from trade_plan_monitor.ai.models import (
    BindingKind,
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    FieldBinding,
    PlanExtractionResult,
    PlanExtractionStatus,
    PlanMapping,
    UserSupplement,
)
from trade_plan_monitor.ai.review import (
    dump_explicit_plan_draft_json,
    server_source_clauses,
)
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_NOW = datetime(2026, 9, 12, 16, 0, tzinfo=_SHANGHAI)
_PROVIDER_ID = UUID("04f3e4f5-7b55-4d61-a9ea-119d0db5c9a7")
_EXTRACTION_ID = UUID("06e3613f-2aa9-481a-8b7e-b6d66230f09d")
_SOURCE = (
    "003043.SZ 已有可卖100股 最高300股 五分钟完成收盘9.80到10.00元含端点"
    "并且成交量不少于前5根已完成五分钟K线算术平均值1.5倍买入100股 "
    "五分钟完成收盘10.80到11.00元含端点卖出100股 五分钟完成收盘低于9.50元风险提醒 "
    "人工选择手动有效 每条规则每次激活只提醒一次 同时交易冲突阻止两者 风险冲突仅保留风险"
)
# Historical derived shorthand, NOT the literal user source. Kept as regression coverage.
_ORIGINAL_SOURCE = (
    "003043.SZ现有100股且今日可卖，最高300股。"
    "五分钟收盘价在9.80至10.00元（含端点）且当前成交量不少于前5根已完成五分钟K线"
    "成交量算术平均值的1.5倍时买入100股；五分钟收盘价在10.80至11.00元（含端点）时卖出100股；"
    "五分钟收盘价低于9.50元时风险提醒。提醒和确认不代表成交。"
)
_HUMAN_SUPPLEMENT_PATHS = {
    "activation.mode",
    "rules[0].condition.conditions[1].history_scope",
    "rules[0].repeat_policy.mode",
    "rules[1].repeat_policy.mode",
    "rules[2].repeat_policy.mode",
    "conflict_policy.trade_conflict",
    "conflict_policy.risk_conflict",
}


class _Runtime:
    async def start(self) -> object:
        return object()

    async def stop(self) -> None:
        return None


def _draft_payload(*, complete: bool = True) -> dict[str, object]:
    repeat = {"mode": "ONCE_PER_ACTIVATION"} if complete else None
    return {
        "schema_version": 3,
        "execution_mode": "EXPLICIT_RULES",
        "execution_version": "explicit-rules-v1",
        "plan_id": "synthetic-r11-api",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "SYNTHETIC R11 API",
        "market": "SZSE",
        "metadata": {},
        "activation": {"mode": "MANUAL"} if complete else None,
        "position": {
            "inventory_scope": "ALL_REGISTERED",
            "lot_size": 100,
            "max_qty": 300,
        },
        "monitoring": {"timeframe_minutes": 5, "indicator_formula_version": "ta-v1"},
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
                            "history_scope": ("CONTIGUOUS_TRADING_BARS" if complete else None),
                        },
                    ],
                },
                "action": {"type": "BUY", "quantity": 100},
                "confirmation": {
                    "kind": "COMPLETED_BAR_CLOSE",
                    "timeframe_minutes": 5,
                },
                "repeat_policy": repeat,
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
                "repeat_policy": repeat,
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
                "repeat_policy": repeat,
                "safety_conditions": None,
            },
        ],
        "conflict_policy": (
            {"trade_conflict": "BLOCK_BOTH", "risk_conflict": "RISK_ONLY"} if complete else None
        ),
    }


def _scalar_paths(value: object, path: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            for item in _scalar_paths(child, f"{path}.{key}" if path else key)
        ]
    if isinstance(value, list):
        return [
            item
            for index, child in enumerate(value)
            for item in _scalar_paths(child, f"{path}[{index}]")
        ]
    return [] if value is None else [(path, value)]


def _logical_paths(value: object, path: str = "") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if value.get("type") in {"ALL", "ANY"}:
            result.append((path, str(value["type"])))
        for key, child in value.items():
            result.extend(_logical_paths(child, f"{path}.{key}" if path else key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_logical_paths(child, f"{path}[{index}]"))
    return result


def _get_path(value: object, path: str) -> object:
    current = value
    for part in path.replace("]", "").replace("[", ".").split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _unit(path: str) -> BindingUnit:
    if path.endswith("_fen"):
        return BindingUnit.FEN
    if path.endswith("quantity") or path.endswith("max_qty") or path.endswith("lot_size"):
        return BindingUnit.SHARES
    if path.endswith("window_bars"):
        return BindingUnit.BARS
    if path.endswith("timeframe_minutes"):
        return BindingUnit.MINUTES
    if path.endswith("ratio"):
        return BindingUnit.RATIO
    return BindingUnit.NONE


def _is_contract(path: str) -> bool:
    return path in {
        "schema_version",
        "execution_mode",
        "execution_version",
        "plan_id",
        "version",
        "name",
        "market",
        "position.inventory_scope",
        "position.lot_size",
        "monitoring.indicator_formula_version",
    } or path.endswith(".rule_id")


def _mapping(draft: ExplicitPlanDraft) -> PlanMapping:
    [clause] = server_source_clauses(_SOURCE)
    data = draft.model_dump(mode="json")
    source_paths: list[str] = []
    bindings: list[FieldBinding] = []
    for path, value in _scalar_paths(data):
        if _is_contract(path):
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.CONTRACT,
                    contract_id="explicit-rules-v1",
                )
            )
        else:
            source_paths.append(path)
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.SOURCE,
                    clause_ids=(clause.clause_id,),
                )
            )
    for path, value in _logical_paths(data):
        source_paths.append(path)
        bindings.append(
            FieldBinding(
                path=path,
                value=value,
                unit=BindingUnit.NONE,
                origin=BindingOrigin.SOURCE,
                binding_kind=BindingKind.STRUCTURE,
                clause_ids=(clause.clause_id,),
            )
        )
    return PlanMapping(
        source_clauses=(
            clause.model_copy(
                update={
                    "disposition": ClauseDisposition.MAPPED,
                    "paths": tuple(source_paths),
                }
            ),
        ),
        field_bindings=tuple(bindings),
        user_supplements=(),
    )


def _original_mapping(draft: ExplicitPlanDraft, *, with_human_supplements: bool) -> PlanMapping:
    clauses = server_source_clauses(_ORIGINAL_SOURCE)
    data = draft.model_dump(mode="json")
    paths_by_clause: dict[int, list[str]] = {index: [] for index in range(len(clauses))}
    bindings: list[FieldBinding] = []
    supplements: list[UserSupplement] = []

    def source_clause_index(path: str) -> int:
        if path == "position.max_qty":
            return 1
        if path == "monitoring.timeframe_minutes" or path.startswith("rules[0]."):
            return 2
        if path.startswith("rules[1]."):
            return 3
        if path.startswith("rules[2]."):
            return 4
        raise AssertionError(f"No original-source clause assigned for {path}")

    for path, value in _scalar_paths(data):
        if path == "symbol":
            # The unchanged first clause also asserts current sellable inventory.
            # Leave the combined clause unresolved instead of pretending that
            # mapping only its symbol captures the clause's full meaning.
            continue
        if _is_contract(path):
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.CONTRACT,
                    contract_id="explicit-rules-v1",
                )
            )
        elif with_human_supplements and path in _HUMAN_SUPPLEMENT_PATHS:
            supplement = UserSupplement(
                supplement_id=f"human-{len(supplements) + 1}",
                path=path,
                value=value,
                unit=_unit(path),
                supplied_at=_NOW,
                label="human_confirmed_supplement",
            )
            supplements.append(supplement)
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.USER_SUPPLEMENT,
                    supplement_id=supplement.supplement_id,
                )
            )
        else:
            clause_index = source_clause_index(path)
            paths_by_clause[clause_index].append(path)
            bindings.append(
                FieldBinding(
                    path=path,
                    value=value,
                    unit=_unit(path),
                    origin=BindingOrigin.SOURCE,
                    clause_ids=(clauses[clause_index].clause_id,),
                )
            )

    for path, value in _logical_paths(data):
        clause_index = source_clause_index(path)
        paths_by_clause[clause_index].append(path)
        bindings.append(
            FieldBinding(
                path=path,
                value=value,
                unit=BindingUnit.NONE,
                origin=BindingOrigin.SOURCE,
                binding_kind=BindingKind.STRUCTURE,
                clause_ids=(clauses[clause_index].clause_id,),
            )
        )

    source_clauses = tuple(
        clause.model_copy(
            update={
                "disposition": (
                    ClauseDisposition.MAPPED
                    if paths_by_clause[index]
                    else ClauseDisposition.UNRESOLVED
                ),
                "paths": tuple(paths_by_clause[index]),
            }
        )
        for index, clause in enumerate(clauses)
    )
    return PlanMapping(
        source_clauses=source_clauses,
        field_bindings=tuple(bindings),
        user_supplements=tuple(supplements),
    )


def _record_extraction(
    lifecycle: PersistentPlanWebLifecycle,
    draft: ExplicitPlanDraft,
    *,
    source_text: str = _SOURCE,
    mapping: PlanMapping | None = None,
) -> None:
    mapping = mapping or _mapping(draft)
    result = PlanExtractionResult(
        request_id=_EXTRACTION_ID,
        provider_id=_PROVIDER_ID,
        model="offline-v4",
        prompt_version="plan-extract-v4",
        source_text_sha256=__import__("hashlib").sha256(source_text.encode()).hexdigest(),
        draft=draft,
        mapping=mapping,
        usage=None,
        status=PlanExtractionStatus.SUCCEEDED,
    )
    import asyncio

    asyncio.run(lifecycle.record_plan_extraction(result))


def _app(database_path: Path) -> tuple[object, PersistentPlanWebLifecycle]:
    lifecycle = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _NOW)
    return create_app(runtime_factory=_Runtime, plan_lifecycle_factory=lambda: lifecycle), lifecycle


def _confirmation_resolutions(detail: dict[str, object]) -> list[dict[str, object]]:
    supplements = {
        item["path"]: item["supplementId"] for item in detail["mapping"]["userSupplements"]
    }
    resolutions = []
    for issue in detail["requiredReviewIssues"]:
        resolution = issue["allowedResolutions"][0]
        item = {"issueId": issue["issueId"], "resolution": resolution}
        if resolution == "CONFIRM_MAPPING":
            item["bindingPath"] = issue["bindingPath"]
        elif resolution == "CONFIRM_POLICY":
            item["supplementId"] = supplements.get(issue["path"])
        resolutions.append(item)
    return resolutions


def test_v4_extraction_save_review_and_public_activation_gate_are_server_bound(
    tmp_path: Path,
) -> None:
    app, lifecycle = _app(tmp_path / "review.sqlite3")
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload()))

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        _record_extraction(lifecycle, draft)
        saved = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "save-explicit-review"},
            json={
                "extractionId": str(_EXTRACTION_ID),
                "planJson": dump_explicit_plan_draft_json(draft),
                "sourceText": _SOURCE,
                "expectedRevision": 0,
            },
        )
        assert saved.status_code == 200
        detail = saved.json()
        assert detail["canActivate"] is False
        assert detail["contentHash"]
        assert detail["sourceHash"]
        assert detail["reviewEvidenceHash"]
        assert detail["reviewRevision"] == 0
        assert detail["reviewId"] is None
        assert detail["requiredReviewIssues"]
        assert detail["mapping"]["mappingVersion"] == "plan-mapping-v2"

        omitted = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-omitted-issues"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": detail["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": [],
            },
        )
        assert omitted.status_code == 200
        assert omitted.json()["canActivate"] is False
        assert omitted.json()["reviewId"] is None

        forged_issue = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-forged-issue"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": detail["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": [
                    {
                        "issueId": "issue-000000000000000000000000",
                        "resolution": "CONFIRM_MAPPING",
                        "bindingPath": "symbol",
                    }
                ],
            },
        )
        assert forged_issue.status_code == 422

        forged_evidence = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-forged-evidence"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": "e" * 64,
                "expectedRevision": 0,
                "resolutions": [],
            },
        )
        assert forged_evidence.status_code == 409

        reviewed = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-all-current"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": detail["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": _confirmation_resolutions(detail),
            },
        )
        assert reviewed.status_code == 200
        approved = reviewed.json()
        assert approved["canActivate"] is True
        assert approved["reviewId"] is not None
        assert approved["revision"] == 1

        stale_revision = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-stale-revision"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": detail["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": [],
            },
        )
        assert stale_revision.status_code == 409

        missing_binding = client.post(
            "/api/v1/plan-activations",
            headers={"Idempotency-Key": "activate-without-review-binding"},
            json={"planVersionId": detail["id"], "expectedRevision": 0},
        )
        assert missing_binding.status_code == 409
        public_gate = client.post(
            "/api/v1/plan-activations",
            headers={"Idempotency-Key": "activate-current-review"},
            json={
                "planVersionId": detail["id"],
                "reviewId": approved["reviewId"],
                "contentHash": detail["contentHash"],
                "expectedRevision": 0,
            },
        )
        assert public_gate.status_code == 409
        capability = client.get("/api/v1/plan-capabilities").json()
        assert capability["publicActivationAvailable"] is False
        assert capability["pendingRequirements"] == ["ORDINARY_PLAN_FORMS"]


def test_partial_draft_persists_and_stale_review_cannot_cross_an_immutable_edit(
    tmp_path: Path,
) -> None:
    app, lifecycle = _app(tmp_path / "partial.sqlite3")
    partial = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        _record_extraction(lifecycle, partial)
        saved = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "save-partial-v1"},
            json={
                "extractionId": str(_EXTRACTION_ID),
                "planJson": dump_explicit_plan_draft_json(partial),
                "sourceText": _SOURCE,
                "expectedRevision": 0,
            },
        )
        assert saved.status_code == 200
        first = saved.json()
        restored = client.get(f"/api/v1/plan-versions/{first['id']}")
        assert restored.status_code == 200
        assert restored.json()["planJson"] == dump_explicit_plan_draft_json(partial)
        assert restored.json()["canActivate"] is False

        edited_payload = partial.model_dump(mode="json")
        edited_payload["version"] = 99
        edited_payload["rules"][0]["condition"]["conditions"][0]["low_fen"] = 970
        edited = ExplicitPlanDraft.model_validate_json(json.dumps(edited_payload))
        edit = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "save-partial-v2"},
            json={
                "basePlanVersionId": first["id"],
                "planJson": dump_explicit_plan_draft_json(edited),
                "sourceText": _SOURCE,
                "expectedRevision": 0,
                "mapping": first["mapping"],
            },
        )
        assert edit.status_code == 200, edit.text
        second = edit.json()
        assert second["version"] == 2
        assert second["contentHash"] != first["contentHash"]
        assert second["reviewId"] is None
        forged = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "forge-old-review"},
            json={
                "planVersionId": second["id"],
                "contentHash": first["contentHash"],
                "sourceHash": first["sourceHash"],
                "reviewEvidenceHash": first["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": [],
            },
        )
        assert forged.status_code == 409


def test_original_source_partial_save_current_edit_and_semantic_review_stay_bound(
    tmp_path: Path,
) -> None:
    app, lifecycle = _app(tmp_path / "original-source-review.sqlite3")
    partial = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload(complete=False)))
    partial_mapping = _original_mapping(partial, with_human_supplements=False)

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        _record_extraction(
            lifecycle,
            partial,
            source_text=_ORIGINAL_SOURCE,
            mapping=partial_mapping,
        )
        saved = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "save-original-partial"},
            json={
                "extractionId": str(_EXTRACTION_ID),
                "planJson": dump_explicit_plan_draft_json(partial),
                "sourceText": _ORIGINAL_SOURCE,
                "expectedRevision": 0,
            },
        )
        assert saved.status_code == 200, saved.text
        first = saved.json()
        assert first["sourceText"] == _ORIGINAL_SOURCE
        assert {
            issue["path"]
            for issue in first["requiredReviewIssues"]
            if issue["code"] == "UNRESOLVED_EXECUTION_POLICY"
        } == {
            "activation",
            "conflict_policy",
            "rules[0].condition.conditions[1].history_scope",
            "rules[0].repeat_policy",
            "rules[1].repeat_policy",
            "rules[2].repeat_policy",
        }
        assert not any(
            issue["path"].endswith("safety_conditions") for issue in first["requiredReviewIssues"]
        )
        unresolved_clauses = [
            clause
            for clause in first["mapping"]["sourceClauses"]
            if clause["disposition"] == "UNRESOLVED"
        ]
        assert [clause["excerpt"] for clause in unresolved_clauses] == [
            "003043.SZ现有100股且今日可卖，",
            "提醒和确认不代表成交。",
        ]

        complete_payload = _draft_payload()
        complete_payload["version"] = 2
        complete = ExplicitPlanDraft.model_validate_json(json.dumps(complete_payload))
        complete_mapping = _original_mapping(complete, with_human_supplements=True)
        edited = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "save-original-complete"},
            json={
                "basePlanVersionId": first["id"],
                "planJson": dump_explicit_plan_draft_json(complete),
                "sourceText": _ORIGINAL_SOURCE,
                "expectedRevision": 0,
                "mapping": json.loads(complete_mapping.model_dump_json(by_alias=True)),
            },
        )
        assert edited.status_code == 200, edited.text
        current = edited.json()
        assert current["version"] == 2
        assert current["sourceText"] == _ORIGINAL_SOURCE
        assert current["sourceHash"] == first["sourceHash"]
        assert current["contentHash"] != first["contentHash"]
        assert {
            item["path"] for item in current["mapping"]["userSupplements"]
        } == _HUMAN_SUPPLEMENT_PATHS
        assert {item["label"] for item in current["mapping"]["userSupplements"]} == {
            "human_confirmed_supplement"
        }

        clauses = {clause["clauseId"]: clause for clause in current["mapping"]["sourceClauses"]}
        bindings = current["mapping"]["fieldBindings"]
        supplements = {item["supplementId"]: item for item in current["mapping"]["userSupplements"]}
        current_draft = json.loads(current["planJson"])
        resolutions: list[dict[str, object]] = []
        for issue in current["requiredReviewIssues"]:
            if issue["code"] == "SOURCE_MAPPING_REVIEW_REQUIRED":
                binding = next(item for item in bindings if item["path"] == issue["bindingPath"])
                assert binding["origin"] == "SOURCE"
                assert issue["clauseId"] in binding["clauseIds"]
                assert clauses[issue["clauseId"]]["excerpt"] in _ORIGINAL_SOURCE
                actual = _get_path(current_draft, issue["bindingPath"])
                assert binding["value"] == (
                    actual["type"] if binding["bindingKind"] == "STRUCTURE" else actual
                )
                resolutions.append(
                    {
                        "issueId": issue["issueId"],
                        "resolution": "CONFIRM_MAPPING",
                        "bindingPath": issue["bindingPath"],
                    }
                )
            elif issue["code"] == "USER_SUPPLEMENT_REVIEW_REQUIRED":
                supplement = next(
                    item for item in supplements.values() if item["path"] == issue["path"]
                )
                assert supplement["label"] == "human_confirmed_supplement"
                assert supplement["path"] == issue["path"]
                assert supplement["value"] == _get_path(current_draft, issue["path"])
                resolutions.append(
                    {
                        "issueId": issue["issueId"],
                        "resolution": "CONFIRM_POLICY",
                        "supplementId": supplement["supplementId"],
                    }
                )

        reviewed = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "review-original-current"},
            json={
                "planVersionId": current["id"],
                "contentHash": current["contentHash"],
                "sourceHash": current["sourceHash"],
                "reviewEvidenceHash": current["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": resolutions,
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        after_review = reviewed.json()
        assert after_review["revision"] == 1
        assert after_review["canActivate"] is False
        refreshed_response = client.get(f"/api/v1/plan-versions/{current['id']}")
        assert refreshed_response.status_code == 200
        refreshed = refreshed_response.json()
        assert {
            (issue["code"], clauses[issue["clauseId"]]["excerpt"])
            for issue in refreshed["unresolvedReviewIssues"]
            if issue["code"] == "UNRESOLVED_SEMANTICS"
        } == {
            ("UNRESOLVED_SEMANTICS", "003043.SZ现有100股且今日可卖，"),
            ("UNRESOLVED_SEMANTICS", "提醒和确认不代表成交。"),
        }
        assert {
            (issue["code"], issue["path"])
            for issue in refreshed["unresolvedReviewIssues"]
            if issue["code"] != "UNRESOLVED_SEMANTICS"
        } == {("UNMAPPED_PLAN_FIELD", "symbol")}
