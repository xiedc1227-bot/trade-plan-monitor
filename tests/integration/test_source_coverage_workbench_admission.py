"""Fresh workbench admission holds actual source authority through jobs commit.

The complete FIELD source is an engineering fixture, not NL extraction evidence.
All stores/readers/freezing are real; the recording coordinator starts no worker.
"""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from tests.integration.preparation_review_current_fixtures import field_source, reviewed_mapping
from tests.integration.test_monitor_loop_submission import context, services
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchReplayContext,
    WorkbenchSelectionCommand,
)
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.database import create_sqlite_engine
from trade_plan_monitor.state.repositories import PlanSaveBlockedError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.web.backtest_schemas import WorkbenchBacktestRunCommand
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanDraftCommand, PlanReviewConfirmationCommand
from trade_plan_monitor.web.schemas import ApiErrorCode


def inspect_jobs(repository):
    with sqlite3.connect(repository.database_path) as connection:
        jobs = connection.execute("SELECT job_id,status,kind,run_id FROM backtest_job").fetchall()
        bindings = connection.execute(
            "SELECT idempotency_key,job_id,response_json FROM backtest_job_idempotency"
        ).fetchall()
    return {"jobs": jobs, "bindings": bindings}


def append_bundle(lifecycle, identity, command):
    with lifecycle._session_factory() as session, session.begin():
        store = SourceCoverageStore(session)
        old = store.latest(identity)
        new = store.append(
            identity,
            old.assessment,
            inputs=old.inputs,
            expected_revision=old.revision,
            command_id=command,
            now=at(24, 10, 0, 13),
        )
        assert new.revision == old.revision + 1 and new.evidence_hash != old.evidence_hash
        return old, new


async def initialize(service, prepared, tmp_path):
    lifecycle = PersistentPlanWebLifecycle(
        database_path=tmp_path / "actual-workbench.sqlite3", clock=lambda: at(24, 9)
    )
    await lifecycle.start()
    service._plan_snapshot_reader = lifecycle
    # Equivalent complete FIELD source generated from this actual typed snapshot.
    # This exercises real persistence/proof, not natural-language extraction accuracy.
    draft = UnifiedPlanDraft.from_executable(prepared.version.snapshot)
    source = field_source(draft)
    mapping = reviewed_mapping(draft, source)
    saved = await lifecycle.save_plan_draft(
        command=PlanDraftCommand(
            plan_json=daily_draft_json(draft),
            source_text=source,
            daily_mapping=mapping,
            expected_revision=0,
        ),
        context=context("actual-source-save"),
    )
    with lifecycle._session_factory() as session:
        proof = SourceCoverageStore(session).latest(str(saved.id))
        assert proof is not None and proof.assessment.coverage_complete, (
            proof.assessment.issues if proof else None
        )
    approved = await lifecycle.confirm_plan_review(
        command=PlanReviewConfirmationCommand(
            plan_version_id=saved.id,
            content_hash=saved.content_hash,
            source_hash=saved.source_hash,
            review_evidence_hash=saved.review_evidence_hash,
            expected_revision=saved.review_revision,
            coverage_evidence_hash=proof.assessment.evidence_hash,
            coverage_rules_version=proof.assessment.rules_version,
        ),
        context=context("actual-source-review"),
    )
    assert approved.can_activate
    reviewed = await lifecycle.get_reviewed_backtest_plan(version_id=str(saved.id))
    selected = await service.create_plan_selection(
        command=WorkbenchSelectionCommand(
            schema_version="workbench-loop-selection-v1",
            plan=reviewed.reference,
            context=WorkbenchReplayContext(
                effective_trade_date=at(24).date(),
                available_at=at(24),
                information_cutoff=at(24),
                initial_account=prepared.account,
                confirmed=True,
                evidence=("Explicit synthetic historical account and start "
                          "for the actual selected source."),
            ),
        ),
        context=context("actual-selection"),
    )
    command = WorkbenchBacktestRunCommand.model_validate(
        {
            "schemaVersion": "workbench-loop-selection-v1",
            "selectionId": selected.selection_id,
            "selectionHash": selected.selection_hash,
            "response": {"mode": "OBSERVE_ONLY"},
            "costs": {
                "commissionRate": "0.0003",
                "minimumCommissionFen": 500,
                "stampDutyRate": "0.0005",
                "transferFeeRate": "0.00001",
                "buySlippageFen": 1,
                "sellSlippageFen": 1,
            },
        }
    )
    return lifecycle, saved, proof, selected, command


