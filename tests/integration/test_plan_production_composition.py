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

from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json, load_plan_yaml
from trade_plan_monitor.domain.plan_validation import DraftReviewIssue
from trade_plan_monitor.web import plan_service as plan_service_module
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.plans import (
    PlanActivationCommand,
    PlanDeactivationCommand,
    PlanDocumentFormat,
    PlanDraftCommand,
    PlanImportCommand,
)
from trade_plan_monitor.web.schemas import ApiErrorCode, MutationContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FIXED_NOW = datetime(2026, 9, 3, 10, 30, tzinfo=_SHANGHAI)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_SAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
)


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
        database_path=database_path,
        ai_service=_AIService(),
        backtest_lifecycle_factory=_BacktestLifecycle,
    ) as app:
        assert not database_path.exists()
        assert not hasattr(app.state, "plan_operation_service")
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            response = client.get("/api/v1/plan-versions")
            assert response.status_code == 200
            assert response.json() == {"items": [], "limit": 20, "offset": 0, "total": 0}
            assert database_path.is_file()
            assert hasattr(app.state, "plan_operation_service")
            imported = client.post(
                "/api/v1/plan-imports",
                headers={"Idempotency-Key": "production-import-v1"},
                json={
                    "document": _SAMPLE_PLAN_PATH.read_text(encoding="utf-8"),
                    "expectedRevision": 0,
                    "format": "YAML",
                    "symbol": "003043.SZ",
                },
            )
            assert imported.status_code == 200
            imported_id = imported.json()["id"]
        assert not hasattr(app.state, "plan_operation_service")

    with create_production_app(
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
    source_v1 = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    plan_v1 = load_plan_yaml(source_v1)
    resolved_review = DraftReviewIssue(
        kind="WARNING",
        path="levels.pressure",
        material=True,
        resolved=True,
    )
    save_command = PlanDraftCommand(
        plan_json=dump_plan_json(plan_v1),
        source_text=source_v1,
        review_issues=(resolved_review,),
        expected_revision=0,
    )

    async def scenario() -> None:
        first = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        assert not database_path.exists()
        await first.start()
        saved = await first.save_plan_draft(
            command=save_command,
            context=_context("save-v1"),
        )
        assert saved.review_issues == (resolved_review,)
        assert saved.source_text == source_v1
        assert saved.status.value == "DRAFT"
        await first.stop()

        second = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await second.start()
        replayed = await second.save_plan_draft(
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

        activated_v1 = await second.activate_plan(
            command=PlanActivationCommand(
                plan_version_id=saved.id,
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
        activated_v2 = await third.activate_plan(
            command=PlanActivationCommand(
                plan_version_id=imported_v2.id,
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
        assert restored_page.total == 2
        assert {item.status.value for item in restored_page.items} == {"SUPERSEDED"}

        with pytest.raises(ApiError) as reused:
            await fifth.save_plan_draft(
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
    source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    plan_v1 = load_plan_yaml(source)

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        base = await service.save_plan_draft(
            command=PlanDraftCommand(
                plan_json=dump_plan_json(plan_v1),
                source_text=source,
                expected_revision=0,
            ),
            context=_context("save-base-v1"),
        )

        submitted = plan_v1.model_copy(update={"version": 999})
        derived_command = PlanDraftCommand(
            base_plan_version_id=base.id,
            plan_json=dump_plan_json(submitted),
            source_text="server-versioned draft",
            expected_revision=0,
        )
        derived = await service.save_plan_draft(
            command=derived_command,
            context=_context("save-derived-v2"),
        )
        replayed = await service.save_plan_draft(
            command=derived_command,
            context=_context("save-derived-v2"),
        )

        assert derived.version == 2
        assert load_plan_json(derived.plan_json).version == 2
        assert replayed == derived

        for field, value in (("plan_id", "other-plan"), ("symbol", "000001.SZ")):
            mismatched = submitted.model_copy(update={field: value})
            with pytest.raises(ApiError) as rejected:
                await service.save_plan_draft(
                    command=PlanDraftCommand(
                        base_plan_version_id=base.id,
                        plan_json=dump_plan_json(mismatched),
                        source_text=f"mismatched {field}",
                        expected_revision=0,
                    ),
                    context=_context(f"reject-mismatched-{field}"),
                )
            assert rejected.value.code is ApiErrorCode.VALIDATION_ERROR

        with pytest.raises(ApiError) as missing:
            await service.save_plan_draft(
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
    source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    plan = load_plan_yaml(source)
    last_safe_plan = plan.model_copy(update={"version": _MAX_SAFE_INTEGER})

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        base = await service.save_plan_draft(
            command=PlanDraftCommand(
                plan_json=dump_plan_json(last_safe_plan),
                source_text=source,
                expected_revision=0,
            ),
            context=_context("save-last-safe-version"),
        )

        with pytest.raises(ApiError) as rejected:
            await service.save_plan_draft(
                command=PlanDraftCommand(
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
    source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    plan_v1 = load_plan_yaml(source)

    async def scenario() -> None:
        seed = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await seed.start()
        base = await seed.save_plan_draft(
            command=PlanDraftCommand(
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
        first_command = PlanDraftCommand(
            base_plan_version_id=base.id,
            plan_json=dump_plan_json(submitted),
            source_text="concurrent first",
            expected_revision=0,
        )
        second_command = first_command.model_copy(update={"source_text": "concurrent second"})

        first_result, second_result = await asyncio.gather(
            first.save_plan_draft(
                command=first_command,
                context=_context("concurrent-derived-first"),
            ),
            second.save_plan_draft(
                command=second_command,
                context=_context("concurrent-derived-second"),
            ),
        )
        replayed = await second.save_plan_draft(
            command=first_command,
            context=_context("concurrent-derived-first"),
        )
        shared_command = first_command.model_copy(
            update={"source_text": "concurrent shared intent"}
        )
        shared_first, shared_second = await asyncio.gather(
            first.save_plan_draft(
                command=shared_command,
                context=_context("concurrent-shared-intent"),
            ),
            second.save_plan_draft(
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
    document = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")

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
    plan = load_plan_yaml(_SAMPLE_PLAN_PATH.read_text(encoding="utf-8")).model_copy(
        update={"version": _MAX_SAFE_INTEGER + 1}
    )
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
            await service.save_plan_draft(
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
    plan = load_plan_yaml(_SAMPLE_PLAN_PATH.read_text(encoding="utf-8"))
    source_text = "large provenance:" + "x" * 200_000

    async def scenario() -> None:
        service = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await service.start()
        saved = await service.save_plan_draft(
            command=PlanDraftCommand(
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
    source = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
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
            await service.save_plan_draft(
                command=PlanDraftCommand(
                    plan_json=dump_plan_json(plan),
                    source_text=f"source version {version}",
                    expected_revision=0,
                ),
                context=_context(f"save-window-{version}"),
            )

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


def test_unresolved_review_remains_an_activation_blocker_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.sqlite3"
    source_text = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    plan = load_plan_yaml(source_text)
    unresolved = DraftReviewIssue(
        kind="WARNING",
        path="entry.condition",
        material=True,
        resolved=False,
    )

    async def scenario() -> None:
        first = PersistentPlanWebLifecycle(database_path=database_path, clock=lambda: _FIXED_NOW)
        await first.start()
        saved = await first.save_plan_draft(
            command=PlanDraftCommand(
                plan_json=dump_plan_json(plan),
                source_text=source_text,
                review_issues=(unresolved,),
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
        assert restored.review_issues == (unresolved,)
        assert restored.can_activate is False
        assert any(
            issue.code == "UNRESOLVED_MATERIAL_AI_ISSUE" and issue.activation_blocking
            for issue in restored.validation_issues
        )
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
