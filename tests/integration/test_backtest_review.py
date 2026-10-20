"""Review follows verified recorded edges rather than traversing result pages."""

import sqlite3

import pytest

pytest_plugins = ["tests.integration.test_monitor_loop_result_api"]


def test_fill_context_and_signed_cross_page_causes(scheduled_published):
    client, _, _, reference, _ = scheduled_published
    base = f"/api/v1/backtest-runs/{reference.run_id}"
    fill = client.get(base + "/fills").json()["items"][0]
    query = {"fillId": fill["fillId"], "limit": 1}
    response = client.get(base + "/review-context", params=query)
    assert response.status_code == 200
    body = response.json()
    assert body["fill"] == fill
    assert body["selected"]["event"]["event_id"] == fill["eventId"]
    assert body["items"][0]["event"]["event_id"] == body["selected"]["event"]["cause_event_id"]
    seen = set()
    while True:
        assert len(body["items"]) <= 1
        for row in body["items"]:
            assert row["event"]["event_id"] not in seen
            seen.add(row["event"]["event_id"])
        assert len(response.content) < 4 * 1024 * 1024
        if not body["hasMore"]:
            break
        token = body["nextCursor"]
        response = client.get(base + "/review-context", params=query | {"cursor": token})
        assert response.status_code == 200
        body = response.json()
        assert client.get(base + "/review-context", params={
            "sequence": 1, "limit": 1, "cursor": token,
        }).status_code == 422
    assert body["completeness"] == "COMPLETE"
    assert seen


@pytest.mark.parametrize("query", [
    {}, {"sequence": 0}, {"sequence": 1, "eventId": "a" * 64},
    {"sequence": 1, "limit": 101}, {"sequence": 1, "unknown": "x"},
    [("sequence", "1"), ("sequence", "2")],
])
def test_closed_review_query(scheduled_published, query):
    client, _, _, reference, _ = scheduled_published
    assert client.get(
        f"/api/v1/backtest-runs/{reference.run_id}/review-context", params=query,
    ).status_code == 422


def test_exact_sequence_effects_and_readonly_store(scheduled_published, request):
    client, _, store, reference, report = scheduled_published
    assert report.event_count > 100
    base = f"/api/v1/backtest-runs/{reference.run_id}"
    observer = sqlite3.connect(store.database_path)
    request.addfinalizer(observer.close)
    before = observer.execute("PRAGMA data_version").fetchone()[0]
    rows_before = observer.execute(
        "SELECT detail_id, content_hash FROM backtest_detail ORDER BY detail_id"
    ).fetchall()
    last = client.get(base + "/review-context", params={"sequence": report.event_count})
    assert last.status_code == 200
    selected = last.json()["selected"]["event"]
    assert selected["sequence"] == report.event_count
    if selected["cause_event_id"]:
        effect = client.get(base + "/review-context", params={
            "eventId": selected["cause_event_id"], "relation": "EFFECTS", "limit": 100,
        })
        assert effect.status_code == 200
        assert selected["event_id"] in [r["event"]["event_id"] for r in effect.json()["items"]]
    response = client.get(base + "/review-context", params={"sequence": report.event_count + 1})
    assert response.status_code == 404
    assert observer.execute("PRAGMA data_version").fetchone()[0] == before
    with sqlite3.connect(store.database_path) as connection:
        assert rows_before == connection.execute(
            "SELECT detail_id, content_hash FROM backtest_detail ORDER BY detail_id"
        ).fetchall()


def copied_store(original, tmp_path):
    from trade_plan_monitor.backtest.results import BacktestResultStore

    path = tmp_path / "review.sqlite3"
    with sqlite3.connect(original.database_path) as source, sqlite3.connect(path) as target:
        source.backup(target)
    source.close()
    target.close()
    return BacktestResultStore(path)


def read_context(store, reference, **selector):
    from trade_plan_monitor.backtest.pagination import HmacCursorSigner
    from trade_plan_monitor.backtest.review import read_review_context

    return read_review_context(
        store, HmacCursorSigner(b"x" * 32), run_id=reference.run_id,
        selector=selector, relation="CAUSES", limit=20, cursor=None,
    )


