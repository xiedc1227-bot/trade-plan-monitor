# Native owner accounting P0 specification

## NOA-S01. Scope
Implement the paired proposal in isolated children only. Preserve independent authority, complete integrity validation and physical cancellation/drain. No production allocator replacement, reduced budget or P1 before coverage and ownership qualify.

## NOA-S02. Observer
Wrap existing Python RAW/MEM/OBJ allocators after initialization; retain existing arena policy. Configure the actual SQLite DLL before driver import. Use bounded native bookkeeping, thread-safe pointer/domain records, saved owner on free, and conservative realloc overlap. Report baseline unknown frees, lost records and observation overhead. Logical domain totals are not deduplicated backing bounds.

## NOA-S03. Experiments
Record native source/build/runtime identity. Test small and large objects, dense errors, actual SQLite queries, cross-thread free, late configuration and fixed-table exhaustion. Compare oracle outputs outside the measurement process. Preserve existing tamper, time, deadlock, cleanup and drain regressions. Stop dependent admission changes if any coverage/ownership gate fails.

## NOA-S04. Acceptance
Keep 64 MiB input, 768 MiB working set and 2560 MiB private commit. Require source-derived bounds, arena/backing reconciliation and funded result transfers before legal-row budget changes. Three diagnostic rounds are not qualified performance. Report unperformed gates honestly; P1 remains NO_GO until all proposal gates pass.
