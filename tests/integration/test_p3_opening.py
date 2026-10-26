"""Explicit budget reconciliation cannot become inventory, cash or approval."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.integration.test_p3_storage import NOW, database

from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_capital_service import (
    CapitalOpeningCommand,
    CapitalOpeningContext,
    CapitalOpeningError,
    confirm_capital_opening,
)

__all__ = ["database"]


def context(**changes):
    return CapitalOpeningContext.model_validate(
        dict(
            plan_version_id=str(uuid4()),
            symbol="601021.SH",
            content_hash="b" * 64,
            review_binding_hash="c" * 64,
            reviewed=True,
            inventory_known=True,
            inventory_revision=1,
            lots=[{"lot_id": "initial-TACTICAL", "bucket": "TACTICAL", "quantity": 400}],
            blockers=[],
        )
        | changes
    )


def opening(ctx, **changes):
    return CapitalOpeningCommand.model_validate(
        dict(
            plan_version_id=str(ctx.plan_version_id),
            expected_inventory_revision=1,
            expected_book_revision=0,
            observed_at=NOW,
            source="explicit local fixture",
            excerpt="400 shares retain450001fen budget cost",
            reason="Confirm this simulated budget only",
            confirmed=True,
            lots=[
                {
                    "lot_id": "initial-TACTICAL",
                    "bucket": "TACTICAL",
                    "quantity": 400,
                    "retained_basis_fen": 450001,
                }
            ],
        )
        | changes
    )


def test_explicit_opening_is_hashed_replayable_and_never_creates_inventory(database):
    engine, _ = database
    ctx = context()
    with Session(engine) as session, session.begin():
        cmd = opening(ctx)
        event = confirm_capital_opening(
            session, cmd, command_id="opening", now=NOW, current=lambda _: ctx
        )
        assert event.book.retained_basis_fen == 450001
        again = confirm_capital_opening(
            session,
            cmd,
            command_id="opening",
            now=NOW + timedelta(seconds=1),
            current=lambda _: None,
        )
        assert again == event
        assert session.execute(text("SELECT COUNT(*) FROM daily_plan_record")).scalar_one() == 0


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"reviewed": False}, "CAPITAL_REVIEW_REQUIRED"),
        ({"inventory_known": False}, "CAPITAL_POSITION_UNKNOWN"),
        ({"inventory_revision": 2}, "CONFLICT"),
        (
            {"lots": [{"lot_id": "other", "bucket": "TACTICAL", "quantity": 400}]},
            "CAPITAL_LOTS_CHANGED",
        ),
    ],
)
def test_current_review_inventory_and_lots_are_mandatory(database, change, reason):
    from trade_plan_monitor.state.repositories import RevisionConflictError

    engine, _ = database
    ctx = context()
    with Session(engine) as session, session.begin():
        with pytest.raises((CapitalOpeningError, RevisionConflictError)) as error:
            confirm_capital_opening(
                session,
                opening(ctx),
                command_id="invalid",
                now=NOW,
                current=lambda _: ctx.model_copy(update=change),
            )
        assert getattr(error.value, "reason", getattr(error.value, "code", None)) == reason
        assert CapitalRepository(session).get(ctx.symbol) is None


def test_future_observation_unknown_basis_and_ai_actor_are_not_accepted(database):
    engine, _ = database
    ctx = context()
    with (
        Session(engine) as session,
        session.begin(),
        pytest.raises(CapitalOpeningError, match="CAPITAL_OBSERVATION_FUTURE"),
    ):
        confirm_capital_opening(
            session,
            opening(ctx, observed_at=NOW + timedelta(days=1)),
            command_id="future",
            now=NOW,
            current=lambda _: ctx,
        )
    for changes in (
        {"confirmed": False},
        {"confirmed": 1},
        {"actor": "AI"},
        {
            "lots": [
                {
                    "lot_id": "initial-TACTICAL",
                    "bucket": "TACTICAL",
                    "quantity": 400,
                    "retained_basis_fen": None,
                }
            ]
        },
    ):
        with pytest.raises(ValueError):
            opening(ctx, **changes)


def test_reconciliation_keeps_old_evidence_and_uses_exact_current_revisions(database):
    engine, _ = database
    ctx = context()
    with Session(engine) as session, session.begin():
        first = confirm_capital_opening(
            session, opening(ctx), command_id="one", now=NOW, current=lambda _: ctx
        )
        lots = [
            dict(
                lot_id="initial-TACTICAL",
                bucket="TACTICAL",
                quantity=400,
                retained_basis_fen=450002,
            )
        ]
        second = confirm_capital_opening(
            session,
            opening(ctx, expected_book_revision=1, lots=lots),
            command_id="two",
            now=NOW,
            current=lambda _: ctx,
        )
        assert second.kind == "RECONCILIATION" and second.book.revision == 2
        assert first.book.retained_basis_fen == 450001
        assert CapitalRepository(session).event("one") == first
