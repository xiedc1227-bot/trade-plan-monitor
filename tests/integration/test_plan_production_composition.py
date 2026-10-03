from __future__ import annotations

import asyncio
import sqlite3
import weakref
from datetime import datetime
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.plan_codec import (
    dump_plan_json,
    dump_plan_yaml,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
from trade_plan_monitor.web import plan_service as plan_service_module
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.daily_plans import DailySupplementCommand
from trade_plan_monitor.web.routers.plans import (
    PlanActivationCommand,
    PlanDeactivationCommand,
    PlanDocumentFormat,
    PlanDraftCommand,
    PlanImportCommand,
    PlanReviewConfirmationCommand,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FIXED_NOW = datetime(2026, 9, 3, 10, 30, tzinfo=_SHANGHAI)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _source():
    raw = unified_payload()
    raw.update(plan_id="huaya-smart", symbol="003043.SZ", market="SZSE")
    return dump_plan_yaml(UnifiedTradePlan.model_validate(raw))


def _draft(**values):
    draft = UnifiedPlanDraft.model_validate_json(values["plan_json"])
    values["daily_mapping"] = reviewed_mapping(draft, values["source_text"])
    return PlanDraftCommand(**values)


async def _save(service, *, command, context):
    mapping = command.daily_mapping
    if mapping is None:
        return await service.save_plan_draft(command=command, context=context)
    registered = await service.read_daily_supplements(candidate_json=command.plan_json)
    if registered["supplements"] != [item.model_dump(mode="json") for item in mapping.supplements]:
        await service.mutate_daily(
            operation="SUPPLEMENT",
            command=DailySupplementCommand(
                candidate_json=command.plan_json,
                content_hash=mapping.candidate_content_hash,
                supplements=mapping.supplements,
                expected_revision=registered["revision"],
            ),
            context=_context("supplement-" + context.idempotency_key),
        )
    return await service.save_plan_draft(command=command, context=context)


async def _confirm(service, saved, key):
    result = await service.confirm_plan_review(
        command=PlanReviewConfirmationCommand(
            plan_version_id=saved.id,
            content_hash=saved.content_hash,
            source_hash=saved.source_hash,
            review_evidence_hash=saved.review_evidence_hash,
            expected_revision=saved.review_revision,
        ),
        context=_context(key),
    )
    assert result.can_activate
    return await service.get_plan_version(version_id=str(saved.id))


def _context(key: str) -> MutationContext:
    return MutationContext(idempotency_key=key, request_id="a" * 32)


class _AIService:
    pass


class _BacktestLifecycle:
    read_service = object()
    operation_service = object()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class _OrderedRuntimeLifecycle:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> object:
        self._events.append("runtime.start")
        return object()

    async def stop(self) -> None:
        self._events.append("runtime.stop")


class _OrderedAILifecycle:
    ai_operation_service = object()
    plan_extraction_service = object()

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> object:
        self._events.append("ai.start")
        return object()

    async def stop(self) -> None:
        self._events.append("ai.stop")


class _OrderedPlanLifecycle:
    operation_service = object()

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> None:
        self._events.append("plan.start")

    async def stop(self) -> None:
        self._events.append("plan.stop")


class _OrderedBacktestLifecycle:
    read_service = object()
    operation_service = object()

    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self._events = events
        self._fail_start = fail_start

    async def start(self) -> None:
        self._events.append("backtest.start")
        if self._fail_start:
            raise RuntimeError("backtest start failed")

    async def stop(self) -> None:
        self._events.append("backtest.stop")


def _write_distribution(directory: Path) -> None:
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!doctype html><script type='module' src='/assets/app.js'></script>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("export {};", encoding="utf-8")


def test_production_app_lazily_injects_the_persistent_plan_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "state" / "monitor.sqlite3"
    distribution = tmp_path / "dist"
    _write_distribution(distribution)
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)

    with create_production_app(
        monitor_contract_version=1,
        database_path=database_path,
        ai_service=_AIService(),
        backtest_lifecycle_factory=_BacktestLifecycle,
    ) as app:
        assert not database_path.exists()
        assert not hasattr(app.state, "plan_operation_service")
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            inactive = client.get("/api/v1/plan-activation-states/003043.SZ")
            assert inactive.status_code == 200
            assert inactive.json()["active"] is False
            assert inactive.json()["planVersionId"] is None
            assert inactive.json()["revision"] == 0
            response = client.get("/api/v1/plan-versions")
            assert response.status_code == 200
            assert response.json() == {"items": [], "limit": 20, "offset": 0, "total": 0}
            assert database_path.is_file()
            assert hasattr(app.state, "plan_operation_service")
            imported = client.post(
                "/api/v1/plan-imports",
                headers={"Idempotency-Key": "production-import-v1"},
                json={
                    "document": _source(),
                    "expectedRevision": 0,
                    "format": "YAML",
                    "symbol": "003043.SZ",
                },
            )
            assert imported.status_code == 200
            imported_id = imported.json()["id"]
        assert not hasattr(app.state, "plan_operation_service")

    with create_production_app(
        monitor_contract_version=1,
        database_path=database_path,
        ai_service=_AIService(),
        backtest_lifecycle_factory=_BacktestLifecycle,
    ) as restarted_app:
        with TestClient(restarted_app, base_url="http://127.0.0.1:8765") as client:
            page = client.get("/api/v1/plan-versions")
            detail = client.get(f"/api/v1/plan-versions/{imported_id}")

    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["id"] == imported_id


def test_plan_lifespan_starts_in_dependency_order_and_stops_in_reverse_order() -> None:
    events: list[str] = []
    plan_lifecycle = _OrderedPlanLifecycle(events)
    app = create_app(
        runtime_factory=lambda: _OrderedRuntimeLifecycle(events),
        ai_lifecycle_factory=lambda: _OrderedAILifecycle(events),
        plan_lifecycle_factory=lambda: plan_lifecycle,
        backtest_lifecycle_factory=lambda: _OrderedBacktestLifecycle(events),
    )

    with TestClient(app):
        assert app.state.plan_operation_service is plan_lifecycle.operation_service
        assert events == [
            "runtime.start",
            "ai.start",
            "plan.start",
            "backtest.start",
        ]

    assert events == [
        "runtime.start",
        "ai.start",
        "plan.start",
        "backtest.start",
        "backtest.stop",
        "plan.stop",
        "ai.stop",
        "runtime.stop",
    ]
    assert not hasattr(app.state, "plan_operation_service")
    assert not hasattr(app.state, "plan_web_lifecycle")


def test_plan_lifespan_is_cleaned_up_when_backtest_start_fails() -> None:
    events: list[str] = []
    app = create_app(
        runtime_factory=lambda: _OrderedRuntimeLifecycle(events),
        ai_lifecycle_factory=lambda: _OrderedAILifecycle(events),
        plan_lifecycle_factory=lambda: _OrderedPlanLifecycle(events),
        backtest_lifecycle_factory=lambda: _OrderedBacktestLifecycle(
            events,
            fail_start=True,
        ),
    )

    with pytest.raises(RuntimeError, match="backtest start failed"), TestClient(app):
        pass

    assert events == [
        "runtime.start",
        "ai.start",
        "plan.start",
        "backtest.start",
        "backtest.stop",
        "plan.stop",
        "ai.stop",
        "runtime.stop",
    ]
    assert not hasattr(app.state, "plan_operation_service")
    assert not hasattr(app.state, "plan_web_lifecycle")


def test_plan_operations_and_idempotency_survive_independent_lifecycles(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source_v1 = _source()
    plan_v1 = load_plan_yaml(source_v1)
    save_command = _draft(
        plan_json=dump_plan_json(plan_v1),
        source_text=source_v1,
        expected_revision=0,
    )

    async def scenario() -> None:
        first = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        assert not database_path.exists()
        await first.start()
        saved = await _save(
            first,
            command=save_command,
            context=_context("save-v1"),
        )
        assert saved.review_id is None
        assert not saved.can_activate
        assert saved.source_text == source_v1
        assert saved.status.value == "DRAFT"
        await first.stop()

        second = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await second.start()
        replayed = await _save(
            second,
            command=save_command,
            context=_context("save-v1"),
        )
        assert replayed == saved
        page = await second.list_plan_versions(
            offset=0,
            limit=20,
            symbol="003043.SZ",
            status=None,
            can_activate=None,
        )
        assert page.total == 1
        assert len(page.items) == 1
        assert page.items[0].id == saved.id
        assert page.items[0].plan_hash == saved.plan_hash
        assert page.items[0].can_activate is saved.can_activate
        loaded = await second.get_plan_version(version_id=str(saved.id))
        assert loaded == saved
        inactive = await second.get_plan_activation_state(symbol="003043.SZ")
        assert inactive is not None
        assert inactive.active is False
        assert inactive.plan_version_id is None
        assert inactive.revision == 0

        reviewed_v1 = await _confirm(second, saved, "review-v1")
        assert reviewed_v1.review_id is not None
        activated_v1 = await second.activate_plan(
            command=PlanActivationCommand(
                plan_version_id=saved.id,
                review_id=reviewed_v1.review_id,
                content_hash=reviewed_v1.content_hash,
                source_hash=reviewed_v1.source_hash,
                review_evidence_hash=reviewed_v1.review_evidence_hash,
                review_revision=reviewed_v1.review_revision,
                expected_revision=inactive.revision,
            ),
            context=_context("activate-v1"),
        )
        assert activated_v1.active is True
        assert activated_v1.revision == 1
        await second.stop()

        source_v2 = source_v1.replace("\nversion: 1\n", "\nversion: 2\n", 1)
        third = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await third.start()
        restored_active = await third.get_plan_activation_state(symbol="003043.SZ")
        assert restored_active == activated_v1
        imported_v2 = await third.import_plan(
            command=PlanImportCommand(
                format=PlanDocumentFormat.YAML,
                document=source_v2,
                symbol="003043.SZ",
                expected_revision=restored_active.revision,
            ),
            context=_context("import-v2"),
        )
        assert imported_v2.version == 2
        assert imported_v2.source_text == source_v2
        assert imported_v2.review_issues == ()
        assert not imported_v2.can_activate
        reviewed_draft = await _save(
            third,
            command=_draft(
                base_plan_version_id=imported_v2.id,
                plan_json=imported_v2.plan_json,
                source_text=source_v2,
                expected_revision=restored_active.revision,
            ),
            context=_context("reviewable-import-v2"),
        )
        reviewed_draft = await _confirm(third, reviewed_draft, "review-import-v2")
        activated_v2 = await third.activate_plan(
            command=PlanActivationCommand(
                plan_version_id=reviewed_draft.id,
                review_id=reviewed_draft.review_id,
                content_hash=reviewed_draft.content_hash,
                source_hash=reviewed_draft.source_hash,
                review_evidence_hash=reviewed_draft.review_evidence_hash,
                review_revision=reviewed_draft.review_revision,
                expected_revision=restored_active.revision,
            ),
            context=_context("activate-v2"),
        )
        assert activated_v2.revision == 2
        await third.stop()

        fourth = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await fourth.start()
        assert await fourth.get_plan_activation_state(symbol="003043.SZ") == activated_v2
        deactivated = await fourth.deactivate_plan(
            command=PlanDeactivationCommand(
                symbol="003043.SZ",
                expected_revision=activated_v2.revision,
            ),
            context=_context("deactivate-v2"),
        )
        assert deactivated.active is False
        assert deactivated.plan_version_id is None
        assert deactivated.revision == 3
        await fourth.stop()

        fifth = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await fifth.start()
        assert await fifth.get_plan_activation_state(symbol="003043.SZ") == deactivated
        restored_page = await fifth.list_plan_versions(
            offset=0,
            limit=20,
            symbol="003043.SZ",
            status=None,
            can_activate=None,
        )
        assert restored_page.total == 3
        assert {item.status.value for item in restored_page.items} == {"DRAFT", "SUPERSEDED"}

        with pytest.raises(ApiError) as reused:
            await _save(
                fifth,
                command=save_command.model_copy(update={"source_text": "different provenance"}),
                context=_context("save-v1"),
            )
        assert reused.value.code is ApiErrorCode.VALIDATION_ERROR
        await fifth.stop()

    asyncio.run(scenario())


def test_base_plan_version_assigns_the_next_version_and_validates_identity(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source = _source()
    plan_v1 = load_plan_yaml(source)

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        base = await _save(
            service,
            command=_draft(
                plan_json=dump_plan_json(plan_v1),
                source_text=source,
                expected_revision=0,
            ),
            context=_context("save-base-v1"),
        )

        submitted = plan_v1.model_copy(update={"version": 999})
        derived_command = _draft(
            base_plan_version_id=base.id,
            plan_json=dump_plan_json(submitted),
            source_text="server-versioned draft",
            expected_revision=0,
        )
        derived = await _save(
            service,
            command=derived_command,
            context=_context("save-derived-v2"),
        )
        replayed = await _save(
            service,
            command=derived_command,
            context=_context("save-derived-v2"),
        )

        assert derived.version == 2
        assert load_plan_json(derived.plan_json).version == 2
        assert replayed == derived

        for field, value in (("plan_id", "other-plan"), ("symbol", "000001.SZ")):
            mismatched = submitted.model_copy(update={field: value})
            with pytest.raises(ApiError) as rejected:
                await _save(
                    service,
                    command=_draft(
                        base_plan_version_id=base.id,
                        plan_json=dump_plan_json(mismatched),
                        source_text=f"mismatched {field}",
                        expected_revision=0,
                    ),
                    context=_context(f"reject-mismatched-{field}"),
                )
            assert rejected.value.code is ApiErrorCode.VALIDATION_ERROR

        with pytest.raises(ApiError) as missing:
            await _save(
                service,
                command=derived_command.model_copy(
                    update={"base_plan_version_id": "90000000-0000-4000-8000-000000000009"}
                ),
                context=_context("missing-base"),
            )
        assert missing.value.code is ApiErrorCode.NOT_FOUND

        page = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=plan_v1.symbol,
            status=None,
            can_activate=None,
        )
        assert page.total == 2
        assert {item.version for item in page.items} == {1, 2}
        await service.stop()

    asyncio.run(scenario())


def test_base_plan_version_refuses_a_javascript_unsafe_successor(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source = _source()
    plan = load_plan_yaml(source)
    last_safe_plan = plan.model_copy(update={"version": _MAX_SAFE_INTEGER})

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        base = await _save(
            service,
            command=_draft(
                plan_json=dump_plan_json(last_safe_plan),
                source_text=source,
                expected_revision=0,
            ),
            context=_context("save-last-safe-version"),
        )

        with pytest.raises(ApiError) as rejected:
            await _save(
                service,
                command=_draft(
                    base_plan_version_id=base.id,
                    plan_json=dump_plan_json(plan),
                    source_text="unsafe successor",
                    expected_revision=0,
                ),
                context=_context("reject-unsafe-successor"),
            )

        assert rejected.value.code is ApiErrorCode.VALIDATION_ERROR
        page = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=plan.symbol,
            status=None,
            can_activate=None,
        )
        assert page.total == 1
        assert page.items[0].version == _MAX_SAFE_INTEGER
        await service.stop()

    asyncio.run(scenario())


def test_concurrent_base_plan_drafts_allocate_distinct_versions_and_replay(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source = _source()
    plan_v1 = load_plan_yaml(source)

    async def scenario() -> None:
        seed = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await seed.start()
        base = await _save(
            seed,
            command=_draft(
                plan_json=dump_plan_json(plan_v1),
                source_text=source,
                expected_revision=0,
            ),
            context=_context("seed-base-v1"),
        )
        await seed.stop()

        first = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        second = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await first.start()
        await second.start()
        submitted = plan_v1.model_copy(update={"version": 500})
        first_command = _draft(
            base_plan_version_id=base.id,
            plan_json=dump_plan_json(submitted),
            source_text="concurrent first",
            expected_revision=0,
        )
        second_command = _draft(
            base_plan_version_id=base.id,
            plan_json=first_command.plan_json,
            source_text="concurrent second",
            expected_revision=0,
        )

        first_result, second_result = await asyncio.gather(
            _save(
                first,
                command=first_command,
                context=_context("concurrent-derived-first"),
            ),
            _save(
                second,
                command=second_command,
                context=_context("concurrent-derived-second"),
            ),
        )
        replayed = await _save(
            second,
            command=first_command,
            context=_context("concurrent-derived-first"),
        )
        shared_command = _draft(
            base_plan_version_id=base.id,
            plan_json=first_command.plan_json,
            source_text="concurrent shared intent",
            expected_revision=0,
        )
        shared_first, shared_second = await asyncio.gather(
            _save(
                first,
                command=shared_command,
                context=_context("concurrent-shared-intent"),
            ),
            _save(
                second,
                command=shared_command,
                context=_context("concurrent-shared-intent"),
            ),
        )

        assert {first_result.version, second_result.version} == {2, 3}
        assert first_result.id != second_result.id
        assert replayed == first_result
        assert shared_first == shared_second
        assert shared_first.version == 4
        page = await first.list_plan_versions(
            offset=0,
            limit=20,
            symbol=plan_v1.symbol,
            status=None,
            can_activate=None,
        )
        assert page.total == 4
        assert {item.version for item in page.items} == {1, 2, 3, 4}
        await second.stop()
        await first.stop()

    asyncio.run(scenario())


def test_plan_import_service_rejects_a_cross_symbol_command(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    document = _source()

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        unsafe_command = PlanImportCommand.model_construct(
            format=PlanDocumentFormat.YAML,
            document=document,
            symbol="600000.SH",
            expected_revision=0,
        )

        with pytest.raises(ApiError) as rejected:
            await service.import_plan(
                command=unsafe_command,
                context=_context("cross-symbol-import"),
            )
        assert rejected.value.code is ApiErrorCode.VALIDATION_ERROR

        page = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=None,
            status=None,
            can_activate=None,
        )
        assert page.total == 0
        await service.stop()

    asyncio.run(scenario())


def test_plan_service_rejects_javascript_unsafe_documents_without_persisting(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    plan = load_plan_yaml(_source()).model_copy(update={"version": _MAX_SAFE_INTEGER + 1})
    plan_json = dump_plan_json(plan)

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        draft = PlanDraftCommand.model_construct(
            base_plan_version_id=None,
            plan_json=plan_json,
            source_text="unsafe draft",
            review_issues=(),
            expected_revision=0,
        )
        imported = PlanImportCommand.model_construct(
            document=plan_json,
            expected_revision=0,
            format=PlanDocumentFormat.JSON,
            symbol=plan.symbol,
        )

        with pytest.raises(ApiError) as rejected_draft:
            await _save(
                service,
                command=draft,
                context=_context("unsafe-service-draft"),
            )
        with pytest.raises(ApiError) as rejected_import:
            await service.import_plan(
                command=imported,
                context=_context("unsafe-service-import"),
            )

        assert rejected_draft.value.code is ApiErrorCode.VALIDATION_ERROR
        assert rejected_import.value.code is ApiErrorCode.VALIDATION_ERROR

        page = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=None,
            status=None,
            can_activate=None,
        )
        assert page.total == 0
        await service.stop()

    asyncio.run(scenario())


def test_large_plan_documents_are_excluded_from_the_list_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    plan = load_plan_yaml(_source())
    source_text = "large provenance:" + "x" * 200_000

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        saved = await _save(
            service,
            command=_draft(
                plan_json=dump_plan_json(plan),
                source_text=source_text,
                expected_revision=0,
            ),
            context=_context("save-large-plan"),
        )

        page = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=plan.symbol,
            status=None,
            can_activate=None,
        )
        serialized_page = page.model_dump_json(by_alias=True)
        detail = await service.get_plan_version(version_id=str(saved.id))

        assert page.total == 1
        assert page.items[0].id == saved.id
        assert "planJson" not in serialized_page
        assert "sourceText" not in serialized_page
        assert "reviewIssues" not in serialized_page
        assert "validationIssues" not in serialized_page
        assert len(serialized_page.encode("utf-8")) < 2_000
        assert detail is not None
        assert detail.source_text == source_text
        await service.stop()

    asyncio.run(scenario())


def test_can_activate_filter_retains_only_the_requested_result_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source = _source()
    template = load_plan_yaml(source)
    alive = 0
    peak_alive = 0
    original_summary = plan_service_module._plan_version_summary

    def release_view() -> None:
        nonlocal alive
        alive -= 1

    def tracked_summary(record: object):
        nonlocal alive, peak_alive
        summary = original_summary(record)
        alive += 1
        peak_alive = max(peak_alive, alive)
        weakref.finalize(summary, release_view)
        return summary

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        for version in range(1, 13):
            plan = template.model_copy(update={"version": version})
            saved = await _save(
                service,
                command=_draft(
                    plan_json=dump_plan_json(plan),
                    source_text=f"source version {version}",
                    expected_revision=0,
                ),
                context=_context(f"save-window-{version}"),
            )
            await _confirm(service, saved, f"review-window-{version}")

        unfiltered = await service.list_plan_versions(
            offset=0,
            limit=20,
            symbol=template.symbol,
            status=None,
            can_activate=None,
        )
        expected_ids = tuple(item.id for item in unfiltered.items[5:7])
        monkeypatch.setattr(plan_service_module, "_plan_version_summary", tracked_summary)

        filtered = await service.list_plan_versions(
            offset=5,
            limit=2,
            symbol=template.symbol,
            status=None,
            can_activate=True,
        )

        assert filtered.total == 12
        assert tuple(item.id for item in filtered.items) == expected_ids
        assert peak_alive <= filtered.limit + 1
        await service.stop()

    asyncio.run(scenario())


def test_plan_lifecycle_rejects_backtest_database_without_modifying_it(tmp_path: Path) -> None:
    database_path = tmp_path / "backtest-results.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE backtest_run (run_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO backtest_run VALUES ('preserve-me')")

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path)
        with pytest.raises(ValueError, match="another storage domain"):
            await service.start()

    asyncio.run(scenario())
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            ).fetchall()
        }
        assert tables == {"backtest_run"}
        assert connection.execute("SELECT run_id FROM backtest_run").fetchall() == [
            ("preserve-me",)
        ]


