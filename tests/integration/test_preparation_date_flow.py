"""Text-only preparation retains provenance while resolving the simulated schedule."""

from datetime import date, datetime, time

import pytest
from tests.integration.test_plan_preparation_review import (
    collection_review_command,
    ready_collection,
    ready_preparation,
    review_command,
)

from trade_plan_monitor.backtest.preparation_models import (
    PlanCollectionPreparationInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.time import SHANGHAI


@pytest.mark.parametrize("count", [1, 5, 17])
def test_text_only_batch_resolves_each_date_without_fabricating_source_times(tmp_path, count):
    store = PreparationStore(tmp_path / "dates.sqlite")
    command = PlanCollectionPreparationInput(
        preparation_id="dates", sources=tuple(
            PreparationSource(source_id=f"day-{day}", text=f"生效交易日：2026-09-{day:02d}")
            for day in range(1, count + 1)
        ),
    )
    record = store.create(command, idempotency_key="create")
    assert len(record.items) == count
    for day, item in enumerate(record.items, 1):
        assert item.source.effective_trade_date == date(2026, 9, day)
        assert item.source.authored_at is item.source.available_at is None
        assert item.source.execution_available_at == datetime(2026, 9, day, 9, 30, tzinfo=SHANGHAI)
    assert store.replay_create(command, idempotency_key="create") == record
    assert PreparationStore(store.database_path).get("dates") == record


def test_uncertain_date_remains_empty_until_explicit_confirmation(tmp_path):
    store = PreparationStore(tmp_path / "dates.sqlite")
    source = PreparationSource(source_id="source", text="9月24日若企稳，继续等待。")
    record = store.create(
        PlanCollectionPreparationInput(preparation_id="dates", sources=(source,)),
        idempotency_key="create",
    )
    assert record.items[0].source.effective_trade_date is None
    confirmed = source.model_copy(update={"effective_trade_date": date(2026, 9, 24)})
    edited = store.edit_collection("dates", source=confirmed, expected_revision=record.revision,
                                   idempotency_key="confirm")
    assert edited.items[0].source.effective_trade_date == date(2026, 9, 24)
    assert edited.items[0].source.authored_at is edited.items[0].source.available_at is None


def test_resolved_batch_is_ordered_by_effective_date_not_file_selection_order(tmp_path):
    store = PreparationStore(tmp_path / "ordered.sqlite")
    record = store.create(PlanCollectionPreparationInput(preparation_id="ordered", sources=(
        PreparationSource(source_id="later", text="生效日期：2026-09-25"),
        PreparationSource(source_id="first", text="生效日期：2026-09-24"),
    )), idempotency_key="create")
    assert [item.source.source_id for item in record.items] == ["first", "later"]
    assert [item.status for item in record.items] == ["DRAFT", "WAITING"]


def test_freeze_and_schedule_work_without_authoring_or_availability(tmp_path):
    store, ready = ready_preparation(tmp_path, metadata={"authored_at": None, "available_at": None})
    reviewed = store.review_and_freeze(
        "one", command=review_command(ready), idempotency_key="review",
    )
    frozen = frozen_preparation(reviewed)
    assert frozen.source.authored_at is frozen.source.available_at is None
    assert frozen.version.authored_at is None
    opening = datetime.combine(ready.source.effective_trade_date, time(9, 30), SHANGHAI)
    assert frozen.version.available_at == opening
    assert frozen.schedule.select(opening).activated_at == opening
    assert frozen.schedule.select(opening.replace(hour=9, minute=29)) is None
    assert type(frozen).model_validate_json(frozen.model_dump_json()) == frozen


def test_successor_materialization_and_frozen_chain_accept_optional_source_times(tmp_path):
    store, ready = ready_collection(tmp_path, without_source_times=True)
    reviewed = store.review_and_freeze(ready.preparation_id,
        command=collection_review_command(ready), idempotency_key="review")
    frozen = frozen_preparation(reviewed)
    for item in frozen.items:
        assert item.source.authored_at is item.source.available_at is None
        assert item.mapping.available_at == item.source.execution_available_at
        assert item.version.available_at == item.source.execution_available_at
        assert frozen.schedule.select(item.version.available_at).version == item.version
    assert type(frozen).model_validate_json(frozen.model_dump_json()) == frozen
