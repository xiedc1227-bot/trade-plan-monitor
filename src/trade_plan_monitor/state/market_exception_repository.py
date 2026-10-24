"""Transactional occurrence projections; event identity prevents repeated grants."""

from trade_plan_monitor.state.market_exception_models import ExceptionCandidate, ExceptionEvent
from trade_plan_monitor.state.repositories import RevisionConflictError


class ExceptionRepository:
    def __init__(self, daily):
        self.daily = daily

    def get(self, candidate_id):
        row = self.daily.get(candidate_id)
        if row is not None and row["kind"] != "EXCEPTION_CANDIDATE":
            raise ValueError("not an exception candidate")
        if row is not None:
            candidate = ExceptionCandidate.model_validate(row["payload"])
            if (row["id"] != candidate.candidate_id
                    or row["symbol"] != candidate.binding.symbol
                    or row["lineage"] != candidate.binding.lineage):
                raise ValueError("candidate storage owner mismatch")
            if candidate.last_event_id is not None:
                event_row = self.daily.get(candidate.last_event_id)
                if event_row is None or event_row["kind"] != "EXCEPTION_EVENT":
                    raise ValueError("candidate transition evidence missing")
                event = ExceptionEvent.model_validate(event_row["payload"])
                if (event.event_id != candidate.last_event_id
                        or event.candidate_id != candidate.candidate_id
                        or event.binding_hash != candidate.binding_hash
                        or event.to_state != candidate.state
                        or event.approval_id != candidate.approval_id
                        or event.quantity != candidate.frozen_quantity
                        or event.expected_revision + 1 != row["revision"]):
                    raise ValueError("candidate transition evidence mismatch")
        return row

    def list(self, symbol):
        return tuple(self.get(row["id"]) for row in self.daily.list(
            symbol=symbol, kind="EXCEPTION_CANDIDATE"))

    def create(self, candidate):
        candidate = ExceptionCandidate.model_validate_json(candidate.model_dump_json())
        if candidate.state != "PENDING":
            raise ValueError("new candidates cannot contain approval")
        b = candidate.binding
        self.daily.lock_symbol(b.symbol)
        old = self.get(candidate.candidate_id)
        if old is not None:
            if old["payload"]["binding_hash"] != candidate.binding_hash:
                raise ValueError("existing occurrence binding cannot be replaced")
            return old
        return self.daily.save(
            candidate.candidate_id, kind="EXCEPTION_CANDIDATE", symbol=b.symbol,
            lineage=b.lineage, payload=candidate.model_dump(mode="json"), expected_revision=0)

    def transition(self, candidate, event, *, expected_revision):
        candidate = ExceptionCandidate.model_validate_json(candidate.model_dump_json())
        event = ExceptionEvent.model_validate_json(event.model_dump_json())
        self.daily.lock_symbol(candidate.binding.symbol)
        row = self.get(candidate.candidate_id)
        if row is None or row["revision"] != expected_revision:
            raise RevisionConflictError(0 if row is None else row["revision"])
        prior = ExceptionCandidate.model_validate(row["payload"])
        if (event.candidate_id != candidate.candidate_id
                or event.binding_hash != prior.binding_hash
                or candidate.binding != prior.binding
                or candidate.created_at != prior.created_at
                or event.expected_revision != expected_revision
                or event.from_state != prior.state or event.to_state != candidate.state
                or candidate.last_event_id != event.event_id
                or event.quantity != candidate.frozen_quantity
                or event.approval_id != candidate.approval_id
                or event.received_at < prior.created_at
                or event.received_at > self.daily.clock()):
            raise ValueError("exception transition does not match stored authority")
        if prior.approval_id is not None and (
                candidate.approval_id != prior.approval_id
                or candidate.frozen_quantity != prior.frozen_quantity):
            raise ValueError("frozen authority cannot change")
        if event.to_state == "APPROVED" and event.received_at >= prior.binding.expires_at:
            raise ValueError("approval window expired")
        if prior.last_event_id is not None:
            previous = self.daily.get(prior.last_event_id)
            if (previous is None
                    or event.received_at.isoformat() < previous["payload"]["received_at"]):
                raise ValueError("event history is missing or backdated")
        self.daily.save(
            event.event_id, kind="EXCEPTION_EVENT", symbol=candidate.binding.symbol,
            lineage=candidate.binding.lineage, payload=event.model_dump(mode="json"),
            expected_revision=0)
        return self.daily.save(
            candidate.candidate_id, kind="EXCEPTION_CANDIDATE", symbol=candidate.binding.symbol,
            lineage=candidate.binding.lineage, payload=candidate.model_dump(mode="json"),
            expected_revision=expected_revision)
