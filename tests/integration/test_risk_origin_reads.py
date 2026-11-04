"""Original risk ownership is read from real births, never the current action book."""

import importlib
from copy import deepcopy

import pytest
from sqlalchemy import update
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_plan_risk_evaluation_output import MONDAY_CLOSE
from tests.integration.test_plan_risk_evaluation_output import risk_case as risk_case

from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

pytestmark = pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "severe": "true"}], indirect=True
)


def read_origin(case, identity, *, work=None):
    read = importlib.import_module("trade_plan_monitor.state.risk_origin_reads").read_risk_origin
    if work is not None:
        return read(work, cause_id=identity, now=case.pipeline._clock.now())
    with case.work() as transaction:
        return read(transaction, cause_id=identity, now=case.pipeline._clock.now())


def native_risk(case, identity="ordinary-risk"):
    return next(row for row in case.result.snapshot["risks"] if row["rule_id"] == identity)


def change_daily(work, identity, *, payload=None, **values):
    """Negative SQL fixtures bypass repository validation, without changing production guards."""
    if payload is not None:
        values["payload_json"] = canonical(payload)
    work.daily.session.execute(
        update(DailyRecord)
        .where(DailyRecord.id == identity)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


@pytest.mark.parametrize("identity", ["ordinary-risk", "severe-risk"])
def test_real_birth_resolves_the_exact_immutable_origin_without_an_action_grant(
    risk_case, identity
):
    case = risk_case
    risk = native_risk(case, identity)
    result = read_origin(case, risk["risk_id"])
    assert result is not None
    assert result.cause.risk_id == risk["risk_id"]
    assert result.cause.status == risk["status"]
    assert result.birth.risk_identity == identity
    assert result.origin.plan_version_id == case.result.snapshot["plan_version_id"]
    assert result.cause.origin_evaluation_id == case.result.evaluation_id
    assert result.binding == read_origin(case, risk["risk_id"]).binding
    assert not hasattr(result, "quantity") and not hasattr(result, "permit")


@pytest.mark.parametrize("status", ["PENDING", "OBSERVATION", "CONFIRMED"])
def test_diagnosis_accepts_actual_non_action_states(risk_case, status):
    case = risk_case
    risk = native_risk(case)
    if status != "PENDING":
        case.source.official_closes[MONDAY_CLOSE.date()] = (
            "70.00" if status == "OBSERVATION" else "64.05"
        )
        result = case.run(MONDAY_CLOSE)
        assert (
            next(row for row in result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")[
                "status"
            ]
            == status
        )
    actual = read_origin(case, risk["risk_id"])
    assert actual is not None and actual.cause.status == status
    assert actual.cause.origin_evaluation_id == case.result.evaluation_id


def test_superseded_original_ignores_the_current_buy_book_and_coverage(risk_case, monkeypatch):
    case = risk_case
    risk = native_risk(case)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    with chain.client:
        chain.activate(version=2, activation_revision=1)
    with case.work() as work:
        old = work.plans.get_version_details(case.result.snapshot["plan_version_id"])
        assert old.status == "SUPERSEDED"
        current = work.plans.get_version_details(chain.version["id"])
        store = SourceCoverageStore(work.daily.session)
        stored = store.latest(current.id)
        values = stored.assessment.model_dump(mode="python", exclude={"evidence_hash", "status"})
        values["obligations"] = stored.assessment.obligations
        values["issues"] = (
            CoverageIssue(
                code="SOURCE_COVERAGE_LIMIT_EXCEEDED",
                path="ordinary_rules[0]",
                message="Synthetic current BUY-only source failure.",
            ),
        )
        failed = CoverageAssessment.build(**values)
        assert not failed.coverage_complete
        store.append(
            current.id,
            failed,
            inputs=stored.inputs,
            expected_revision=stored.revision,
            command_id="current-buy-failed",
            now=case.pipeline._clock.now(),
        )
        work.daily.session.execute(
            update(DailyRecord).where(DailyRecord.kind == "POSITION").values(payload_json="{}")
        )
        work.commit()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current active/book/history is not original ownership")

    monkeypatch.setattr(ActionOwnerReader, "active", forbidden)
    monkeypatch.setattr(ActionOwnerReader, "activation", forbidden)
    monkeypatch.setattr(ActionOwnerReader, "risks", forbidden)
    result = read_origin(case, risk["risk_id"])
    assert result is not None and result.origin.plan_version_id == old.id


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy-origin",
        "current-kind",
        "current-symbol",
        "self-reference",
        "head",
        "missing-birth",
        "post-state",
        "wrong-kind",
        "symbol",
        "identity",
        "birth-identity",
        "birth-date",
        "version",
        "review",
        "activation",
        "policy",
        "scope",
        "basis",
        "basis-blocker",
        "reassessment",
    ],
)
def test_missing_or_crossed_original_owners_stay_unknown(risk_case, mutation):
    case = risk_case
    risk = native_risk(case)
    if mutation == "post-state":
        later = case.run(MONDAY_CLOSE)
        assert "risk_births" not in later.snapshot
    with case.work() as work:
        current = work.daily.get(risk["risk_id"])
        payload = deepcopy(current["payload"])
        origin = work.daily.get(risk["origin_evaluation_id"])
        original = deepcopy(origin["payload"])
        if mutation == "legacy-origin":
            payload.pop("origin_evaluation_id")
        elif mutation == "current-kind":
            change_daily(work, current["id"], kind="REPORT")
        elif mutation == "current-symbol":
            change_daily(work, current["id"], symbol="000001.SZ")
        elif mutation == "self-reference":
            next(row for row in original["risks"] if row["risk_id"] == current["id"])[
                "origin_evaluation_id"
            ] = "unrelated-origin"
        elif mutation == "head":
            payload["origin_evaluation_id"] = "evaluation-head-" + case.plan.symbol
        elif mutation == "post-state":
            payload["origin_evaluation_id"] = later.evaluation_id
        elif mutation == "identity":
            payload["rule_id"] = "severe-risk"
        elif mutation == "policy":
            payload["target_tactical_qty"] = 100
        elif mutation == "scope":
            payload["holding_scope"] = {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-09-11"}
        elif mutation == "basis":
            payload["basis_id"] = "another-basis"
        elif mutation == "basis-blocker":
            payload["blockers"] = ["PERSISTED_RISK_BASIS_EQUIVALENCE_REQUIRED"]
        elif mutation == "reassessment":
            payload["reassessment_id"] = "later-reset-without-birth"
        elif mutation == "missing-birth":
            original.pop("risk_births")
        elif mutation in {"birth-identity", "birth-date"}:
            birth = next(
                row for row in original["risk_births"] if row["risk_identity"] == "ordinary-risk"
            )
            birth["risk_identity" if mutation == "birth-identity" else "close_date"] = (
                "unrelated-risk" if mutation == "birth-identity" else "2026-09-10"
            )
        elif mutation == "version":
            original["plan_version_id"] = "00000000-0000-0000-0000-000000000999"
            for observation in original["risk_evaluations"]:
                observation["plan_version_id"] = original["plan_version_id"]
        elif mutation == "review":
            original["review_id"] = "wrong-review"
            for observation in original["risk_evaluations"]:
                observation["review_id"] = "wrong-review"
        elif mutation == "activation":
            original["activation_revision"] += 1
        elif mutation == "wrong-kind":
            change_daily(work, origin["id"], kind="REPORT")
        elif mutation == "symbol":
            change_daily(work, origin["id"], symbol="000001.SZ")
        else:
            raise AssertionError(mutation)
        change_daily(work, current["id"], payload=payload)
        if mutation not in {"wrong-kind", "symbol"}:
            change_daily(work, origin["id"], payload=original)
        assert read_origin(case, risk["risk_id"], work=work) is None


def test_receipt_selects_its_original_revision_even_after_a_later_failed_assessment(risk_case):
    case = risk_case
    risk = native_risk(case)
    original = read_origin(case, risk["risk_id"])
    assert original is not None
    with case.work() as work:
        store = SourceCoverageStore(work.daily.session)
        receipt = store.receipt(case.result.snapshot["review_id"])
        first = store.at_revision(
            case.result.snapshot["plan_version_id"], receipt.coverage_revision
        )
        values = first.assessment.model_dump(mode="python", exclude={"evidence_hash", "status"})
        values["obligations"] = first.assessment.obligations
        values["issues"] = (
            CoverageIssue(
                code="SOURCE_COVERAGE_LIMIT_EXCEEDED",
                path="ordinary_rules[0]",
                message="Synthetic later assessment cannot rewrite the original receipt.",
            ),
        )
        failed = CoverageAssessment.build(**values)
        later = store.append(
            first.plan_version_id,
            failed,
            inputs=first.inputs,
            expected_revision=first.revision,
            command_id="later-assessment",
            now=case.pipeline._clock.now(),
        )
        assert later.revision == first.revision + 1 and not later.assessment.coverage_complete
        work.commit()
    result = read_origin(case, risk["risk_id"])
    assert result is not None and result.binding == original.binding
