"""Apply available frozen budget declarations through the ordinary private service."""

from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.p3_replay_input import FrozenCapitalOpening
from trade_plan_monitor.backtest.research_input import ResearchTimestamp, ResearchValue
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_capital_service import (
    CapitalInventoryLot,
    CapitalOpeningCommand,
    CapitalOpeningContext,
    CapitalOpeningError,
    CapitalOpeningLot,
    confirm_capital_opening,
)


class CapitalReplayOutcome(ResearchValue):
    schema_version: Literal["capital-replay-outcome-v1"] = "capital-replay-outcome-v1"
    envelope_hash: Sha256Hex
    source_event_id: str = Field(min_length=1, max_length=128)
    provenance: Literal["RECORDED_LOCAL", "RESEARCH_SCENARIO"]
    at: ResearchTimestamp
    status: Literal["APPLIED", "BLOCKED"]
    blockers: tuple[str, ...] = Field(max_length=10)
    private_event_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def consistent(self):
        if ((self.status == "BLOCKED") != bool(self.blockers)
                or (self.status == "BLOCKED") != (self.private_event_hash is None)):
            raise ValueError("capital outcome status and private receipt disagree")
        return self


def validate_capital_outcomes(events, outcomes, *, started_at, cutoff):
    expected = tuple((e.envelope_hash, e.source_event_id, e.provenance,
                      max(e.available_at, started_at))
                     for e in events if e.available_at <= cutoff)
    actual = tuple((o.envelope_hash, o.source_event_id, o.provenance, o.at)
                   for o in outcomes or ())
    if expected != actual:
        raise ValueError("capital outcomes do not match available frozen source events")


def apply_frozen_capital(session, frozen):
    """No current user database, cash balance or inferred research costs are read."""
    frozen = FrozenCapitalOpening.model_validate_json(frozen.model_dump_json())
    event, blockers = None, ()
    try:
        if frozen.available_at > session.now:
            raise CapitalOpeningError("CAPITAL_REPLAY_NOT_AVAILABLE")
        if frozen.plan_hash != plan_sha256(session.plan):
            raise CapitalOpeningError("CAPITAL_REPLAY_PLAN_MISMATCH")
        opening = (session.run_input.initial_account.lots
                   if hasattr(session.run_input, "initial_account")
                   else session.run_input.initial_lots)
        initial_keys = {lot.lot_key for lot in opening}
        with session.work() as work:
            work.daily.lock_symbol(session.plan.symbol)
            accounting = DailyAccounting(work.daily)
            inventory = accounting.snapshot(session.plan.symbol, session.now.date())
            position = accounting._position(session.plan.symbol)
            if not inventory["known"]:
                raise CapitalOpeningError("CAPITAL_POSITION_UNKNOWN")
            resolved = []
            for lot in frozen.lots:
                if lot.reference.kind == "OPENING":
                    if lot.reference.lot_key not in initial_keys:
                        raise CapitalOpeningError("CAPITAL_REPLAY_OPENING_LOT_MISSING")
                    lot_id = lot.reference.lot_key
                else:
                    receipts = work.daily.list(symbol=session.plan.symbol, kind="SIMULATION")
                    matches = [r["payload"] for r in receipts
                               if r["payload"]["cause_id"] == lot.reference.signal_id
                               and r["payload"]["side"] == "BUY"]
                    if len(matches) != 1:
                        raise CapitalOpeningError("CAPITAL_REPLAY_BUY_LOT_MISSING")
                    lot_id = matches[0]["simulation_id"]
                resolved.append(CapitalOpeningLot(lot_id=lot_id, bucket=lot.bucket,
                    quantity=lot.quantity, retained_basis_fen=lot.retained_basis_fen))
            current_lots = tuple(CapitalInventoryLot(lot_id=b["id"], bucket=b["bucket"],
                quantity=b["quantity"]) for b in position["payload"]["batches"])
            review = work.daily.get("review-"+session.details.id)["payload"]
            context = CapitalOpeningContext(plan_version_id=session.details.id,
                symbol=session.plan.symbol, content_hash=session.details.content_hash,
                review_binding_hash=daily_hash("capital-opening-review-v1", review),
                reviewed=review["confirmed"], inventory_known=True,
                inventory_revision=inventory["revision"], lots=current_lots, blockers=())
            prior = CapitalRepository(work.daily.session).get(session.plan.symbol)
            command = CapitalOpeningCommand(plan_version_id=session.details.id,
                expected_inventory_revision=inventory["revision"],
                expected_book_revision=0 if prior is None else prior.revision,
                observed_at=frozen.observed_at, source=frozen.source, excerpt=frozen.excerpt,
                reason=frozen.reason, confirmed=True, lots=tuple(resolved))
            event = confirm_capital_opening(work.daily.session, command,
                command_id="frozen-"+frozen.envelope_hash, now=session.now,
                current=lambda _: context)
            work.commit()
    except CapitalOpeningError as error:
        blockers = (error.reason,)
    return CapitalReplayOutcome(envelope_hash=frozen.envelope_hash,
        source_event_id=frozen.source_event_id, provenance=frozen.provenance, at=session.now,
        status="BLOCKED" if blockers else "APPLIED", blockers=blockers,
        private_event_hash=None if event is None else event.event_hash)


class CapitalReplayState:
    def __init__(self, session, program):
        self.session, self.program = session, program
        self.processed, self.outcomes = set(), []

    def apply(self, now, *, before_order=None):
        if self.program is None:
            return
        for event in self.program.opening_events:
            if event.available_at > now or event.envelope_hash in self.processed:
                continue
            if (before_order is not None and event.available_at == now
                    and event.order >= before_order):
                continue
            self.outcomes.append(apply_frozen_capital(self.session, event))
            self.processed.add(event.envelope_hash)

    def finish(self, *, started_at, cutoff):
        if self.program is not None:
            validate_capital_outcomes(self.program.opening_events, self.outcomes,
                                      started_at=started_at, cutoff=cutoff)