def test_stale_before_current_read_rejects_real_fresh_workbench_run(tmp_path, monkeypatch):
    service, preparations, prepared, _, _, _, _, coordinator = services(tmp_path, monkeypatch)

    async def run():
        lifecycle = None
        try:
            lifecycle, saved, _, _, command = await initialize(service, prepared, tmp_path)
            old, new = append_bundle(lifecycle, str(saved.id), "stale-before-current-read")
            with pytest.raises(PlanSaveBlockedError):
                await lifecycle.get_reviewed_backtest_plan(version_id=str(saved.id))
            with pytest.raises(ApiError) as failure:
                await service.submit_run(command=command, context=context("fresh-before-stale"))
            assert failure.value.code == ApiErrorCode.CONFLICT
            rows = inspect_jobs(service._repository)
            assert rows["jobs"] == [] and rows["bindings"] == [] and coordinator.authorized == []
            print(
                "PRECHECK_CONTROL",
                json.dumps(
                    {"old_revision": old.revision, "new_revision": new.revision, "jobs": rows},
                    default=str,
                ),
            )
        finally:
            await service.stop_metadata()
            await preparations.stop()
            if lifecycle:
                await lifecycle.stop()

    asyncio.run(run())


def test_current_workbench_run_rechecks_actual_source_at_job_admission(tmp_path, monkeypatch):
    service, preparations, prepared, _, results, _, _, coordinator = services(tmp_path, monkeypatch)

    async def run():
        lifecycle = None
        outcome = None
        failure = None
        try:
            lifecycle, saved, proof, selected, command = await initialize(
                service, prepared, tmp_path
            )
            original_freeze = service._freeze_prepared_input
            frames = []

            def freeze_then_reassess(*args, **kwargs):
                # Actual production dataset freeze/copy/persist occurs, then a valid
                # append-only source assessment commits before real job finalization.
                reference = original_freeze(*args, **kwargs)
                old, new = append_bundle(lifecycle, str(saved.id), "bundle-after-actual-input-copy")
                frames.append(
                    {
                        "old_revision": old.revision,
                        "new_revision": new.revision,
                        "old_bundle": old.evidence_hash,
                        "new_bundle": new.evidence_hash,
                        "assessment_hash_equal": old.assessment.evidence_hash
                        == new.assessment.evidence_hash,
                        "reference": reference.model_dump(mode="json"),
                    }
                )
                with pytest.raises(PlanSaveBlockedError):
                    lifecycle._get_reviewed_backtest_plan_sync(version_id=str(saved.id))
                return reference

            monkeypatch.setattr(service, "_freeze_prepared_input", freeze_then_reassess)
            try:
                outcome = await service.submit_run(
                    command=command, context=context("fresh-racing-intent")
                )
            except ApiError as cause:
                failure = cause
            rows = inspect_jobs(service._repository)
            diagnostic = {
                "frames": frames,
                "failure_code": None if failure is None else str(failure.code),
                "outcome": None if outcome is None else outcome.receipt.model_dump(mode="json"),
                "jobs": rows,
                "coordinator_authorized": coordinator.authorized,
            }
            if outcome is not None:
                # Existing completed idempotency receipt stays a read-only replay,
                # with no second authority read/copy/new job/authorization.
                before = (len(frames), list(coordinator.authorized), rows)
                replay = await service.submit_run(
                    command=command, context=context("fresh-racing-intent")
                )
                assert replay == outcome
                assert before == (
                    len(frames),
                    list(coordinator.authorized),
                    inspect_jobs(service._repository),
                )
                diagnostic["old_completed_receipt_replay_unchanged"] = True
                reference = results.get_loop_input_reference(outcome.receipt.run_id)
                assert results.get_loop_input(reference).prepared == selected.frozen
            (tmp_path / "race-evidence.json").write_text(
                json.dumps(diagnostic, default=str, indent=2), encoding="utf-8"
            )
            print("ACTUAL_RACE", json.dumps(diagnostic, default=str))
            assert frames and frames[0]["old_revision"] == proof.revision
            assert failure is not None, (
                "new job admitted after current source receipt went STALE: "
                + json.dumps(diagnostic, default=str)
            )
            assert failure.code == ApiErrorCode.CONFLICT
            assert rows["jobs"] == [] and rows["bindings"] == [] and coordinator.authorized == []
        finally:
            await service.stop_metadata()
            await preparations.stop()
            if lifecycle:
                await lifecycle.stop()

    asyncio.run(run())


@asynccontextmanager
async def actual_case(tmp_path, monkeypatch):
    from types import SimpleNamespace

    service, preparations, prepared, _, results, _, _, coordinator = services(tmp_path, monkeypatch)
    lifecycle = None
    try:
        lifecycle, saved, proof, selected, command = await initialize(service, prepared, tmp_path)
        yield SimpleNamespace(
            service=service,
            preparations=preparations,
            lifecycle=lifecycle,
            saved=saved,
            proof=proof,
            selected=selected,
            command=command,
            results=results,
            coordinator=coordinator,
        )
    finally:
        await service.stop_metadata()
        await preparations.stop()
        if lifecycle is not None:
            await lifecycle.stop()


