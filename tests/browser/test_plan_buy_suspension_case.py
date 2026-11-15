"""PBS fixture isolation and fixed-input validation, without launching a service."""

import pytest
from tests.browser.plan_buy_suspension_case import DIST, source_case, validate_static
from tests.browser.plan_readiness_server import REPOSITORY, create_fixture_app


@pytest.mark.parametrize("directory", [None, REPOSITORY / "web/dist",
    REPOSITORY / "src/trade_plan_monitor/web/dist"])
def test_pbs_rejects_implicit_or_shared_static(directory):
    with pytest.raises(ValueError, match="exact isolated"):
        validate_static(directory)


def test_pbs_frozen_distribution_is_exact():
    validate_static(DIST)


def test_pbs_rejects_nonempty_database_root(tmp_path):
    root = REPOSITORY / ".pytest_cache/pbs/t12/a11/nonempty-isolation-check"
    root.mkdir(parents=True, exist_ok=True)
    (root / "occupied.txt").write_text("must not touch")
    with pytest.raises(ValueError, match="fresh isolated"):
        create_fixture_app(root, scenario="buy-suspension", static_directory=DIST)
    assert (root / "occupied.txt").read_text() == "must not touch"


def test_pbs_rejects_database_outside_project_cache():
    with pytest.raises(ValueError, match="project-local"):
        create_fixture_app(REPOSITORY / "build/pbs/t12/forbidden-database",
            scenario="buy-suspension", static_directory=DIST)


def test_pbs_sources_do_not_pregrant_guard_supplements():
    for replacement in (False, True):
        draft, source, mapping = source_case(replacement=replacement)
        assert draft.schema_version == 10 and draft.buy_suspension is not None
        assert "再次跌破24.20" in source
        assert mapping.supplements == ()
        assert not any(b.path.startswith("buy_suspension.") for b in mapping.bindings)


def test_pbs_offline_v13_output_uses_actual_extraction_parser():
    import asyncio
    from uuid import uuid4

    from tests.browser.plan_buy_suspension_case import PBSExtraction

    from trade_plan_monitor.ai.extraction import extract_plan

    async def scenario():
        service = PBSExtraction(config_path=REPOSITORY / "never-read.yaml")
        await service.start()
        try:
            for replacement in (False, True):
                _, source, _ = source_case(replacement=replacement)
                result = await extract_plan(request_id=uuid4(), source_text=source,
                    config=service._binding.config, provider=service._binding.provider)
                assert result.status.value == "SUCCEEDED", result.model_dump(mode="json")
        finally:
            await service.stop()
    asyncio.run(scenario())
