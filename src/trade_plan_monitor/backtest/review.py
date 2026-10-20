"""Bounded causal reads over published, hash-verified loop records."""

from hashlib import sha256

from trade_plan_monitor.backtest.pagination import InvalidCursorError, validate_page_limit
from trade_plan_monitor.backtest.result_service import BacktestResultNotFoundError
from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    _availability_by_run,
    _load_detail_row,
    _load_fill_row,
)
from trade_plan_monitor.backtest.review_index import index_review_event

_COLUMNS = (
    "d.detail_id, d.run_id, d.kind, d.event_at, d.content_domain, d.content_hash, d.payload_json"
)
_ROUTE = "review-context"


def read_review_context(store, signer, *, run_id, selector, relation, limit, cursor):
    """One snapshot, at most limit related rows; never index or replay on GET."""
    validate_page_limit(limit)
    filters = {"runId": run_id, "selector": selector, "relation": relation, "limit": limit}
    decoded = None if cursor is None else signer.decode(
        cursor, route=_ROUTE, filters=filters, order="causal-sequence-v1",
    )
    with store._connect() as connection:
        connection.execute("BEGIN")
        if connection.execute(
            "SELECT 1 FROM backtest_run WHERE run_id = ? AND materialized = 1", (run_id,),
        ).fetchone() is None:
            raise BacktestResultNotFoundError
        state = next(s for s in _availability_by_run(connection, (run_id,))[run_id]
                     if s.kind is BacktestDetailKind.DECISION)
        availability = state.availability.value
        indexed_end = connection.execute(
            "SELECT sequence FROM backtest_review_event WHERE run_id = ? "
            "ORDER BY sequence DESC LIMIT 1", (run_id,),
        ).fetchone()
        index_ready = indexed_end is not None and indexed_end[0] == state.original_count

        def load_event(*, event_id=None, sequence=None):
            if availability != "AVAILABLE":
                return None
            if sequence is not None:
                rows = connection.execute(
                    f"SELECT {_COLUMNS} FROM backtest_detail d "
                    "WHERE d.run_id = ? AND d.detail_id = ? AND d.kind = 'DECISION'",
                    (run_id, f"loop-{sequence:06d}-{run_id[:16]}"),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {_COLUMNS}, i.event_id, i.sequence, i.cause_event_id, "
                    "i.content_hash FROM backtest_review_event i "
                    "JOIN backtest_detail d ON d.detail_id = i.detail_id "
                    "AND d.run_id = i.run_id "
                    "WHERE i.run_id = ? AND i.event_id = ? LIMIT 2", (run_id, event_id),
                ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise RuntimeError("ambiguous review identity")
            row = rows[0]
            record = _load_detail_row(tuple(row[:7]), expected_run_id=run_id)
            import json

            from trade_plan_monitor.backtest.loop_report import decode_loop_event

            event = decode_loop_event(json.dumps(record.payload))
            if sequence is None and tuple(row[7:]) != (
                event.event_id, event.sequence, event.cause_event_id, row[5],
            ):
                raise RuntimeError("review metadata/hash mismatch")
            if ((event_id is not None and event.event_id != event_id)
                    or (sequence is not None and event.sequence != sequence)):
                raise RuntimeError("review index identity mismatch")
            return record

        fill = None
        event_id = selector.get("eventId")
        if selector.get("fillId") is not None:
            stored_id = sha256(("monitor-loop-stored-fill-v1\0" + run_id + "\0"
                                + selector["fillId"]).encode()).hexdigest()
            row = connection.execute(
                "SELECT fill_id, run_id, filled_at, content_domain, content_hash, payload_json "
                "FROM backtest_fill WHERE run_id = ? AND fill_id = ?", (run_id, stored_id),
            ).fetchone()
            if row is None:
                raise BacktestResultNotFoundError
            fill = _load_fill_row(tuple(row), expected_run_id=run_id)
            event_id = fill.payload["event_id"]
        selected = load_event(event_id=event_id, sequence=selector.get("sequence"))
        result = dict(
            runId=run_id, selector=selector, relation=relation, selected=selected, fill=fill,
            items=[], availability=availability,
            projectionStatus="READY" if index_ready or availability != "AVAILABLE" else "NOT_READY",
            completeness="COMPLETE", missingEventId=None, limit=limit,
            hasMore=False, nextCursor=None,
        )
        if selected is None:
            if decoded is not None and availability == "AVAILABLE":
                raise InvalidCursorError
            if fill is None and availability == "AVAILABLE" and (
                index_ready or selector.get("sequence") is not None
            ):
                raise BacktestResultNotFoundError
            result.update(projectionStatus="NOT_READY" if availability == "AVAILABLE" else "READY",
                          completeness="PARTIAL", missingEventId=event_id)
            return result
        selected_hash = connection.execute(
            "SELECT content_hash FROM backtest_detail WHERE detail_id = ?", (selected.detail_id,),
        ).fetchone()[0]
        boundary = (selected.payload["event_id"], selected_hash)
        if decoded is not None and decoded.high_water != boundary:
            raise InvalidCursorError
        position = None if decoded is None else decoded.last_seen
        if decoded is not None and (position is None or len(position) != 1):
            raise InvalidCursorError
        items = []
        next_position = None
        if relation == "CAUSES":
            target = selected.payload["cause_event_id"] if position is None else position[0]
            for _ in range(limit):
                if target is None:
                    break
                record = load_event(event_id=target)
                if record is None:
                    result.update(completeness="PARTIAL", missingEventId=target)
                    break
                if record.payload["sequence"] >= (
                    items[-1].payload["sequence"] if items else selected.payload["sequence"]
                ):
                    raise RuntimeError("invalid review causal order")
                items.append(record)
                target = record.payload["cause_event_id"]
            else:
                next_position = None if target is None else (target,)
        else:
            try:
                after = 0 if position is None else int(position[0])
            except ValueError:
                raise InvalidCursorError from None
            rows = connection.execute(
                "SELECT sequence, event_id FROM backtest_review_event "
                "WHERE run_id = ? AND cause_event_id = ? AND sequence > ? "
                "ORDER BY sequence LIMIT ?", (run_id, boundary[0], after, limit + 1),
            ).fetchall()
            for sequence, identity in rows[:limit]:
                record = load_event(event_id=identity)
                if (record is None or record.payload["cause_event_id"] != boundary[0]
                        or record.payload["sequence"] != sequence):
                    raise RuntimeError("review child index mismatch")
                items.append(record)
            if len(rows) > limit:
                next_position = (str(rows[limit - 1][0]),)
            if not index_ready:
                result["completeness"] = "PARTIAL"
        result["items"] = items
        if next_position is not None:
            result.update(hasMore=True, nextCursor=signer.encode(
                route=_ROUTE, filters=filters, order="causal-sequence-v1",
                high_water=boundary, last_seen=next_position,
            ))
        connection.commit()
        return result


def rebuild_review_batch(store, run_id, *, after=None, limit=100):
    """Explicit maintenance only, over a bounded retained canonical batch."""
    validate_page_limit(limit)
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM backtest_run WHERE run_id = ? AND materialized = 1", (run_id,),
        ).fetchone() is None:
            raise BacktestResultNotFoundError
        if after is not None and connection.execute(
            "SELECT 1 FROM backtest_review_event WHERE run_id = ? AND detail_id = ?",
            (run_id, after),
        ).fetchone() is None:
            raise ValueError("maintenance continuation must follow an indexed record")
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM backtest_detail d WHERE d.run_id = ? "
            "AND d.kind = 'DECISION' AND d.detail_id > ? ORDER BY d.detail_id LIMIT ?",
            (run_id, after or "", limit + 1),
        ).fetchall()
        for row in rows[:limit]:
            record = _load_detail_row(tuple(row), expected_run_id=run_id)
            index_review_event(connection, record, row[5])
        connection.commit()
        return rows[limit - 1][0] if len(rows) > limit else None


def project_review_evidence(records):
    """Reuse deterministic diagnostics wording; never re-evaluate recorded predicates."""
    import json

    from trade_plan_monitor.backtest.loop_diagnostics import _explain, _leaves
    from trade_plan_monitor.backtest.loop_report import decode_loop_event
    from trade_plan_monitor.backtest.time import format_shanghai_datetime

    rows = []
    for record in records:
        event = decode_loop_event(json.dumps(record.payload))
        if event.payload.kind != "EVALUATED":
            continue
        for condition in event.payload.conditions:
            for leaf in _leaves(condition.evidence):
                requirement, actual = _explain(leaf, None)
                rows.append(dict(
                    sequence=event.sequence, ruleId=condition.rule_id,
                    at=format_shanghai_datetime(event.at),
                    rootOutcome=condition.evidence.outcome,
                    requirement=requirement[:400], actual=actual[:400],
                    reason=(leaf.reason or "")[:200],
                ))
                if len(rows) == 100:
                    return rows
    return rows
