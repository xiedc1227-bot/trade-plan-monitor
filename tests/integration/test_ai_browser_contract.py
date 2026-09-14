"""Pin the production serializer shape consumed by the TypeScript regression test."""

import json
from datetime import datetime
from pathlib import Path

from tests.unit.test_ai_plan_extraction_v4 import _extract, _valid_output

from trade_plan_monitor.ai.models import AIUsageSnapshot
from trade_plan_monitor.web.ai_service import _completed_extraction_view

FIXTURE = Path(__file__).parents[2] / "web/tests/fixtures/ai-partial-extraction.json"


def production_partial_view():
    timestamp = datetime.fromisoformat("2026-09-14T10:00:00+08:00")
    return _completed_extraction_view(
        result=_extract(_valid_output()).model_copy(
            update={
                "usage": AIUsageSnapshot(
                    prompt_tokens=100, completion_tokens=100, total_tokens=200
                ),
            }
        ),
        submitted_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
        diagnostic_status="RECORDED",
    ).model_dump(mode="json", by_alias=True)


def test_browser_partial_extraction_fixture_matches_production_serialization():
    assert production_partial_view() == json.loads(FIXTURE.read_text(encoding="utf-8"))
