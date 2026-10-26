"""Compare-and-swap books and append-only receipts share the caller's transaction."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from trade_plan_monitor.state.p3_models import (
    CapitalBook,
    CapitalBookEvent,
    CapitalBookRow,
    CapitalEventRow,
)
from trade_plan_monitor.state.repositories import RevisionConflictError


class CapitalCommandConflict(ValueError):
    pass


class CapitalRepository:
    def __init__(self, session):
        self.session = session

    def get(self, symbol):
        row = self.session.execute(
            select(
                CapitalBookRow.symbol,
                CapitalBookRow.revision,
                CapitalBookRow.inventory_revision,
                CapitalBookRow.payload_json,
                CapitalBookRow.updated_at,
            ).where(CapitalBookRow.symbol == symbol)
        ).one_or_none()
        if row is None:
            return None
        value = CapitalBook.model_validate_json(row.payload_json)
        if (
            value.symbol,
            value.revision,
            value.inventory_revision,
            value.updated_at.isoformat(),
        ) != (row.symbol, row.revision, row.inventory_revision, row.updated_at):
            raise ValueError("capital book columns differ from immutable payload")
        return value

    def event(self, command_id):
        row = self.session.execute(
            select(
                CapitalEventRow.command_id,
                CapitalEventRow.symbol,
                CapitalEventRow.revision,
                CapitalEventRow.request_hash,
                CapitalEventRow.payload_json,
                CapitalEventRow.created_at,
            ).where(CapitalEventRow.command_id == command_id)
        ).one_or_none()
        if row is None:
            return None
        value = CapitalBookEvent.model_validate_json(row.payload_json)
        if (
            value.command_id,
            value.book.symbol,
            value.book.revision,
            value.request_hash,
            value.received_at.isoformat(),
        ) != (row.command_id, row.symbol, row.revision, row.request_hash, row.created_at):
            raise ValueError("capital event columns differ from immutable payload")
        return value

    def write(self, book, *, expected_revision, command_id, request_hash, kind, now, details):
        prior = self.event(command_id)
        if prior is not None:
            if (
                prior.request_hash != request_hash
                or prior.book.symbol != book.symbol
                or prior.kind != kind
            ):
                raise CapitalCommandConflict("CAPITAL_IDEMPOTENCY_CONFLICT")
            return prior
        current = self.get(book.symbol)
        actual = 0 if current is None else current.revision
        if actual != expected_revision:
            raise RevisionConflictError(actual)
        event = CapitalBookEvent.build(
            command_id=command_id,
            request_hash=request_hash,
            kind=kind,
            before_revision=actual,
            before_hash=None if current is None else current.evidence_hash,
            book=book,
            received_at=now,
            details=details,
        )
        data = dict(
            revision=book.revision,
            inventory_revision=book.inventory_revision,
            payload_json=book.model_dump_json(),
            updated_at=now.isoformat(),
        )
        if current is None:
            self.session.add(CapitalBookRow(symbol=book.symbol, **data))
        else:
            changed = self.session.execute(
                update(CapitalBookRow)
                .where(
                    CapitalBookRow.symbol == book.symbol,
                    CapitalBookRow.revision == expected_revision,
                )
                .values(**data)
            )
            if changed.rowcount != 1:
                raise RevisionConflictError(actual)
        self.session.add(
            CapitalEventRow(
                command_id=command_id,
                symbol=book.symbol,
                revision=book.revision,
                request_hash=request_hash,
                payload_json=event.model_dump_json(),
                created_at=now.isoformat(),
            )
        )
        try:
            self.session.flush()
        except IntegrityError as error:
            raise CapitalCommandConflict("CAPITAL_CONCURRENT_COMMAND") from error
        return event