def assert_not_admitted(case):
    rows = inspect_jobs(case.service._repository)
    assert rows["jobs"] == []
    assert rows["bindings"] == []
    assert case.coordinator.authorized == []


def test_source_writer_is_held_through_actual_jobs_commit_without_monitor_dml(
    tmp_path,
    monkeypatch,
):
    async def run():
        async with actual_case(tmp_path, monkeypatch) as case:
            lifecycle, service = case.lifecycle, case.service
            contender = create_sqlite_engine(lifecycle._database_path, busy_timeout_ms=50)
            statements, blocked, committed = [], [], []
            original_fence = lifecycle.current_workbench_run_fence

            def observe(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement.strip().upper())

            def try_actual_reassessment():
                with Session(contender) as session, session.begin():
                    store = SourceCoverageStore(session)
                    current = store.latest(str(case.saved.id))
                    store.append(
                        str(case.saved.id),
                        current.assessment,
                        inputs=current.inputs,
                        expected_revision=current.revision,
                        command_id="competing-real-assessment",
                        now=at(24, 10, 0, 13),
                    )

            @contextmanager
            def recorded(reference):
                with original_fence(reference) as current:
                    yield current
                    # The actual jobs connection has committed before this source
                    # context exits, while the monitor writer is still held.
                    rows = inspect_jobs(service._repository)
                    committed.append(rows)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(try_actual_reassessment)
                        with pytest.raises(OperationalError) as failure:
                            future.result(timeout=3)
                        assert failure.value.orig.sqlite_errorcode in {
                            sqlite3.SQLITE_BUSY,
                            sqlite3.SQLITE_LOCKED,
                        }
                        blocked.append(True)

            event.listen(lifecycle._engine, "before_cursor_execute", observe)
            monkeypatch.setattr(lifecycle, "current_workbench_run_fence", recorded)
            try:
                outcome = await service.submit_run(
                    command=case.command, context=context("actual-locked-admission")
                )
            finally:
                event.remove(lifecycle._engine, "before_cursor_execute", observe)
                contender.dispose()
            assert outcome.receipt.status == "QUEUED"
            assert len(committed) == 1 and len(committed[0]["jobs"]) == 1
            assert committed[0]["bindings"][0][0] == "actual-locked-admission"
            assert blocked == [True]
            assert "BEGIN" in statements and "BEGIN IMMEDIATE" in statements
            assert not any(
                sql.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"))
                for sql in statements
            )
            # Returning the DBAPI connection to its pool must not leak the
            # private writer option into a normal subsequent plan GET.
            statements.clear()
            event.listen(lifecycle._engine, "before_cursor_execute", observe)
            try:
                current = await lifecycle.get_plan_version(version_id=str(case.saved.id))
            finally:
                event.remove(lifecycle._engine, "before_cursor_execute", observe)
            assert current.id == case.saved.id
            assert "BEGIN" in statements and "BEGIN IMMEDIATE" not in statements
            old, new = append_bundle(lifecycle, str(case.saved.id), "writer-released-after-commit")
            assert (old.revision, new.revision) == (1, 2)

    asyncio.run(run())


def test_completed_workbench_receipt_replay_does_not_reenter_source_or_copy(tmp_path, monkeypatch):
    async def run():
        async with actual_case(tmp_path, monkeypatch) as case:
            first = await case.service.submit_run(
                command=case.command, context=context("completed-workbench-intent")
            )
            original_rows = inspect_jobs(case.service._repository)
            append_bundle(case.lifecycle, str(case.saved.id), "stale-after-completed-job-receipt")
            with pytest.raises(PlanSaveBlockedError):
                await case.lifecycle.get_reviewed_backtest_plan(version_id=str(case.saved.id))

            def unexpected(*_args, **_kwargs):
                pytest.fail("completed run receipt replay must not acquire new authority")

            monkeypatch.setattr(case.lifecycle, "current_workbench_run_fence", unexpected)
            monkeypatch.setattr(case.service, "_freeze_prepared_input", unexpected)
            # Even a closed actual source owner is irrelevant to a completed receipt.
            await case.lifecycle.stop()
            replay = await case.service.submit_run(
                command=case.command, context=context("completed-workbench-intent")
            )
            assert replay == first
            assert inspect_jobs(case.service._repository) == original_rows
            assert case.coordinator.authorized == [first.receipt.job_id]

    asyncio.run(run())


