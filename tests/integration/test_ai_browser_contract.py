"""Pin the production serializer shape consumed by the TypeScript regression test."""

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from tests.unit.test_current_plan_extraction_security import current_output, extract

from trade_plan_monitor.ai.models import AIUsageSnapshot
from trade_plan_monitor.web.ai_service import _completed_extraction_view

FIXTURE = Path(__file__).parents[2] / "web/tests/fixtures/ai-partial-extraction.json"


def production_partial_view():
    timestamp = datetime.fromisoformat("2026-09-14T10:00:00+08:00")
    output = current_output()
    output["draft"]["activation"] = None
    output["draft"]["position"]["max_qty"] = None
    return _completed_extraction_view(
        result=extract(output).model_copy(
            update={
                "request_id": UUID("51e37676-d62d-4bbc-873a-2b389f8d4611"),
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
