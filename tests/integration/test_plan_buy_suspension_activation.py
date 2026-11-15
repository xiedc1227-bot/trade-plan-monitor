"""Real review/activation boundaries; synthetic sources, isolated SQL, no provider I/O."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from tests.integration.test_daily_plan_chain import SH, Chain
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_plan_buy_suspension_recovery import chain as chain
from tests.integration.test_plan_buy_suspension_recovery import seed_schema10
from tests.unit.test_plan_buy_suspension_coverage import replacement_case

from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.source_coverage_authority import read_version_coverage


@pytest.fixture
def production_chain(chain):
    return chain


def public_review(chain, draft, *, replacement=False, retire=False, start=None, ack=True,
                  review_status=200, supplement_revision=0, register_intent=True):
    from trade_plan_monitor.ai.daily_review import DailyClause
    from trade_plan_monitor.ai.review import server_source_clauses
    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
    from trade_plan_monitor.domain.daily_scope import scope_hash
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementIntent

    source, mapping = source_mapping(draft)
    intent = None
    if replacement:
        text = ("This new plan replaces the predecessor BUY suspension " + (
            "and explicitly retires its guard." if retire else "and supplies a new guard."))
        effective = start or chain.now
        begin = len(source) + 1
        source += "\n" + text + '\nstrategy_effective_from = "' + effective.isoformat() + '"'
        added = tuple(DailyClause.model_validate(c.model_dump() | dict(disposition="POLICY",
            paths=("ordinary_rules[0].side",), reason="Mandatory BUY replacement relation"))
            for c in server_source_clauses(source)[len(mapping.clauses):])
        mapping = mapping.model_copy(update={"clauses": (*mapping.clauses, *added)})
        intent = BuySuspensionReplacementIntent(source_hash=scope_hash(source),
            candidate_content_hash=mapping.candidate_content_hash, source_start=begin,
            source_end=begin + len(text), excerpt=text, replacement_reason="Explicit new strategy",
            retire_predecessor_guard=retire, acknowledge_unverified_predecessor=ack,
            strategy_effective_from=effective)
        if register_intent:
            chain.post("plan-review-supplements", dict(candidateJson=daily_draft_json(draft),
                contentHash=mapping.candidate_content_hash, sourceText=source, supplements=[],
                expectedRevision=supplement_revision,
                buySuspensionReplacementIntent=intent.model_dump(mode="json")))
    preview = chain.post("plan-review-previews", dict(candidateJson=daily_draft_json(draft),
        sourceText=source, mapping=mapping.model_dump(mode="json")))
    assert preview["review"]["issues"] == []
    if replacement:
        assert preview.get("buySuspensionReplacementIntent") == (
            intent.model_dump(mode="json") if register_intent else None)
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_activation_state(draft.symbol)
        revision = 0 if active is None else active.revision
    saved = chain.post("plan-drafts", dict(planJson=daily_draft_json(draft), sourceText=source,
        dailyMapping=preview["review"]["mapping"], expectedRevision=revision))
    coverage = saved["sourceCoverage"]
    binding = dict(planVersionId=saved["id"], contentHash=saved["contentHash"],
        sourceHash=saved["sourceHash"], reviewEvidenceHash=saved["reviewEvidenceHash"])
    reviewed = chain.post("plan-review-confirmations", dict(**binding, expectedRevision=0,
        coverageEvidenceHash=coverage["coverageEvidenceHash"],
        coverageRulesVersion=coverage["rulesVersion"]), status=review_status)
    if review_status != 200:
        return saved, reviewed
    return saved, dict(**binding, reviewId=reviewed["reviewId"],
                      reviewRevision=reviewed["revision"], expectedRevision=revision)


def public_activate(chain, draft, **review_options):
    saved, command = public_review(chain, draft, **review_options)
    chain.post("plan-activations", command)
    chain.plan, chain.version = draft.to_executable(), saved
    return saved


def public_production_guard(chain):
    from tests.integration.test_plan_buy_suspension_recovery import pipeline
    from tests.integration.test_unified_runtime import current_plan

    chain.plan = current_plan(mixed=False)
    saved = public_activate(chain, guard_draft(chain))
    chain.position(core=0, tactical=100)
    return pipeline(chain), saved


def guard_draft(chain, *, plan_id=None, version=1, retire=False):
    raw = chain.plan.model_dump(mode="python")
    raw.update(schema_version=10, execution_version="condition-plan-v6", version=version)
    if plan_id is not None:
        raw["plan_id"] = plan_id
    raw["buy_suspension"] = None if retire else (raw.get("buy_suspension") or dict(
        condition=dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=2420),
        effective_from=chain.now.replace(hour=9, minute=30, second=0, microsecond=0)))
    return BuySuspensionPlanDraft.model_validate(raw)


def test_public_registration_review_activation_and_retirement_are_separate(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        first = guard_draft(chain)
        old, activate = public_review(chain, first)
        chain.post("plan-activations", activate)
        chain.plan = first.to_executable()
        new = guard_draft(chain, plan_id="explicit-retirement", retire=True)
        saved, activate = public_review(chain, new, replacement=True, retire=True)
        with chain.plans._unit_of_work() as work:
            assert work.plans.get_active(first.symbol).plan_version_id == old["id"]
        chain.post("plan-activations", activate)
        with chain.plans._unit_of_work() as work:
            assert work.plans.get_active(first.symbol).plan_version_id == saved["id"]
            assert work.daily.get_buy_suspension(symbol=first.symbol,
                owner_plan_version_id=old["id"]) is None


def save_and_review(chain, draft, source, mapping, intent=None):
    from trade_plan_monitor.domain.daily_hash import daily_hash

    with chain.plans._unit_of_work() as work:
        if intent is not None:
            work.daily.save(daily_hash("daily-human-supplements-v1", dict(
                symbol=draft.symbol, content_hash=mapping.candidate_content_hash)),
                kind="DRAFT", symbol=draft.symbol, lineage=draft.plan_id,
                expected_revision=0, payload=dict(content_hash=mapping.candidate_content_hash,
                    source="EXPLICIT_HUMAN_OPERATION", supplements=[],
                    buy_suspension_replacement_intent=intent.model_dump(mode="json")))
        identity = save_daily_draft(work, draft, source_text=source, mapping=mapping,
                                    clock=chain.plans._clock)
        details = work.plans.get_version_details(identity)
        coverage = read_version_coverage(work, details)
        confirmed = confirm_daily_review(work, SimpleNamespace(plan_version_id=identity,
            content_hash=details.content_hash, source_hash=details.source_hash,
            review_evidence_hash=details.review_evidence_hash, resolutions=(), expected_revision=0,
            coverage_evidence_hash=coverage.assessment.evidence_hash,
            coverage_rules_version=coverage.assessment.rules_version), clock=chain.plans._clock)
        work.commit()
        return confirmed


@pytest.fixture
def original(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        seed_schema10(chain, datetime(2026, 9, 18, 9, 30, tzinfo=SH))
        yield chain


def test_owner_survives_deactivation_and_missing_record_is_not_clear(original):
    from trade_plan_monitor.state.activation_history import resolve_buy_suspension_context

    with original.plans._unit_of_work() as work:
        before = resolve_buy_suspension_context(work.plans, original.plan.symbol)
        work.plans.deactivate(original.plan.symbol, expected_revision=1)
        after = resolve_buy_suspension_context(work.plans, original.plan.symbol)
        assert after.owner.id == before.owner.id
        assert after.birth_revision == before.birth_revision == 1
        assert after.activation_revision == 2
        assert work.daily.get_buy_suspension(symbol=original.plan.symbol,
            owner_plan_version_id=after.owner.id) is None
        work.commit()


def test_guard_status_does_not_accept_a_dropped_field_even_with_old_true_callback(original):
    from trade_plan_monitor.runtime.daily_service import _buy_suspension_status

    plan = original.plan.model_copy(update={"buy_suspension": None})
    with original.plans._unit_of_work() as work:
        allowed, _, _ = _buy_suspension_status(work, plan, original.now,
                                              lambda *a, **k: True)
        assert allowed is False


def test_review_builds_exact_acknowledged_absent_predecessor_receipt(original):
    draft, source, mapping, intent = replacement_case()
    # A new immutable version; source declarations do not depend on display IDs.
    draft = draft.model_copy(update={"plan_id": "replacement-plan", "symbol": original.plan.symbol})
    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

    # Rebuild the source with the actual candidate identity.
    bare_source, bare_map = source_mapping(draft)
    tail = source[source.index("This new plan"):]
    source = bare_source + "\n" + tail
    from trade_plan_monitor.ai.daily_review import DailyClause
    from trade_plan_monitor.ai.review import server_source_clauses
    from trade_plan_monitor.domain.daily_scope import scope_hash

    extra = tuple(DailyClause.model_validate(c.model_dump() | dict(disposition="POLICY",
        paths=("ordinary_rules[0].side",), reason="Exact mandatory replacement relation"))
        for c in server_source_clauses(source)[len(bare_map.clauses):])
    mapping = bare_map.model_copy(update={"clauses": (*bare_map.clauses, *extra)})
    start = len(bare_source) + 1
    intent = intent.model_copy(update={"source_hash": scope_hash(source),
        "candidate_content_hash": daily_draft_content_sha256(draft), "source_start": start,
        "source_end": start + len(intent.excerpt)})
    confirmed = save_and_review(original, draft, source, mapping, intent)
    with original.plans._unit_of_work() as work:
        binding = work.daily.get("review-" + confirmed.id)["payload"]
        receipt = binding["buy_suspension_replacement"]
        assert receipt["predecessor_state_revision"] == 0
        assert receipt["predecessor_state_hash"] is None
        assert receipt["predecessor_unresolved_from"] == "2026-09-18T09:30:00+08:00"
        assert receipt["predecessor_unresolved_through"] is None
        assert receipt["new_review_id"] == confirmed.review_id
        assert work.plans.get_active(original.plan.symbol).plan_version_id != confirmed.id
        from trade_plan_monitor.web.source_coverage_read import read_source_coverage

        current = read_source_coverage(work, confirmed.id)
        assert current.summary.current_review_bound


@pytest.mark.parametrize("latched", [False, True])
def test_public_multilayer_copies_and_stop_restart_keep_original_record(production_chain, latched):
    from tests.integration.test_plan_buy_suspension_recovery import advance
    from tests.integration.test_plan_buy_suspension_runtime import inputs

    from trade_plan_monitor.state.activation_history import resolve_buy_suspension_context

    chain = production_chain
    owner, first = public_production_guard(chain)
    if latched:
        chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
    old = advance(chain)
    for index in (2, 3):
        public_activate(chain, guard_draft(chain, plan_id=f"ordinary-copy-{index}"))
    chain.post("plan-deactivations", dict(symbol=chain.plan.symbol, expectedRevision=3))
    public_activate(chain, guard_draft(chain, plan_id="ordinary-after-stop"))
    row = advance(chain)
    assert row["id"] == old["id"] and row["state"].definition == old["state"].definition
    assert row["state"].owner_plan_version_id == first["id"]
    with chain.plans._unit_of_work() as work:
        context = resolve_buy_suspension_context(work.plans, chain.plan.symbol)
        assert context.owner.id == first["id"] and context.birth_revision == 1
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="BUY_SUSPENSION")) == 1
        assert owner.buy_suspension_current(work, chain.plan,
            expected_revision=row["revision"]) is (not latched)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    assert result.snapshot["buy_suspension_owner_plan_version_id"] == first["id"]
    assert bool(result.snapshot["signals"]) is (not latched)


@pytest.mark.parametrize("change", ["appears", "latch", "activation", "target", "generation"])
def test_public_replacement_stale_snapshot_cannot_activate(production_chain, change):
    from datetime import timedelta

    from tests.integration.test_plan_buy_suspension_recovery import advance

    chain = production_chain
    owner, first = public_production_guard(chain)
    if change in {"target", "generation"}:
        advance(chain)
    candidate = guard_draft(chain, plan_id="reviewed-retirement", retire=True)
    saved, command = public_review(chain, candidate, replacement=True, retire=True)
    if change in {"appears", "latch"}:
        if change == "latch":
            chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
        advance(chain)
    elif change == "activation":
        chain.post("plan-deactivations", dict(symbol=chain.plan.symbol, expectedRevision=1))
        command["expectedRevision"] = 2
    elif change == "target":
        chain.now += timedelta(minutes=5)
    else:
        owner._recovery_configuration_revision += "-changed"
    chain.post("plan-activations", command, status=409)
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(chain.plan.symbol)
        assert active is None if change == "activation" else active.plan_version_id == first["id"]
        assert work.plans.get_version_details(saved["id"]).status == "DRAFT"


@pytest.mark.parametrize("inactive", [False, True])
def test_old_clear_with_later_target_requires_ack_and_can_be_superseded(production_chain, inactive):
    from datetime import timedelta

    from tests.integration.test_plan_buy_suspension_recovery import advance

    chain = production_chain
    _, first = public_production_guard(chain)
    old = advance(chain)
    assert old["state"].outcome == "CLEAR_THROUGH_TARGET"
    chain.now += timedelta(minutes=5)
    if inactive:
        chain.post("plan-deactivations", dict(symbol=chain.plan.symbol, expectedRevision=1))
    denied = guard_draft(chain, plan_id="no-ack-retirement", retire=True)
    public_review(chain, denied, replacement=True, retire=True, ack=False, review_status=422)
    accepted = guard_draft(chain, plan_id="ack-retirement", retire=True)
    saved = public_activate(chain, accepted, replacement=True, retire=True, supplement_revision=1)
    with chain.plans._unit_of_work() as work:
        receipt = work.daily.get("review-" + saved["id"])["payload"]["buy_suspension_replacement"]
        assert receipt["predecessor_unresolved_through"] == "2026-09-18T09:40:00+08:00"
        preserved = work.daily.get_buy_suspension(symbol=chain.plan.symbol,
            owner_plan_version_id=first["id"])
        assert preserved["state_hash"] == old["state_hash"]


def test_public_new_guard_has_own_catchup_and_preserves_old_latch(production_chain):
    from tests.integration.test_plan_buy_suspension_recovery import advance

    chain = production_chain
    owner, first = public_production_guard(chain)
    chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
    old = advance(chain)
    draft = guard_draft(chain, plan_id="new-guard-strategy")
    raw = draft.model_dump(mode="python")
    raw["buy_suspension"]["condition"]["price_fen"] = 2410
    draft = BuySuspensionPlanDraft.model_validate(raw)
    replacement = public_activate(chain, draft, replacement=True)
    with chain.plans._unit_of_work() as work:
        assert not owner.buy_suspension_current(work, chain.plan)
    row = advance(chain)
    assert row["state"].owner_plan_version_id == replacement["id"]
    assert row["state"].outcome == "CLEAR_THROUGH_TARGET"
    with chain.plans._unit_of_work() as work:
        assert owner.buy_suspension_current(work, chain.plan)
        assert work.daily.get_buy_suspension(symbol=chain.plan.symbol,
            owner_plan_version_id=first["id"])["state_hash"] == old["state_hash"]


def test_public_no_guard_retirement_obeys_strategy_start(production_chain):
    from datetime import timedelta

    from tests.integration.test_plan_buy_suspension_recovery import advance
    from tests.integration.test_plan_buy_suspension_runtime import inputs

    chain = production_chain
    owner, _ = public_production_guard(chain)
    advance(chain)
    start = chain.now + timedelta(minutes=5)
    public_activate(chain, guard_draft(chain, plan_id="future-retirement", retire=True),
                    replacement=True, retire=True, start=start)
    with chain.plans._unit_of_work() as work:
        assert not owner.buy_suspension_current(work, chain.plan)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=inputs(chain))
    assert result.snapshot["signals"] == []
    chain.now = start
    with chain.plans._unit_of_work() as work:
        assert owner.buy_suspension_current(work, chain.plan)


def test_public_dropped_guard_and_old_family_cannot_escape_actual_owner(tmp_path):
    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.repositories import PlanActivationBlockedError

    chain = Chain(tmp_path)
    with chain.client:
        legacy = chain.plan
        chain.activate()
        public_activate(chain, guard_draft(chain, version=2))
        public_review(chain, guard_draft(chain, plan_id="dropped-copy", retire=True),
                      review_status=422)
        with chain.plans._unit_of_work() as work:
            with pytest.raises(PlanActivationBlockedError, match="BUY_SUSPENSION"):
                work.plans.activate(legacy, expected_revision=2, validation=PlanValidationResult())
            assert work.plans.get_active(chain.plan.symbol).plan_version_id == chain.version["id"]


def test_different_symbol_has_no_inherited_global_ban(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        public_activate(chain, guard_draft(chain))
        other = guard_draft(chain, plan_id="other-symbol", retire=True).model_copy(
            update={"symbol": "600000.SH"})
        public_activate(chain, other)
        with chain.plans._unit_of_work() as work:
            assert work.plans.get_active(other.symbol).plan_version_id == chain.version["id"]


@pytest.mark.parametrize("outcome", ["UNVERIFIED", "LATCHED"])
def test_public_retirement_preserves_real_old_unresolved_or_latched_history(
    production_chain, outcome,
):
    from tests.integration.test_plan_buy_suspension_recovery import advance

    chain = production_chain
    owner, first = public_production_guard(chain)
    chain.sdk.late = outcome == "UNVERIFIED"
    if outcome == "LATCHED":
        chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
    old = advance(chain)
    assert old["state"].outcome == outcome
    public_activate(chain, guard_draft(chain, plan_id="explicit-retired-context", retire=True),
                    replacement=True, retire=True)
    with chain.plans._unit_of_work() as work:
        assert owner.buy_suspension_current(work, chain.plan)
        assert work.daily.get_buy_suspension(symbol=chain.plan.symbol,
            owner_plan_version_id=first["id"])["state_hash"] == old["state_hash"]
    # A later independent ordinary context does not resurrect the retired obligation.
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    raw = chain.plan.model_dump(mode="python")
    raw.update(plan_id="ordinary-after-retirement", schema_version=5,
               execution_version="condition-plan-v1")
    raw.pop("buy_suspension")
    public_activate(chain, UnifiedPlanDraft.model_validate(raw))
    with chain.plans._unit_of_work() as work:
        assert owner.buy_suspension_current(work, chain.plan)


@pytest.mark.parametrize("first", ["ACTIVATION", "BUY", "CORRECTION"])
def test_actual_writers_order_replacement_old_buy_and_correction(production_chain, first):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Event

    from tests.integration.test_plan_buy_suspension_recovery import advance
    from tests.integration.test_plan_buy_suspension_runtime import inputs
    from tests.integration.test_plan_buy_suspension_simulation import command

    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.repositories import (
        PlanActivationBlockedError,
        RevisionConflictError,
    )
    from trade_plan_monitor.state.simulation import SimulationAuthorityError, simulate_inventory

    chain = production_chain
    owner, old = public_production_guard(chain)
    row = advance(chain)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    buy = command(chain, result.snapshot["signals"][0])
    candidate = guard_draft(chain, plan_id="concurrent-retirement", retire=True)
    replacement, _ = public_review(chain, candidate, replacement=True, retire=True)
    chain.now += timedelta(seconds=1)
    held, release, attempting = Event(), Event(), Event()

    def action(kind, lead):
        if not lead:
            attempting.set()
        try:
            with chain.plans._unit_of_work() as work:
                if kind == "ACTIVATION":
                    work.plans.activate(candidate.to_executable(), expected_revision=1,
                        validation=PlanValidationResult(),
                        buy_suspension_current=owner.buy_suspension_current)
                elif kind == "BUY":
                    simulate_inventory(work, buy, chain.now,
                        buy_suspension_current=owner.buy_suspension_current)
                else:
                    work.daily.lock_symbol(chain.plan.symbol)
                    target = row["state"].target
                    minute = work.history.list_minutes(chain.plan.symbol,
                        start=target, end=target)[0]
                    work.history.upsert_minutes((minute.model_copy(update={"close_fen": 2419,
                        "received_at": chain.now}),))
                if lead:
                    held.set()
                    assert release.wait(5)
                work.commit()
            return kind
        except (PlanActivationBlockedError, RevisionConflictError, SimulationAuthorityError):
            return "REJECTED"

    following = "BUY" if first == "ACTIVATION" else "ACTIVATION"
    with ThreadPoolExecutor(max_workers=2) as pool:
        leading = pool.submit(action, first, True)
        try:
            assert held.wait(5)
            trailing = pool.submit(action, following, False)
            assert attempting.wait(5)
        finally:
            release.set()
        assert leading.result(timeout=10) == first
        assert trailing.result(timeout=10) == ("ACTIVATION" if first == "BUY" else "REJECTED")
    with chain.plans._unit_of_work() as work:
        fills = work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
        assert len(fills) == int(first == "BUY")
        assert work.plans.get_active(chain.plan.symbol).plan_version_id == (
            old["id"] if first == "CORRECTION" else replacement["id"])


def test_public_fill_retry_and_replacement_never_reset_accounting(production_chain):
    from tests.integration.test_plan_buy_suspension_recovery import advance
    from tests.integration.test_plan_buy_suspension_runtime import inputs
    from tests.integration.test_plan_buy_suspension_simulation import command

    chain = production_chain
    owner, _ = public_production_guard(chain)
    row = advance(chain)
    signal = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"])).snapshot["signals"][0]
    payload = command(chain, signal).model_dump(mode="json", by_alias=True)
    receipt = chain.post("simulated-trades", payload, key="t08-completed-buy")
    public_activate(chain, guard_draft(chain, plan_id="after-completed-buy", retire=True),
                    replacement=True, retire=True)
    assert chain.post("simulated-trades", payload, key="t08-completed-buy") == receipt
    chain.post("simulated-trades", payload, key="t08-stale-buy", status=409)
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
        assert work.daily.get(signal["signal_id"])["payload"]["simulated_qty"] == 100
        assert work.daily.get("simulation-position-" + chain.plan.symbol)["payload"][
            "batches"][-1]["quantity"] == 100


def test_missing_activation_pointers_cannot_turn_owned_history_into_first_activation(tmp_path):
    from sqlalchemy import delete

    from trade_plan_monitor.state.activation_history import resolve_buy_suspension_context
    from trade_plan_monitor.state.models import ActivePlan, PlanActivationState

    chain = Chain(tmp_path)
    with chain.client:
        public_activate(chain, guard_draft(chain))
        with chain.plans._unit_of_work() as work:
            resolve_buy_suspension_context(work.plans, chain.plan.symbol)
            for model in (ActivePlan, PlanActivationState):
                work.daily.session.execute(delete(model).where(model.symbol == chain.plan.symbol)
                    .execution_options(synchronize_session=False))
            with pytest.raises(ValueError):
                resolve_buy_suspension_context(work.plans, chain.plan.symbol)


def test_cached_deleted_intent_registration_cannot_authorize_direct_activation(production_chain):
    from sqlalchemy import delete

    from trade_plan_monitor.domain.daily_hash import daily_hash
    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
    from trade_plan_monitor.web.source_coverage_read import read_source_coverage

    chain = production_chain
    owner, _ = public_production_guard(chain)
    candidate = guard_draft(chain, plan_id="deleted-registration", retire=True)
    saved, _ = public_review(chain, candidate, replacement=True, retire=True)
    with chain.plans._unit_of_work() as work:
        assert read_source_coverage(work, saved["id"]).summary.current_review_bound
        identity = daily_hash("daily-human-supplements-v1", dict(symbol=chain.plan.symbol,
            content_hash=saved["contentHash"]))
        retained = work.daily.session.get(DailyRecord, identity)
        assert retained is not None
        work.daily.session.execute(delete(DailyRecord).where(DailyRecord.id == identity)
            .execution_options(synchronize_session=False))
        with pytest.raises(SourceCoverageAuthorityError):
            work.plans.activate(candidate.to_executable(), expected_revision=1,
                validation=PlanValidationResult(),
                buy_suspension_current=owner.buy_suspension_current)


@pytest.mark.parametrize("ordinary_between", [False, True])
def test_same_source_reimport_is_not_a_new_replacement_decision(tmp_path, ordinary_between):
    from trade_plan_monitor.ai.daily_review import DailyMapping

    chain = Chain(tmp_path)
    with chain.client:
        public_activate(chain, guard_draft(chain))
        saved = public_activate(chain, guard_draft(chain, plan_id="first-replacement"),
                                replacement=True)
        if ordinary_between:
            public_activate(chain, guard_draft(chain, plan_id="ordinary-between"))
        duplicate = BuySuspensionPlanDraft.from_executable(chain.plan).model_copy(
            update={"plan_id": "reimport-same-source"})
        with pytest.raises(ValueError, match="new source"):
            save_and_review(chain, duplicate, saved["sourceText"],
                            DailyMapping.model_validate(saved["dailyMapping"]))


def test_review_shadow_checks_receipt_plan_hash_not_only_content_hash(production_chain):
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementBinding
    from trade_plan_monitor.web.source_coverage_read import read_source_coverage

    chain = production_chain
    public_production_guard(chain)
    saved, _ = public_review(chain, guard_draft(chain, plan_id="wrong-hash", retire=True),
                            replacement=True, retire=True)
    with chain.plans._unit_of_work() as work:
        row = work.daily.get("review-" + saved["id"])
        receipt = BuySuspensionReplacementBinding.model_validate(
            row["payload"]["buy_suspension_replacement"])
        values = {name: getattr(receipt, name) for name in type(receipt).model_fields
                  if name != "evidence_hash"}
        wrong = BuySuspensionReplacementBinding.build(**(values | {"new_plan_hash": "0" * 64}))
        work.daily.save(row["id"], kind="REVIEW", symbol=row["symbol"], lineage=row["lineage"],
            expected_revision=row["revision"], payload=row["payload"] | {
                "buy_suspension_replacement": wrong.model_dump(mode="json")})
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert not read_source_coverage(work, saved["id"]).summary.current_review_bound


def test_activation_writer_refreshes_cached_source_before_checking(production_chain):
    from sqlalchemy import update

    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.models import PlanSource, PlanVersion
    from trade_plan_monitor.state.repositories import RepositoryError
    from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError

    chain = production_chain
    owner, _ = public_production_guard(chain)
    candidate = guard_draft(chain, plan_id="source-changed-under-lock", retire=True)
    saved, _ = public_review(chain, candidate, replacement=True, retire=True)
    with chain.plans._unit_of_work() as work:
        version = work.daily.session.get(PlanVersion, saved["id"])
        retained = work.daily.session.get(PlanSource, version.source_id)
        work.plans.get_version_details(saved["id"])
        work.daily.session.execute(update(PlanSource).where(PlanSource.id == retained.id)
            .values(source_text="Changed after review")
            .execution_options(synchronize_session=False))
        with pytest.raises((RepositoryError, SourceCoverageAuthorityError)):
            work.plans.activate(candidate.to_executable(), expected_revision=1,
                validation=PlanValidationResult(),
                buy_suspension_current=owner.buy_suspension_current)


@pytest.mark.parametrize("field", ["predecessor_guard", "new_review_id"])
def test_installed_replacement_still_binds_real_guard_and_review(production_chain, field):
    from trade_plan_monitor.state.activation_history import resolve_buy_suspension_context
    from trade_plan_monitor.state.source_coverage_values import BuySuspensionReplacementBinding

    chain = production_chain
    public_production_guard(chain)
    saved = public_activate(chain, guard_draft(chain, plan_id="installed-retirement", retire=True),
                            replacement=True, retire=True)
    with chain.plans._unit_of_work() as work:
        row = work.daily.get("review-" + saved["id"])
        receipt = BuySuspensionReplacementBinding.model_validate(
            row["payload"]["buy_suspension_replacement"])
        values = {name: getattr(receipt, name) for name in type(receipt).model_fields
                  if name != "evidence_hash"}
        payload = dict(row["payload"])
        if field == "predecessor_guard":
            guard = receipt.predecessor_guard
            values[field] = guard.model_copy(update={"condition": guard.condition.model_copy(
                update={"price_fen": 2500})})
        else:
            values[field] = payload["review_id"] = "forged-review"
        payload["buy_suspension_replacement"] = BuySuspensionReplacementBinding.build(
            **values).model_dump(mode="json")
        work.daily.save(row["id"], kind="REVIEW", symbol=row["symbol"], lineage=row["lineage"],
                        expected_revision=row["revision"], payload=payload)
        work.commit()
    with chain.plans._unit_of_work() as work:
        with pytest.raises(ValueError):
            resolve_buy_suspension_context(work.plans, chain.plan.symbol)


def test_public_multilayer_replacement_receipt_distinguishes_predecessor_and_owner(tmp_path):
    from trade_plan_monitor.state.activation_history import (
        guard_owner_hash,
        resolve_buy_suspension_context,
    )

    chain = Chain(tmp_path)
    with chain.client:
        first = public_activate(chain, guard_draft(chain))
        public_activate(chain, guard_draft(chain, plan_id="continuation-two"))
        third = public_activate(chain, guard_draft(chain, plan_id="continuation-three"))
        draft = guard_draft(chain, plan_id="after-three-retirement", retire=True)
        saved, activation = public_review(chain, draft, replacement=True, retire=True)
        with chain.plans._unit_of_work() as work:
            context = resolve_buy_suspension_context(work.plans, chain.plan.symbol)
            prior = work.plans.get_version_details(third["id"])
            owner = work.plans.get_version_details(first["id"])
            receipt = work.daily.get("review-" + saved["id"])["payload"][
                "buy_suspension_replacement"]
            assert receipt["predecessor_plan_version_id"] == prior.id != owner.id
            assert receipt["predecessor_guard_owner_plan_version_id"] == owner.id
            assert receipt["predecessor_guard_owner_hash"] == guard_owner_hash(context)
            for field, actual in (
                ("predecessor_plan_id", prior.plan_id), ("predecessor_plan_version", prior.version),
                ("predecessor_plan_hash", prior.plan_hash),
                ("predecessor_content_hash", prior.content_hash),
                ("predecessor_source_hash", prior.source_hash),
                ("predecessor_review_id", prior.review_id),
                ("predecessor_review_revision", prior.review_revision),
                ("predecessor_activation_revision", 3),
                ("new_plan_version_id", saved["id"]), ("new_plan_hash", saved["planHash"]),
                ("new_content_hash", saved["contentHash"]),
                ("new_source_hash", saved["sourceHash"]),
                ("new_review_id", activation["reviewId"]), ("new_review_revision", 1),
            ):
                assert receipt[field] == actual
            assert receipt["predecessor_guard"] == chain.plan.buy_suspension.model_dump(mode="json")
            assert receipt["predecessor_state_revision"] == 0
            assert receipt["predecessor_state_hash"] is None
            assert receipt["new_guard"] is None
            assert work.plans.get_active(chain.plan.symbol).plan_version_id == prior.id
        chain.post("plan-activations", activation)
        with chain.plans._unit_of_work() as work:
            assert work.plans.get_active(chain.plan.symbol).plan_version_id == saved["id"]
            assert resolve_buy_suspension_context(work.plans, chain.plan.symbol).owner is None


def test_public_changed_source_replacement_without_reregistration_cannot_review(tmp_path):
    from datetime import timedelta

    from trade_plan_monitor.domain.daily_hash import daily_hash

    chain = Chain(tmp_path)
    with chain.client:
        public_activate(chain, guard_draft(chain))
        original = public_activate(chain, guard_draft(chain, plan_id="registered-strategy"),
                                   replacement=True)
        candidate = guard_draft(chain, plan_id="unregistered-new-source")
        saved, denied = public_review(chain, candidate, replacement=True, register_intent=False,
            start=chain.now + timedelta(minutes=5), review_status=422)
        assert saved["contentHash"] == original["contentHash"]
        assert saved["sourceHash"] != original["sourceHash"]
        assert denied["error"]["code"] == "VALIDATION_ERROR"
        with chain.plans._unit_of_work() as work:
            review = work.daily.get("review-" + saved["id"])["payload"]
            assert not review["confirmed"] and review["review_id"] is None
            assert "buy_suspension_replacement_intent" not in review
            assert "buy_suspension_replacement" not in review
            assert work.plans.get_active(chain.plan.symbol).plan_version_id == original["id"]
            registered = work.daily.get(daily_hash("daily-human-supplements-v1", dict(
                symbol=chain.plan.symbol, content_hash=saved["contentHash"])))
            assert registered["payload"]["buy_suspension_replacement_intent"][
                "source_hash"] == original["sourceHash"]
