"""The browser adapter must expose actual owned work, never manufactured readiness."""

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event


@asynccontextmanager
async def workspace(root, *, scenario="automatic"):
    module = import_module("tests.browser.plan_readiness_server")
    app = module.create_fixture_app(root, scenario=scenario)
    state = app.state.readiness_fixture
    try:
        async with app.router.lifespan_context(app):
            async with httpx.ASGITransport(app, client=("127.0.0.1", 50000)) as transport:
                yield state, transport
        assert state.case.composition.read_service.outstanding_work == 0
        assert state.case.composition._runtime.progress_snapshot().state == "STOPPED"
    finally:
        state.restore_boundaries()


async def request(transport, path, *, method="GET", body=None):
    response = await transport.handle_async_request(
        httpx.Request(
            method,
            "http://127.0.0.1:8765" + path,
            json=body,
            headers={
                "X-Monitor-Contract-Version": "2",
                **({"Idempotency-Key": uuid4().hex} if method == "POST" else {}),
            },
        )
    )
    await response.aread()
    return response


def test_saved_source_public_get_uses_the_actual_owner_and_real_sqlite(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            detail = await request(transport, "/api/v1/plan-versions/" + state.version)
            assert detail.status_code == 200, detail.text
            saved = detail.json()
            assert saved["sourceCoverage"]["currentReviewBound"] is True
            assert saved["sourceCoverage"]["coverageComplete"] is True
            native = await state.case.composition.read_service.get_plan_readiness(
                version_id=state.version,
            )
            response = await request(transport, state.readiness_path)
            assert response.status_code == 200, response.text
            assert response.json() == native.model_dump(mode="json", by_alias=True)
            assert response.json()["summary"] == "READY_FOR_MONITORING", {
                "now": state.case.clock.now().isoformat(),
                "progress": str(state.case.composition._runtime.progress_snapshot()),
                "parked": str(state.case.clock.parked[0]),
                "axes": [(axis.axis, axis.state, axis.reason) for axis in native.axes],
            }
            assert response.json()["authorityGranted"] is False
            assert response.json()["rules"][0]["state"] == "CONDITION_FALSE"
            assert native.fresh_until > native.snapshot.computed_at + timedelta(milliseconds=1)
            assert (tmp_path / "monitor.sqlite3").is_file()
            assert state.case.composition._runtime.runtime_generation == (
                native.snapshot.context.runtime_generation
            )

    asyncio.run(scenario())


def test_two_scheduled_targets_need_no_new_fact_or_review(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            before = state.inspect()
            first = (await request(transport, state.readiness_path)).json()
            response = await request(
                transport, state.prefix + "/next-target", method="POST", body={}
            )
            assert response.status_code == 200, response.text
            after = response.json()
            second = (await request(transport, state.readiness_path)).json()
            assert second["summary"] == "READY_FOR_MONITORING"
            assert second["rules"][0]["state"] == "CONDITION_FALSE"
            assert second["snapshot"]["context"] == first["snapshot"]["context"]
            a, b = first["rules"][0]["facts"], second["rules"][0]["facts"]
            assert a["evaluatedTarget"] != b["evaluatedTarget"]
            assert a["evaluatedAt"] < b["evaluatedAt"]
            assert before["completionResultHash"] != after["completionResultHash"]
            for table in ("source_coverage_review", "plan_review_provenance", "plan_version"):
                assert before["storage"][table] == after["storage"][table]
            assert before["storage"]["dailyKinds"].get("FACT", 0) == (
                after["storage"]["dailyKinds"].get("FACT", 0)
            )
            assert (
                after["storage"]["dailyKinds"]["EVALUATION"]
                > (before["storage"]["dailyKinds"]["EVALUATION"])
            )
            assert after["externalAttempts"] == []

    asyncio.run(scenario())


def test_repeated_public_reads_do_not_write_acquire_evaluate_or_renew_expiry(tmp_path, monkeypatch):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            before = state.inspect()
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            statements = []

            def forbidden(*_args, **_kwargs):
                pytest.fail("GET attempted native producer or SDK work")

            def readonly(_connection, _cursor, sql, _parameters, _context, _many):
                verb = sql.lstrip().split()[0].upper()
                statements.append(verb)
                assert verb not in {
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "REPLACE",
                    "CREATE",
                    "ALTER",
                    "DROP",
                }

            with monkeypatch.context() as patch:
                for name in ("run_deadline", "prepare_daily_inputs", "refresh_references"):
                    patch.setattr(pipeline, name, forbidden)
                patch.setattr(state.case.sdk, "_stock_minutes", forbidden)
                engine = state.case.composition._runtime._liveness_owner._engine
                event.listen(engine, "before_cursor_execute", readonly)
                try:
                    a = await request(transport, state.readiness_path)
                    b = await request(transport, state.readiness_path)
                finally:
                    event.remove(engine, "before_cursor_execute", readonly)
            assert a.status_code == b.status_code == 200
            assert a.json() == b.json()
            assert a.json()["freshUntil"] is not None
            assert "SELECT" in statements
            assert state.inspect() == before

    asyncio.run(scenario())


def test_fixture_rejects_nonlocal_controls_extra_fields_and_third_cycle(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            invalid = await request(
                transport,
                state.prefix + "/next-target",
                method="POST",
                body={"completion": "invented"},
            )
            assert invalid.status_code == 422
            assert state.cycles == 1
            async with httpx.ASGITransport(state.app, client=("192.0.2.1", 50000)) as foreign:
                rejected = await request(foreign, state.prefix + "/inspect")
                assert rejected.status_code == 403
            assert (
                await request(transport, state.prefix + "/next-target", method="POST", body={})
            ).status_code == 200
            assert (
                await request(transport, state.prefix + "/next-target", method="POST", body={})
            ).status_code == 409

    asyncio.run(scenario())


def confirmation(saved):
    return {
        "planVersionId": saved["id"],
        "contentHash": saved["contentHash"],
        "sourceHash": saved["sourceHash"],
        "reviewEvidenceHash": saved["reviewEvidenceHash"],
        "expectedRevision": saved["reviewRevision"],
        "coverageEvidenceHash": saved["sourceCoverage"]["coverageEvidenceHash"],
        "coverageRulesVersion": saved["sourceCoverage"]["rulesVersion"],
    }


def activation(saved, *, expected_revision):
    return {
        "planVersionId": saved["id"],
        "contentHash": saved["contentHash"],
        "sourceHash": saved["sourceHash"],
        "reviewEvidenceHash": saved["reviewEvidenceHash"],
        "reviewId": saved["reviewId"],
        "reviewRevision": saved["reviewRevision"],
        "expectedRevision": expected_revision,
    }


def test_context_repair_retains_original_requirement_and_rejects_stale_authority(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            initial = state.inspect()["storage"]
            invalid = await request(
                transport,
                state.prefix + "/source-case",
                method="POST",
                body={"scenario": "repair", "proof": "not accepted"},
            )
            assert invalid.status_code == 422
            assert state.inspect()["storage"] == initial
            setup = await request(
                transport, state.prefix + "/source-case", method="POST", body={"scenario": "repair"}
            )
            assert setup.status_code == 200, setup.text
            data = setup.json()
            saved = (
                await request(transport, "/api/v1/plan-versions/" + data["versionIds"][0])
            ).json()
            assert saved["sourceCoverage"]["coverageComplete"] is False
            assert saved["sourceCoverage"]["canConfirmReview"] is False
            assert data["requirement"] in saved["sourceText"]
            before = state.inspect()["storage"]
            blocked = await request(
                transport,
                "/api/v1/plan-review-confirmations",
                method="POST",
                body=confirmation(saved),
            )
            assert blocked.status_code == 409, blocked.text
            blocked = await request(
                transport,
                "/api/v1/plan-activations",
                method="POST",
                body=activation(saved, expected_revision=1),
            )
            assert blocked.status_code == 409, blocked.text
            assert state.inspect()["storage"] == before

            # Mirror the existing explicit UI workflow: registered exact value,
            # correct clause classification/path, then save and explicitly review.
            candidate = saved["planJson"]
            mapping = deepcopy(saved["dailyMapping"])
            path = data["repairPath"]
            result = await request(
                transport,
                "/api/v1/plan-review-supplements",
                method="POST",
                body={
                    "candidateJson": candidate,
                    "contentHash": saved["contentHash"],
                    "expectedRevision": 0,
                    "supplements": [
                        {
                            "supplement_id": "explicit-source-match",
                            "candidate_content_hash": saved["contentHash"],
                            "path": path,
                            "value": 4000,
                            "reason": (
                                "Explicitly retain the original 4000-fen requirement; "
                                "no condition is waived."
                            ),
                        }
                    ],
                },
            )
            assert result.status_code == 200, result.text
            clause = next(row for row in mapping["clauses"] if row["clause_id"] == data["clauseId"])
            clause.update(
                disposition="POLICY",
                paths=[path],
                reason="Exact original requirement and field match.",
            )
            checked = await request(
                transport,
                "/api/v1/plan-review-previews",
                method="POST",
                body={
                    "candidateJson": candidate,
                    "sourceText": saved["sourceText"],
                    "mapping": mapping,
                },
            )
            assert checked.status_code == 200, checked.text
            preview = checked.json()
            raw = json.loads(preview["candidateJson"])
            raw["version"] = 3
            repaired = await request(
                transport,
                "/api/v1/plan-drafts",
                method="POST",
                body={
                    "planJson": json.dumps(raw),
                    "sourceText": saved["sourceText"],
                    "dailyMapping": preview["review"]["mapping"],
                    "expectedRevision": 1,
                    "basePlanVersionId": saved["id"],
                },
            )
            assert repaired.status_code == 200, repaired.text
            repaired = repaired.json()
            assert repaired["sourceText"] == saved["sourceText"]
            assert repaired["sourceCoverage"]["coverageComplete"] is True
            assert repaired["sourceCoverage"]["currentReviewBound"] is False
            result = await request(
                transport,
                "/api/v1/plan-review-confirmations",
                method="POST",
                body=confirmation(repaired),
            )
            assert result.status_code == 200, result.text
            current = (await request(transport, "/api/v1/plan-versions/" + repaired["id"])).json()
            assert current["sourceCoverage"]["currentReviewBound"] is True
            assert current["sourceCoverage"]["coverageReviewReceiptHash"] is not None
            frozen = state.inspect()["storage"]
            rejected = await request(
                transport,
                "/api/v1/plan-activations",
                method="POST",
                body=activation(repaired, expected_revision=1),
            )
            assert rejected.status_code == 409, rejected.text
            assert state.inspect()["storage"] == frozen
            for command in (
                {**confirmation(repaired), "sourceHash": "0" * 64},
                {**confirmation(repaired), "planVersionId": saved["id"]},
            ):
                rejected = await request(
                    transport, "/api/v1/plan-review-confirmations", method="POST", body=command
                )
                assert rejected.status_code == 409, rejected.text
                assert state.inspect()["storage"] == frozen

    asyncio.run(scenario())


def test_real_review_activation_changes_context_without_borrowing_old_native_proof(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            setup = await request(
                transport,
                state.prefix + "/source-case",
                method="POST",
                body={"scenario": "contexts"},
            )
            assert setup.status_code == 200, setup.text
            a, b = setup.json()["versionIds"]
            old = (await request(transport, f"/api/v1/plan-versions/{a}/monitor-readiness")).json()
            assert old["summary"] == "NEEDS_REVIEW"
            assert old["snapshot"]["context"]["reviewReceiptHash"] is None
            saved = (await request(transport, f"/api/v1/plan-versions/{a}")).json()
            assert (
                await request(
                    transport,
                    "/api/v1/plan-review-confirmations",
                    method="POST",
                    body=confirmation(saved),
                )
            ).status_code == 200
            current = (await request(transport, f"/api/v1/plan-versions/{a}")).json()
            activated = await request(
                transport,
                "/api/v1/plan-activations",
                method="POST",
                body=activation(current, expected_revision=1),
            )
            assert activated.status_code == 200, activated.text
            fresh = (
                await request(transport, f"/api/v1/plan-versions/{a}/monitor-readiness")
            ).json()
            assert fresh["summary"] == "UNKNOWN"
            assert fresh["snapshot"]["context"]["reviewReceiptHash"] is not None
            assert (
                next(axis for axis in fresh["axes"] if axis["axis"] == "REVIEW_ACTIVATION")["state"]
                == "PASS"
            )
            assert (
                await request(transport, f"/api/v1/plan-versions/{b}/monitor-readiness")
            ).json()["snapshot"]["context"]["planVersionId"] == b
            frozen = state.inspect()["storage"]
            rejected = await request(
                transport,
                "/api/v1/plan-activations",
                method="POST",
                body={
                    **activation(current, expected_revision=2),
                    "planVersionId": b,
                },
            )
            assert rejected.status_code == 409, rejected.text
            assert state.inspect()["storage"] == frozen

    asyncio.run(scenario())


def test_manual_leaves_keep_distinct_true_false_facts_in_native_owner_evaluation(tmp_path):
    async def scenario():
        async with workspace(tmp_path, scenario="manual-leaves") as (state, transport):
            saved = (await request(transport, "/api/v1/plan-versions/" + state.version)).json()
            plan = json.loads(saved["planJson"])
            assert plan["schema_version"] == 5
            assert len(plan["ordinary_rules"]) == 1 and plan["alert_rules"] == []
            owner = plan["ordinary_rules"][0]["rule_id"]
            before = state.inspect()["storage"]
            receipts = []
            for index, truth in enumerate((True, False)):
                before_post = (await request(transport, state.prefix + "/manual-evidence")).json()
                before_readiness = (await request(transport, state.readiness_path)).json()
                result = await request(
                    transport,
                    "/api/v1/plan-facts",
                    method="POST",
                    body={
                        "planVersionId": saved["id"],
                        "contentHash": saved["contentHash"],
                        "factId": f"manual-leaf-{index}",
                        "kind": "VOLUME_OR_CANDLE",
                        "tradeDate": str(state.case.clock.now().date()),
                        "satisfied": truth,
                        "evidence": (
                            f"Synthetic actual observation for exact leaf {index}; result={truth}."
                        ),
                        "expectedRevision": 0,
                        "conditionSelection": {
                            "ownerKind": "ORDINARY_RULE",
                            "ownerId": owner,
                            "conditionPath": f"condition.conditions[{index}]",
                        },
                    },
                )
                assert result.status_code == 200, result.text
                receipts.append(result.json()["id"])
                after_post = (await request(transport, state.prefix + "/manual-evidence")).json()
                after_post_readiness = (await request(transport, state.readiness_path)).json()
                actual, diagnostic = after_post_readiness, after_post
                assert diagnostic["nativeCompletionRecordId"] == diagnostic["evaluationId"]
                assert diagnostic["evaluationId"] != before_post["evaluationId"]
                alignment = diagnostic["sourceAlignment"]
                assert alignment["consumedClosedDays"] > 0
                assert alignment["consumedCalendarRows"] == alignment["storedCalendarRows"]
                assert alignment["consumedClosedDays"] == alignment["storedClosedDays"]
                assert alignment["sessionsMatchOnlyOpenDays"] is True
                assert alignment["consumedSessionRows"] == (
                    alignment["consumedCalendarRows"] - alignment["consumedClosedDays"]
                )
                assert alignment["calendarFingerprintMatches"] is True
                (tmp_path / f"manual-proof-{index}.json").write_text(
                    json.dumps(
                        {
                            "postReceipt": result.json(),
                            "beforePost": {
                                "nativeEvidence": before_post,
                                "readiness": before_readiness,
                            },
                            "afterPublicPost": {
                                "nativeEvidence": after_post,
                                "readiness": after_post_readiness,
                            },
                            "readiness": actual,
                            "nativeEvidence": diagnostic,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                rule = next(row for row in actual["rules"] if row["facts"]["ownerId"] == owner)
                assert [leaf["state"] for leaf in rule["facts"]["leaves"]] == (
                    ["CONDITION_TRUE", "MISSING_INPUT"]
                    if index == 0
                    else ["CONDITION_TRUE", "CONDITION_FALSE"]
                )
                assert rule["state"] == ("MISSING_INPUT" if index == 0 else "CONDITION_FALSE")
            evidence = (await request(transport, state.prefix + "/manual-evidence")).json()
            native = next(
                row["evidence"]
                for row in evidence["evaluation"]["ordinary_evaluations"]
                if row["rule_id"] == owner
            )
            assert [leaf["fact_ids"] for leaf in native["children"]] == [
                [receipts[0]],
                [receipts[1]],
            ]
            assert evidence["evaluation"]["signals"] == []
            assert evidence["nativeCompletionRecordId"] == evidence["evaluationId"]
            assert all(
                leaf["evidenceRefs"] == [evidence["evaluationId"]]
                for leaf in rule["facts"]["leaves"]
            )
            after = state.inspect()["storage"]
            assert after["dailyKinds"]["FACT"] == before["dailyKinds"]["FACT"] + 2
            assert after["source_coverage_review"] == before["source_coverage_review"]

            # A real same-bar cached duty cannot create a fresh evaluation or
            # extend the original condition observation's validity.
            runtime = state.case.composition._runtime
            target = runtime._liveness_owner._pipeline.runtime_status_snapshot()[2][0].target
            deadline = next(
                row
                for row in runtime._scheduler._deadlines_for_open_date(
                    state.case.clock.now().date()
                )
                if row.bar_end == target.bucket_end
            )
            bound = rule["facts"]["observation"]["expiresAt"]
            cached = await runtime._execute_deadline(deadline)
            assert cached and all(row.duplicate for row in cached)
            same = (await request(transport, state.prefix + "/manual-evidence")).json()
            assert same["evaluationId"] == evidence["evaluationId"]
            assert same["nativeCompletionRecordId"] == evidence["nativeCompletionRecordId"]
            reread = (await request(transport, state.readiness_path)).json()
            assert reread["rules"][0]["facts"]["observation"]["expiresAt"] == bound
            assert (
                state.inspect()["storage"]["dailyKinds"]["EVALUATION"]
                == (after["dailyKinds"]["EVALUATION"])
            )

    asyncio.run(scenario())


def test_wrong_manual_leaf_binding_creates_no_fact_or_other_business_write(tmp_path):
    async def scenario():
        async with workspace(tmp_path, scenario="manual-leaves") as (state, transport):
            saved = (await request(transport, "/api/v1/plan-versions/" + state.version)).json()
            owner = json.loads(saved["planJson"])["ordinary_rules"][0]["rule_id"]
            before = state.inspect()["storage"]
            body = {
                "planVersionId": saved["id"],
                "contentHash": saved["contentHash"],
                "factId": "must-not-be-saved",
                "kind": "VOLUME_OR_CANDLE",
                "tradeDate": str(state.case.clock.now().date()),
                "satisfied": False,
                "evidence": (
                    "Synthetic rejected evidence must not satisfy another source-owned leaf."
                ),
                "expectedRevision": 0,
                "conditionSelection": {
                    "ownerKind": "ORDINARY_RULE",
                    "ownerId": owner,
                    "conditionPath": "condition.conditions[0]",
                },
            }
            for changes in (
                {
                    "conditionSelection": {
                        **body["conditionSelection"],
                        "conditionPath": "condition.conditions[99]",
                    }
                },
                {"conditionSelection": {**body["conditionSelection"], "ownerId": "wrong-owner"}},
                {"planVersionId": str(uuid4())},
            ):
                result = await request(
                    transport, "/api/v1/plan-facts", method="POST", body={**body, **changes}
                )
                assert result.status_code in {404, 409, 422}, result.text
                assert state.inspect()["storage"] == before

    asyncio.run(scenario())


def test_closed_calendar_row_loss_revokes_original_manual_owner_proof(tmp_path):
    from trade_plan_monitor.state.models import TradingCalendar

    async def scenario():
        async with workspace(tmp_path, scenario="manual-leaves") as (state, transport):
            before = (await request(transport, state.prefix + "/manual-evidence")).json()
            assert before["nativeCompletionRecordId"] == before["evaluationId"]
            pipeline = state.case.composition._runtime._liveness_owner._pipeline
            inputs = pipeline.daily_evaluations._current_inputs[state.case.plan.symbol]
            closed = next(day for day in inputs.trading_calendar if not day.is_open)
            with state.lifecycle._unit_of_work() as work:
                row = work.daily.session.get(TradingCalendar, (closed.exchange, closed.cal_date))
                work.daily.session.delete(row)
                work.commit()
            observed = (await request(transport, state.readiness_path)).json()
            assert observed["rules"][0]["state"] == "UNKNOWN"
            assert observed["rules"][0]["facts"]["observation"]["availability"] != "CURRENT"
            assert observed["summary"] != "READY_FOR_MONITORING"
            after = (await request(transport, state.prefix + "/manual-evidence")).json()
            assert after["evaluationId"] == before["evaluationId"]
            assert after["sourceAlignment"]["calendarFingerprintMatches"] is False

    asyncio.run(scenario())


def test_calendar_restore_preserves_original_proof_then_next_cycle_creates_new_proof(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from tests.integration.test_plan_readiness_scenarios import observation_only

    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            runtime = state.case.composition._runtime
            owner = runtime._liveness_owner
            guarded = SimpleNamespace(
                pipeline=owner._pipeline, engine=owner._engine, sdk=state.case.sdk
            )
            observations = []

            async def observe():
                before = state.inspect()
                with observation_only(guarded, monkeypatch):
                    response = await request(transport, state.readiness_path)
                assert response.status_code == 200, response.text
                assert state.inspect() == before
                value = response.json()
                assert value["authorityGranted"] is False
                observations.append({"inspection": before, "readiness": value})
                return value

            initial = state.inspect()
            first = await observe()
            assert first["summary"] == "READY_FOR_MONITORING"
            missing = await request(
                transport, state.prefix + "/calendar-loss", method="POST", body={}
            )
            assert missing.status_code == 200, missing.text
            lost = await observe()
            assert lost["summary"] != "READY_FOR_MONITORING"
            assert lost["rules"][0]["state"] == "UNKNOWN"
            assert state.inspect()["completionRecordId"] == initial["completionRecordId"]
            restored = await request(
                transport, state.prefix + "/calendar-restore", method="POST", body={}
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["calendarRow"] == missing.json()["calendarRow"]
            interim = await observe()
            assert interim == first  # Same original proof/timestamps, without renewal.
            assert state.inspect()["completionRecordId"] == initial["completionRecordId"]
            assert state.inspect()["storage"] == initial["storage"]
            next_cycle = await request(
                transport, state.prefix + "/next-target", method="POST", body={}
            )
            assert next_cycle.status_code == 200, next_cycle.text
            current = await observe()
            after = state.inspect()
            assert current["summary"] == "READY_FOR_MONITORING"
            assert current["rules"][0]["state"] == "CONDITION_FALSE"
            assert after["completionRecordId"] != initial["completionRecordId"]
            assert current["rules"][0]["facts"]["leaves"][0]["evidenceRefs"] == [
                after["completionRecordId"]
            ]
            assert (
                current["rules"][0]["facts"]["evaluatedTarget"]
                != (first["rules"][0]["facts"]["evaluatedTarget"])
            )
            for table in (
                "plan_version",
                "source_coverage_review",
                "plan_review_provenance",
                "plan_activation_state",
                "active_plan",
            ):
                assert after["storage"][table] == initial["storage"][table]
            assert after["storage"]["dailyKinds"].get("FACT", 0) == (
                initial["storage"]["dailyKinds"].get("FACT", 0)
            )
            assert after["externalAttempts"] == []
            (tmp_path / "calendar-recovery-evidence.json").write_text(
                json.dumps(
                    {
                        "observations": observations,
                        "removed": missing.json(),
                        "restored": restored.json(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    asyncio.run(scenario())


def test_fixed_calendar_controls_reject_payloads_foreign_clients_and_repeats(tmp_path):
    async def scenario():
        async with workspace(tmp_path) as (state, transport):
            before = state.inspect()
            for suffix in ("calendar-loss", "calendar-restore"):
                path = state.prefix + "/" + suffix
                invalid = await request(
                    transport, path, method="POST", body={"calDate": "2026-01-01"}
                )
                assert invalid.status_code == 422
                async with httpx.ASGITransport(state.app, client=("192.0.2.1", 50000)) as foreign:
                    assert (await request(foreign, path, method="POST", body={})).status_code == 403
                assert state.inspect() == before
            restore = state.prefix + "/calendar-restore"
            loss = state.prefix + "/calendar-loss"
            for path, expected in (
                (restore, 409),
                (loss, 200),
                (loss, 409),
                (restore, 200),
                (restore, 409),
                (loss, 409),
            ):
                result = await request(transport, path, method="POST", body={})
                assert result.status_code == expected, result.text
            assert state.inspect() == before

    asyncio.run(scenario())


@pytest.mark.parametrize("loss", ["closed", "expired"])
def test_two_native_alert_receipts_remain_history_after_current_service_is_lost(
    tmp_path, monkeypatch, loss
):
    from types import SimpleNamespace

    from tests.integration.test_plan_readiness_scenarios import observation_only

    async def scenario():
        async with workspace(tmp_path, scenario="notifications") as (state, transport):
            owner = state.case.composition._runtime._liveness_owner
            guarded = SimpleNamespace(
                pipeline=owner._pipeline,
                engine=owner._engine,
                sdk=state.case.sdk,
                dispatcher=owner._dispatcher,
            )
            observations = []

            async def observe():
                before = state.inspect()
                with observation_only(guarded, monkeypatch):
                    response = await request(transport, state.readiness_path)
                assert response.status_code == 200, response.text
                assert state.inspect() == before
                value = response.json()
                assert value["authorityGranted"] is False
                observations.append({"inspection": before, "readiness": value})
                return value

            def channel(rule):
                return next(
                    row
                    for row in rule["facts"]["notification"]["channels"]
                    if row["channel"] == "IN_APP"
                )

            def notification(value):
                return next(row for row in value["axes"] if row["axis"] == "NOTIFICATION_DELIVERY")

            partial = await observe()
            assert len(partial["rules"]) == 2
            assert all(row["state"] == "CONDITION_TRUE" for row in partial["rules"])
            assert (
                sum(channel(row).get("latestAttempt") is not None for row in partial["rules"]) == 1
            )
            assert notification(partial)["state"] == "UNKNOWN"
            baseline = state.inspect()
            result = await request(
                transport, state.prefix + "/notification-next-check", method="POST", body={}
            )
            assert result.status_code == 200, result.text
            complete = await observe()
            assert notification(complete)["state"] == "PASS"
            events, attempts = [], []
            for row in complete["rules"]:
                receipt = channel(row)["latestAttempt"]
                assert receipt["status"] == "DELIVERED"
                assert channel(row).get("eligible") is None
                events.append(row["facts"]["notification"]["eventId"])
                assert receipt["eventId"] == row["facts"]["notification"]["eventId"]
                attempts.append(receipt["id"])
            assert len(set(events)) == len(set(attempts)) == 2
            before_close = state.inspect()
            assert before_close["storage"]["delivery_attempt"]["count"] == 2
            lost_service = await request(
                transport,
                state.prefix
                + ("/notification-close" if loss == "closed" else "/notification-expire"),
                method="POST",
                body={},
            )
            assert lost_service.status_code == 200, lost_service.text
            lost = await observe()
            assert lost["summary"] == "UNKNOWN" and lost["freshUntil"] is None
            assert notification(lost)["state"] == "UNKNOWN"
            for current, original in zip(lost["rules"], complete["rules"], strict=True):
                assert channel(current)["latestAttempt"] == channel(original)["latestAttempt"]
                assert channel(current).get("eligible") is None
                for field in ("createdAt", "target"):
                    assert (
                        current["facts"]["notification"][field]
                        == original["facts"]["notification"][field]
                    )
            assert await observe() == lost
            assert state.inspect() == {**before_close, "now": state.case.clock.now().isoformat()}
            for table in (
                "plan_version",
                "plan_review_provenance",
                "source_coverage_review",
                "active_plan",
                "plan_activation_state",
            ):
                assert before_close["storage"][table] == baseline["storage"][table]
            assert before_close["storage"]["dailyKinds"].get("FACT", 0) == 0
            from trade_plan_monitor.state.models import DeliveryAttempt

            with state.lifecycle._unit_of_work() as work:
                for rule in complete["rules"]:
                    receipt = channel(rule)["latestAttempt"]
                    row = work.daily.session.get(DeliveryAttempt, receipt["id"])
                    assert (row.event_id, row.channel, row.status, row.delivered_at) == (
                        receipt["eventId"],
                        "IN_APP",
                        "DELIVERED",
                        receipt["deliveredAt"],
                    )
            (tmp_path / "notification-evidence.json").write_text(
                json.dumps(
                    {"loss": loss, "observations": observations}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )

    asyncio.run(scenario())


def test_fixed_notification_controls_are_loopback_one_shot_and_accept_no_selected_inputs(tmp_path):
    async def scenario():
        async with workspace(tmp_path, scenario="notifications") as (state, transport):
            before = state.inspect()
            for suffix in ("notification-next-check", "notification-close", "notification-expire"):
                path = state.prefix + "/" + suffix
                invalid = await request(
                    transport, path, method="POST", body={"eventId": "selected"}
                )
                assert invalid.status_code == 422
                async with httpx.ASGITransport(state.app, client=("192.0.2.1", 50000)) as foreign:
                    assert (await request(foreign, path, method="POST", body={})).status_code == 403
                assert state.inspect() == before
            check = state.prefix + "/notification-next-check"
            close = state.prefix + "/notification-close"
            expire = state.prefix + "/notification-expire"
            for path, expected in (
                (close, 409),
                (expire, 409),
                (check, 200),
                (check, 409),
                (close, 200),
                (close, 409),
                (expire, 409),
            ):
                response = await request(transport, path, method="POST", body={})
                assert response.status_code == expected, response.text
        async with workspace(tmp_path / "automatic") as (state, transport):
            before = state.inspect()
            for suffix in ("notification-next-check", "notification-close", "notification-expire"):
                response = await request(
                    transport, state.prefix + "/" + suffix, method="POST", body={}
                )
                assert response.status_code == 409
            assert state.inspect() == before

    asyncio.run(scenario())
