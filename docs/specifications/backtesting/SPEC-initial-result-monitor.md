# Initial result monitor startup

## IMS01. Scope and contract
Only fresh `backtest-run-detail` entry defers the same app monitor until the initial result succeeds or fails, with a maximum `5000 ms` timer. Other routes and already running monitors retain existing behavior. Route change releases the gate; unmount cancels its timer and prevents late startup. Invalid result identity releases without fetching. Pending connection remains truthful. App owns startup; result view reports settlement through a typed injection. No backend, native accounting, evidence, authority, cancellation or drain changes. Preserve unrelated AI extraction, daily inventory and README work.

## IMS02. Acceptance and stop
Run exactly `20` alternating baseline/candidate browser pairs from drained starts on the same data. Require median readiness improvement of both `20%` and `1.0 s`. Result-only and concurrent API latency and measured total CPU must not regress beyond `10%`; errors/refusals/timeouts must not increase. No p95 claim. Reject on correctness/boundary regression or failed fixed gate; do not expand scope or keep sampling until success. Timer bounds requested delay; event-loop suspension cannot guarantee wall-clock execution.

Same-result query normalization does not release the gate; a different pathname does.