def test_old_schema_bounded_rebuild_preserves_all_canonical_bytes(scheduled_published, tmp_path):
    from trade_plan_monitor.backtest.migration import DatabaseState, inspect_result_database
    from trade_plan_monitor.backtest.results import BacktestResultStore
    from trade_plan_monitor.backtest.review import rebuild_review_batch

    _, _, original, reference, report = scheduled_published
    store = copied_store(original, tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE backtest_review_event")
        before = connection.execute(
            "SELECT detail_id, content_hash, payload_json FROM backtest_detail ORDER BY detail_id"
        ).fetchall()
    connection.close()
    assert inspect_result_database(store.database_path).database_state is DatabaseState.CURRENT
    store = BacktestResultStore(store.database_path)
    initial = read_context(store, reference, sequence=report.event_count)
    assert initial["projectionStatus"] == "NOT_READY"
    after = None
    batches = 0
    while True:
        after = rebuild_review_batch(store, reference.run_id, after=after, limit=100)
        batches += 1
        if after is None:
            break
    assert batches > 1
    result = read_context(store, reference, sequence=report.event_count)
    assert result["projectionStatus"] == "READY"
    with sqlite3.connect(store.database_path) as connection:
        assert before == connection.execute(
            "SELECT detail_id, content_hash, payload_json FROM backtest_detail ORDER BY detail_id"
        ).fetchall()
    connection.close()
    assert inspect_result_database(store.database_path).database_state is DatabaseState.CURRENT
    BacktestResultStore(store.database_path)


def test_expired_cause_keeps_durable_fill_and_removes_derived_rows(scheduled_published, tmp_path):
    from trade_plan_monitor.backtest.pagination import HmacCursorSigner
    from trade_plan_monitor.backtest.review import read_review_context

    client, _, original, reference, _ = scheduled_published
    store = copied_store(original, tmp_path)
    fill = client.get(f"/api/v1/backtest-runs/{reference.run_id}/fills").json()["items"][0]
    signer = HmacCursorSigner(b"x" * 32)
    before = read_review_context(
        store, signer, run_id=reference.run_id, selector={"fillId": fill["fillId"]},
        relation="CAUSES", limit=1, cursor=None,
    )
    assert before["hasMore"]
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM backtest_detail WHERE run_id = ?", (reference.run_id,))
        connection.execute(
            "UPDATE backtest_run SET decision_expired_at = ? WHERE run_id = ?",
            ("2026-10-20T12:00:00.000000+08:00", reference.run_id),
        )
        connection.commit()
        assert connection.execute("SELECT count(*) FROM backtest_review_event").fetchone()[0] == 0
    context = read_context(store, reference, fillId=fill["fillId"])
    assert context["fill"] is not None
    assert context["selected"] is None and context["items"] == []
    assert context["availability"] == "EXPIRED" and context["completeness"] == "PARTIAL"
    assert context["missingEventId"] == fill["eventId"]
    continued = read_review_context(
        store, signer, run_id=reference.run_id, selector={"fillId": fill["fillId"]},
        relation="CAUSES", limit=1, cursor=before["nextCursor"],
    )
    assert continued["availability"] == "EXPIRED" and continued["fill"] is not None


def test_corrupt_index_cannot_substitute_another_event(scheduled_published, tmp_path):
    _, _, original, reference, report = scheduled_published
    store = copied_store(original, tmp_path)
    selected = read_context(store, reference, sequence=report.event_count)["selected"]
    identity = selected.payload["event_id"]
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE backtest_review_event SET content_hash = ? WHERE event_id = ?",
            ("f" * 64, identity),
        )
    with pytest.raises(RuntimeError, match="metadata/hash mismatch"):
        read_context(store, reference, eventId=identity)


def test_causal_queries_use_bounded_identity_and_edge_indexes(scheduled_published):
    _, _, store, reference, _ = scheduled_published
    with sqlite3.connect(store.database_path) as connection:
        identity = connection.execute(
            "EXPLAIN QUERY PLAN SELECT detail_id FROM backtest_review_event "
            "WHERE run_id = ? AND event_id = ? LIMIT 2", (reference.run_id, "a" * 64),
        ).fetchall()
        children = connection.execute(
            "EXPLAIN QUERY PLAN SELECT sequence, event_id FROM backtest_review_event "
            "WHERE run_id = ? AND cause_event_id = ? AND sequence > ? ORDER BY sequence LIMIT 21",
            (reference.run_id, "a" * 64, 0),
        ).fetchall()
    assert any("ix_backtest_review_identity" in row[3] for row in identity)
    assert any("ix_backtest_review_cause" in row[3] for row in children)
    assert not any("SCAN" in row[3] for row in identity + children)