def test_missing_final_fence_capability_rejects_before_copy(tmp_path, monkeypatch):
    async def run():
        async with actual_case(tmp_path, monkeypatch) as case:
            monkeypatch.setattr(case.lifecycle, "current_workbench_run_fence", None)

            def unexpected(*_args, **_kwargs):
                pytest.fail("a missing private source writer must fail before copying")

            monkeypatch.setattr(case.service, "_freeze_prepared_input", unexpected)
            with pytest.raises(ApiError) as failure:
                await case.service.submit_run(
                    command=case.command, context=context("missing-actual-fence")
                )
            assert failure.value.code == ApiErrorCode.SERVICE_UNAVAILABLE
            assert_not_admitted(case)

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["closed", "busy", "integrity", "new-review"])
def test_final_actual_owner_failure_after_copy_has_no_job_or_receipt(
    tmp_path,
    monkeypatch,
    fault,
):
    async def run():
        async with actual_case(tmp_path, monkeypatch) as case:
            original_freeze = case.service._freeze_prepared_input
            blocker = None

            def short_wait(dbapi_connection, _record, _proxy):
                dbapi_connection.execute("PRAGMA busy_timeout=40")

            if fault == "busy":
                event.listen(case.lifecycle._engine, "checkout", short_wait)

            def copy_then_fault(*args, **kwargs):
                nonlocal blocker
                reference = original_freeze(*args, **kwargs)
                if fault == "closed":
                    asyncio.run(case.lifecycle.stop())
                elif fault == "busy":
                    blocker = sqlite3.connect(case.lifecycle._database_path)
                    blocker.execute("BEGIN IMMEDIATE")
                elif fault == "integrity":
                    with sqlite3.connect(case.lifecycle._database_path) as connection:
                        connection.execute(
                            "DROP TRIGGER pma_seal_source_coverage_assessment_update"
                        )
                else:
                    # A real second explicit confirmation changes the actual
                    # review owner while the old immutable selection stays fixed.
                    asyncio.run(
                        case.lifecycle.confirm_plan_review(
                            command=PlanReviewConfirmationCommand(
                                plan_version_id=case.saved.id,
                                content_hash=case.saved.content_hash,
                                source_hash=case.saved.source_hash,
                                review_evidence_hash=case.saved.review_evidence_hash,
                                expected_revision=1,
                                coverage_evidence_hash=case.proof.assessment.evidence_hash,
                                coverage_rules_version=case.proof.assessment.rules_version,
                            ),
                            context=context("new-actual-review-after-copy"),
                        )
                    )
                    current = case.lifecycle._get_reviewed_backtest_plan_sync(
                        version_id=str(case.saved.id)
                    )
                    assert current.reference != case.selected.frozen.reviewed.reference
                return reference

            monkeypatch.setattr(case.service, "_freeze_prepared_input", copy_then_fault)
            try:
                with pytest.raises(ApiError) as failure:
                    await case.service.submit_run(
                        command=case.command, context=context("final-owner-failure-" + fault)
                    )
                expected = (
                    ApiErrorCode.SERVICE_UNAVAILABLE
                    if fault in {"busy", "closed"}
                    else ApiErrorCode.INTERNAL_ERROR
                    if fault == "integrity"
                    else ApiErrorCode.CONFLICT
                )
                assert failure.value.code == expected
                if fault == "busy":
                    assert failure.value.retry_after_seconds == 1
                assert_not_admitted(case)
            finally:
                if blocker is not None:
                    # This raw contender was created in the metadata thread.
                    await case.service._run_sync(blocker.close)
                if fault == "busy":
                    event.remove(case.lifecycle._engine, "checkout", short_wait)

    asyncio.run(run())


def test_jobs_failure_rolls_back_and_releases_the_actual_source_writer(tmp_path, monkeypatch):
    async def run():
        async with actual_case(tmp_path, monkeypatch) as case:
            original_bind = case.service._repository._bind_idempotency_response

            def bind_then_fail(*args, **kwargs):
                original_bind(*args, **kwargs)
                raise RuntimeError("test-only failure before the actual jobs commit")

            monkeypatch.setattr(
                case.service._repository, "_bind_idempotency_response", bind_then_fail
            )
            with pytest.raises(RuntimeError, match="test-only failure before"):
                await case.service.submit_run(
                    command=case.command, context=context("rollback-actual-admission")
                )
            assert_not_admitted(case)
            current = await case.lifecycle.get_reviewed_backtest_plan(version_id=str(case.saved.id))
            assert current.reference == case.selected.frozen.reviewed.reference
            old, new = append_bundle(
                case.lifecycle, str(case.saved.id), "writer-released-after-rollback"
            )
            assert (old.revision, new.revision) == (1, 2)

    asyncio.run(run())
