"""Corrections are fenced, bounded physical calls with durable feedback."""

import asyncio

import pytest
from tests.integration.test_plan_preparation_worker import service_setup

from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor
from trade_plan_monitor.domain.plan_validation import ValidationIssue


@pytest.mark.parametrize("bad_calls", [1, 2, 5])
def test_processing_errors_correct_at_most_twice_and_never_approve(tmp_path, bad_calls):
    async def scenario():
        service, store, jobs, initial, _ = service_setup(tmp_path)
        original = service._extractor.call
        calls = []

        def call(identity, source, token, feedback=(), repair_context=None):
            calls.append((str(identity), feedback))
            assert store.get("one").work_claim.phase == "CALLING"
            result = original(identity, source, token)
            result = result.model_copy(update={"preparation_contract": "SEMANTIC_PATCH"})
            if len(calls) <= bad_calls:
                result = result.model_copy(
                    update={
                        "validation_issues": (
                            ValidationIssue(
                                code="DAILY_SOURCE_BINDING_REQUIRED",
                                path="position.max_qty",
                                message="Unbound extracted value",
                                severity="ERROR",
                                activationBlocking=True,
                            ),
                        )
                    }
                )
            else:
                result = result.model_copy(update={"validation_issues": ()})
            return result

        service._extractor = PreparationExtractor(call, max_repairs=2)
        try:
            await service.submit_extraction(
                "one", expected_revision=initial.revision, idempotency_key="extract-correct"
            )
            await service.wait_for_drain()
            record = store.get("one")
            assert len(calls) == min(bad_calls + 1, 3)
            assert len({identity for identity, _ in calls}) == len(calls)
            assert calls[0][1] == ()
            assert record.attempts[0].repair_context_json is not None
            assert all(
                feedback == ("DAILY_SOURCE_BINDING_REQUIRED: position.max_qty",)
                for _, feedback in calls[1:]
            )
            assert [a.error_code for a in record.attempts[:-1]] == ["AI_REPAIR_REQUIRED"] * (
                len(calls) - 1
            )
            assert record.status == "CANDIDATE" and record.review is None
            assert record.work_claim is None
            assert bool(record.candidate.issues) == (bad_calls > 2)
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_missing_business_fact_does_not_trigger_correction(tmp_path):
    async def scenario():
        service, store, jobs, initial, calls = service_setup(tmp_path)
        original = service._extractor.call

        def call(identity, source, token, feedback=(), repair_context=None):
            result = original(identity, source, token)
            result = result.model_copy(update={"preparation_contract": "SEMANTIC_PATCH"})
            return result.model_copy(
                update={
                    "validation_issues": (
                        ValidationIssue(
                            code="PLAN_PARAMETER_REQUIRED",
                            path="position.max_qty",
                            message="Maximum position absent",
                            severity="ERROR",
                            activationBlocking=True,
                        ),
                    )
                }
            )

        service._extractor = PreparationExtractor(call, max_repairs=2)
        try:
            await service.submit_extraction(
                "one", expected_revision=initial.revision, idempotency_key="extract-unknown"
            )
            await service.wait_for_drain()
            record = store.get("one")
            assert len(calls) == len(record.attempts) == 1
            assert record.candidate.validation == "UNRESOLVED"
        finally:
            await service.stop()

    asyncio.run(scenario())
