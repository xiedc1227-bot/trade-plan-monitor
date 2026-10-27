"""Current supplement provenance uses the actual caller-owned read clock."""

from datetime import timedelta

import pytest
from sqlalchemy import text
from tests.integration.preparation_review_current_fixtures import (
    field_source,
    reviewed_mapping,
    single_draft,
)
from tests.integration.test_source_coverage_authority import _command
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.source_coverage_authority import (
    read_version_coverage,
    require_current_coverage,
    require_repository_review,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError


def _save(state, *, registration_at=_NOW):
    draft = single_draft()
    source = field_source(draft, missing=("position.max_qty",))
    mapping = reviewed_mapping(draft, source)
    assert len(mapping.supplements) == 1
    digest = daily_draft_content_sha256(draft)
    with state.work() as work:
        work.daily.clock = lambda: registration_at
        work.daily.save(daily_hash("daily-human-supplements-v1", dict(
            symbol=draft.symbol, content_hash=digest)), kind="DRAFT", symbol=draft.symbol,
            lineage=digest, expected_revision=0, payload=dict(content_hash=digest,
                source="EXPLICIT_HUMAN_OPERATION",
                supplements=[row.model_dump(mode="json") for row in mapping.supplements]))
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                    clock=lambda: _NOW)
        work.commit()
    return identity


def _rows(work):
    return {table: tuple(work.daily.session.execute(text(f"SELECT * FROM {table}")).all())
            for table in (DailyRecord.__tablename__, "audit_log", "source_coverage_assessment",
                          "source_coverage_review")}


def test_actual_registered_supplement_reads_current_proof_without_writes(state):
    identity = _save(state)
    with state.work() as work:
        before = _rows(work)
        details = work.plans.get_version_details(identity)
        proof = read_version_coverage(work, details)
        assert proof.assessment.coverage_complete
        assert require_current_coverage(work, details) == proof
        assert _rows(work) == before


def test_actual_repository_review_uses_its_owned_clock_for_registered_supplement(state):
    identity = _save(state)
    with state.work() as work:
        confirm_daily_review(work, _command(work, identity), clock=lambda: _NOW)
        work.commit()
    with state.work() as work:
        before = _rows(work)
        assert require_repository_review(work.plans, identity).assessment.coverage_complete
        assert _rows(work) == before


def test_future_registered_supplement_is_integrity_failure_without_writes(state):
    identity = _save(state, registration_at=_NOW + timedelta(minutes=1))
    with state.work() as work:
        before = _rows(work)
        details = work.plans.get_version_details(identity)
        with pytest.raises(SourceCoverageIntegrityError):
            require_current_coverage(work, details)
        assert _rows(work) == before
