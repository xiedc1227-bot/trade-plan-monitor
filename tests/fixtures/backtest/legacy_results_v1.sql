PRAGMA journal_mode=DELETE;

CREATE TABLE backtest_run (
    run_id TEXT PRIMARY KEY,
    plan_sha256 TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED', 'CANCELLED')),
    completed_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    summary_hash TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE backtest_fill (
    fill_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
    filled_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE backtest_detail (
    detail_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES backtest_run (run_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    event_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO backtest_run (
    run_id,
    plan_sha256,
    dataset_hash,
    status,
    completed_at,
    pinned,
    summary_hash,
    summary_json,
    created_at
) VALUES (
    'legacy-completed-v1',
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'COMPLETED',
    '2026-08-24T07:20:00.000000+00:00',
    0,
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    '{"schemaVersion":"backtest-run-summary-v1","runId":"legacy-completed-v1"}',
    '2026-08-24T07:20:00.000000+00:00'
);