def test_plan_lifecycle_accepts_the_live_market_index_projection_tables_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    engine = create_sqlite_engine(database_path)
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()

    async def scenario() -> None:
        first = PersistentPlanWebLifecycle(database_path=database_path)
        await first.start()
        await first.stop()

        restarted = PersistentPlanWebLifecycle(database_path=database_path)
        await restarted.start()
        await restarted.stop()

    asyncio.run(scenario())


def test_unresolved_review_remains_an_activation_blocker_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source_text = _source()
    raw = load_plan_yaml(source_text).model_dump(mode="json")
    raw["ordinary_rules"][0]["confirmation"] = None
    plan = UnifiedPlanDraft.model_validate(raw)

    async def scenario() -> None:
        first = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await first.start()
        saved = await _save(
            first,
            command=_draft(
                plan_json=plan.model_dump_json(),
                source_text=source_text,
                expected_revision=0,
            ),
            context=_context("save-blocked-v1"),
        )
        await first.stop()

        restarted = PersistentPlanWebLifecycle(
            database_path=database_path,
            clock=lambda: _FIXED_NOW,
        )
        await restarted.start()
        restored = await restarted.get_plan_version(version_id=str(saved.id))
        assert restored is not None
        assert restored.daily_issues == saved.daily_issues
        assert restored.can_activate is False
        assert any(issue.activation_blocking for issue in restored.validation_issues)
        assert any("confirmation" in issue.path for issue in restored.daily_issues)
        with pytest.raises(ApiError) as blocked:
            await restarted.activate_plan(
                command=PlanActivationCommand(
                    plan_version_id=saved.id,
                    expected_revision=0,
                ),
                context=_context("activate-blocked-v1"),
            )
        assert blocked.value.code is ApiErrorCode.CONFLICT
        await restarted.stop()

    asyncio.run(scenario())
