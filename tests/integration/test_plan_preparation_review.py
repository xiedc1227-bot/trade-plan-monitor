"""Explicit human review freezes one research snapshot, never a live activation."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_monitor_loop_extraction import CASES, extract, fact, output_for
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.loop_input import KnownLoopCash, LoopAccountInput
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

NOW = datetime(2026, 10, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
AVAILABLE = datetime(2026, 8, 20, 9, tzinfo=ZoneInfo("Asia/Shanghai"))


def ready_preparation(tmp_path, *, source_text=None, opening_snapshot=False, metadata=None):
    text = source_text or CASES[0]["source"].split("参考行情", 1)[0]
    if opening_snapshot:
        text += "账户快照2026-08-20T09:00:00+08:00。"
    case = {**CASES[0], "source": text}
    source = PreparationSource(
        source_id="source-1",
        text=case["source"],
        **(
            dict(
                authored_at=AVAILABLE, available_at=AVAILABLE, effective_trade_date=AVAILABLE.date()
            )
            | (metadata or {})
        ),
    )
    output = output_for(case)
    if opening_snapshot:
        output["opening_account"]["snapshot_at"] = fact(
            text, "账户快照2026-08-20T09:00:00+08:00", AVAILABLE.isoformat()
        )
    result = extract(
        output,
        source.text,
        authored_at=source.authored_at,
        available_at=source.available_at,
        effective_trade_date=source.effective_trade_date,
    )
    store = PreparationStore(tmp_path / "preparation.sqlite3", clock=lambda: NOW)
    record = store.create(
        SinglePlanPreparationInput(preparation_id="one", sources=(source,)),
        idempotency_key="create",
    )
    running = store.start_attempt("one", expected_revision=record.revision, idempotency_key="start")
    result = result.model_copy(update={"request_id": UUID(running.attempts[-1].attempt_id)})
    ready = store.finish_attempt(
        "one",
        attempt_id=running.attempts[-1].attempt_id,
        expected_revision=running.revision,
        candidate=result.to_preparation_candidate(),
        idempotency_key="finish",
    )
    return store, ready


def review_command(record, **changes):
    from trade_plan_monitor.backtest.preparation_review import PreparationReviewCommand

    draft = UnifiedPlanDraft.from_executable(
        research_plan().model_copy(update={"symbol": "002240.SZ", "market": "SZSE"})
    )
    mapping = reviewed_mapping(draft, source=record.source.text)
    account = LoopAccountInput(
        snapshot_at=AVAILABLE,
        inventory_known=True,
        cash=KnownLoopCash(balance_fen=500000),
        lots=(),
        opening_mark=None,
        evidence="Synthetic human account override: no opening lots, cash 500000 fen.",
    )
    values = dict(
        expected_revision=record.revision,
        expected_source_revision=record.source_revision,
        expected_candidate_revision=record.candidate_revision,
        candidate_hash=record.candidate.candidate_hash,
        evidence_hash=record.candidate.evidence_hash,
        confirmed=True,
        evidence="Explicit synthetic human review of this source, plan and account.",
        draft=draft,
        mapping=mapping,
        account=account,
    )
    return PreparationReviewCommand(**(values | changes))


def test_explicit_review_freezes_complete_plan_account_and_original_evidence(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path)
    assert ready.review is None
    command = review_command(ready)
    reviewed = store.review_and_freeze("one", command=command, idempotency_key="review")
    frozen = frozen_preparation(reviewed)
    assert frozen.source == ready.source
    assert frozen.extraction_candidate_hash == ready.candidate.candidate_hash
    assert frozen.extraction_evidence_hash == ready.candidate.evidence_hash
    assert frozen.opening_evidence.cost_basis_fen == 401050
    assert frozen.account == command.account
    assert frozen.version.snapshot == command.draft.to_executable()
    assert frozen.version.review.confirmed is True
    assert frozen.version.review.reviewed_at == NOW
    assert len(frozen.schedule.entries) == 1
    assert PreparationStore(store.database_path).get("one") == reviewed
    with pytest.raises(ValidationError):
        frozen.account.cash.balance_fen = 1


@pytest.mark.parametrize("confirmation", [False, 1, "true", None])
def test_review_requires_literal_human_confirmation(tmp_path, confirmation):
    store, ready = ready_preparation(tmp_path)
    with pytest.raises(ValidationError):
        review_command(ready, confirmed=confirmation)
    assert store.get("one") == ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", 99),
        ("expected_source_revision", 99),
        ("expected_candidate_revision", 99),
        ("candidate_hash", "f" * 64),
        ("evidence_hash", "f" * 64),
    ],
)
def test_review_rejects_stale_revision_or_evidence_without_consuming_key(tmp_path, field, value):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            "one", command=review_command(ready, **{field: value}), idempotency_key="review"
        )
    assert store.get("one") == ready
    assert (
        store.review_and_freeze(
            "one", command=review_command(ready), idempotency_key="review"
        ).status
        == "REVIEWED"
    )


@pytest.mark.parametrize("changes", [{"draft": None}, {"mapping": None}, {"account": None}])
def test_confirmation_cannot_acknowledge_unresolved_plan_evidence_or_account(tmp_path, changes):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            "one", command=review_command(ready, **changes), idempotency_key="review"
        )
    assert store.get("one") == ready


@pytest.mark.parametrize("field", ["account", "source", "mapping", "extraction_candidate_hash"])
def test_frozen_manifest_detects_changed_bound_inputs(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path)
    frozen = frozen_preparation(
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    )
    payload = frozen.model_dump(mode="json")
    if field == "account":
        payload[field]["cash"]["balance_fen"] += 1
    elif field == "source":
        payload[field]["text"] += " 新补充。"
    elif field == "mapping":
        payload[field]["supplements"][0]["reason"] += " Changed evidence."
    else:
        payload[field] = "f" * 64
    with pytest.raises(ValidationError):
        type(frozen).model_validate(payload)


def review_service(store, jobs):
    from trade_plan_monitor.backtest.preparation_service import PreparationService
    from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor

    def forbidden_call(*args):
        pytest.fail("Review and reads must not call AI")

    return PreparationService(store, jobs, PreparationExtractor(forbidden_call))


@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "EXPIRED"])
def test_unfinished_global_task_blocks_review_without_changing_candidate(tmp_path, kind, state):
    from tests.integration.test_backtest_jobs import _Clock
    from tests.integration.test_backtest_single_task import request

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    clock = _Clock(NOW)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    first = jobs.submit(request(kind), "job", request_id="1" * 32)
    if state != "QUEUED":
        jobs.claim_next()
    if state == "CANCEL_REQUESTED":
        jobs.request_cancel(first.job_id, "cancel-job")
    if state == "EXPIRED":
        clock.advance(timedelta(seconds=31))

    async def scenario():
        service = review_service(store, jobs)
        try:
            with pytest.raises(JobAdmissionError) as blocked:
                await service.review_and_freeze(
                    "one", command=review_command(ready), idempotency_key="review"
                )
            assert blocked.value.code == "BACKTEST_BUSY"
            assert store.get("one") == ready
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_source_account_preserves_unknown_cash_dates_sellability_and_mark(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path, opening_snapshot=True)
    reviewed = store.review_and_freeze(
        "one", command=review_command(ready, account=None), idempotency_key="review"
    )
    frozen = frozen_preparation(reviewed)
    assert frozen.account_origin == "SOURCE"
    assert frozen.account.snapshot_at == AVAILABLE
    assert frozen.account.cash.kind == "UNKNOWN"
    assert frozen.account.opening_mark is None
    (lot,) = frozen.account.lots
    assert lot.bucket == "CORE" and lot.quantity == 100 and lot.cost_basis_fen == 401050
    assert lot.acquired_trade_date is None and lot.sellable_quantity is None
    assert frozen.account.opening_equity_fen is None


@pytest.mark.parametrize("field", ["authored_at", "available_at", "effective_trade_date"])
def test_missing_source_chronology_needs_explicit_correction_before_freeze(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path, metadata={field: None})
    with pytest.raises(PreparationConflictError, match="SOURCE_TIME_REQUIRED"):
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    assert store.get("one") == ready


def test_human_review_cannot_reclassify_unsupported_execution_as_background(tmp_path):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path, source_text=CASES[0]["source"])
    with pytest.raises(PreparationConflictError, match="UNSUPPORTED_SOURCE"):
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    assert store.get("one") == ready


@pytest.mark.parametrize("expired", [False, True])
def test_unresolved_reservation_stays_occupied_before_review(tmp_path, expired):
    from tests.integration.test_backtest_jobs import _Clock

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    clock = _Clock(NOW)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    reservation = jobs.claim_run_submission('{"domain":"unknown-work"}', "unknown")
    if expired:
        clock.advance(timedelta(seconds=31))

    async def scenario():
        service = review_service(store, jobs)
        try:
            with pytest.raises(JobAdmissionError) as blocked:
                await service.review_and_freeze(
                    "one", command=review_command(ready), idempotency_key="review"
                )
            assert blocked.value.code == "BACKTEST_BUSY"
            assert store.get("one") == ready
            assert (
                jobs.get_run_submission_reservation('{"domain":"unknown-work"}', "unknown")
                == reservation
            )
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_review_receipt_survives_source_edit_restart_and_another_active_job(tmp_path):
    from tests.integration.test_backtest_single_task import request

    from trade_plan_monitor.backtest.canonical import canonical_json
    from trade_plan_monitor.backtest.jobs import BacktestJobRepository
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    command = review_command(ready)

    async def scenario():
        service = review_service(store, jobs)
        try:
            frozen = await service.review_and_freeze(
                "one", command=command, idempotency_key="review"
            )
            assert await service.get_frozen("one") == frozen
            original = canonical_json(frozen)
            reviewed = store.get("one")
            changed = await service.edit_source(
                "one",
                source=ready.source.model_copy(update={"text": ready.source.text + " 新补充。"}),
                expected_revision=reviewed.revision,
                idempotency_key="edit",
            )
            assert changed.candidate is None and changed.review is None
            with pytest.raises(PreparationConflictError, match="REVIEW_REQUIRED"):
                await service.get_frozen("one")
        finally:
            await service.stop()
        jobs.submit(request("VERIFY"), "other")
        restarted = review_service(PreparationStore(store.database_path), jobs)
        try:
            replay = await restarted.review_and_freeze(
                "one", command=command, idempotency_key="review"
            )
            assert canonical_json(replay) == original
            assert replay.manifest_hash == frozen.manifest_hash
            assert store.get("one") == changed
            with pytest.raises(PreparationConflictError, match="IDEMPOTENCY_CONFLICT"):
                await restarted.review_and_freeze(
                    "one",
                    command=command.model_copy(update={"evidence": "Changed human declaration"}),
                    idempotency_key="review",
                )
            assert len(jobs.list_jobs()) == 1
        finally:
            await restarted.stop()

    asyncio.run(scenario())
