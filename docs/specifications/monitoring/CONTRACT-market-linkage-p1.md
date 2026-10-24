# Contract inventory: market-linkage-p1

## MLC1-01 — Approved authority and baseline

On 2026-10-24 the user approved MLP1-D01–MLP1-D06 and explicitly authorized all ordered P1 tasks and staged acceptance without repeated confirmation. Baseline `dbeff32`, branch `main`; the only pre-existing changes are the eight P1 proposal/index documents. [Specification](SPEC-market-linkage-p1.md) · [tasks](../../../tasks/market-linkage-p1.md) · [Chinese copy](CONTRACT-market-linkage-p1.zh-CN.md).

The V01 baseline passed: 91 tests in 1.20s. This establishes existing behavior, not P1 acceptance. T01 documentation slices are approval/status (four files), boundary inventory/report (four files), then index wording (four files).

## MLC1-02 — Reader and writer inventory

All source paths are under `src/trade_plan_monitor/` unless stated otherwise. Extend explicit variants and dispatch; never broaden Schema 6 to authorize an exception.

| Boundary | Observed owners | P1 change |
| --- | --- | --- |
| Strict plan and draft | `domain/market_linkage_models.py`, `market_linkage_validation.py`, `unified_plan_validation.py`, `daily_plan_validation.py` | Separate Schema 7 rule/plan and nullable draft policy; inherit common validations without modifying old fields |
| Codec and hashes | `domain/plan_codec.py`, `plan_hash.py`, `daily_plan_validation.py` | Explicit 7 dispatch, `plan-review-content-v4`; full canonical plan SHA-256 remains exact |
| Extraction/review | `ai/plan_extraction.py`, `extraction.py`, `loop_plan_extraction.py`, `models.py`, `prompts.py`, `daily_review.py`, `semantic_validation.py`, `domain/market_linkage_definitions.py` | `plan-extract-v10`, expanded exception bindings and no approval imports |
| Updates/preparation | `ai/plan_delta_wire.py`, `preparation_wire.py`, `plan_update_extraction.py`, `predecessor_patch.py`, `update_review.py` | Preserve explicit Schema 7 permission and require review for changes |
| Shared decision | `decision/confirmation_selection.py`, `quantity_policy.py`, `market_linkage.py`, `unified_lifecycle.py` | Dedicated v2 evidence/calculation plus pure exception validation; legacy evaluators remain exact |
| Durable authority | `state/daily_repository.py`, `daily_state_models.py`, `market_linkage_authority.py`, `daily_models.py` | Versioned candidate/event records in existing transactional storage; deterministic unique IDs, verified hashes and revision fencing |
| Production runtime | `runtime/daily_service.py`, `production.py`, `service.py`, `market_indexes.py` | Schema 7 dispatch; reuse acquisition and stable occurrence policy; persist candidates separately from executable signals |
| Execution/read/send | `state/simulation.py`, `web/daily_service.py`, runtime completion/read and notification admission | Exact persisted grant plus current gates; atomic whole consumption; no approval side effects on inventory |
| HTTP and UI | `web/routers/plans.py`, `daily_plans.py`, service composition; `web/src/composables/usePlanWorkspace.ts` and plan components | Three new command families from MLP1-09, versioned runtime view; generate both API profiles; local guards unchanged |
| Replay | `backtest/run_input.py`, `loop_input_store.py`, `loop_dataset.py`, `loop_replay.py`, `runner.py`, `loop_runner.py`, `research_runner.py`, `composition.py`, `plan_schedule.py`, `plan_updates.py`, `preparation_review.py` | `backtest-run-v8` and frozen explicit authorization events, both runtime/research entry paths |

## MLC1-03 — Version and storage decisions

The proposed version names have no existing conflicting source definitions. Preserve the approved Schema 7 / `condition-plan-v3` / `market-linkage-v2` identities. Review uses `plan-review-content-v4`; evidence/calculation use `market-linkage-evidence-v2` and `market-linkage-calculation-v2`; candidate and authorization use `market-linkage-exception-candidate-v1` and `market-linkage-exception-authorization-v1`. Every hash uses canonical JSON and the existing domain/NUL/SHA-256 convention. No new defaults are serialized into old objects.

Retain market/index formulas and Q0/ordinary sizing fields. Per-rule `market_policy.exception_routes` contains both required permission fields; explicit DISABLED/DISABLED remains valid. Missing values may exist in drafts but prevent executable validation. Keep existing plan/expanded-tree limits.

Reuse `DailyRecord` with deterministic candidate, event and command identities and the existing write transaction/revision checks; its primary key supplies durable uniqueness. Candidate state is a mutable fenced projection; authorization and terminal event payloads are append-only. Event IDs include occurrence plus transition identity so different command keys cannot repeat approval or consumption. Exact field validation is mandatory before saving and after loading; no unknown-record permissiveness may grant authority. Existing idempotency receipts guard request bodies and remain in the same transaction as effects. A new physical table/migration is unnecessary unless inspection proves otherwise; that would be recorded and tested additively before use.

Candidate binds the full identities in MLP1-08, the eligible D evidence, computed next session and server-derived close, frozen input calculation, and original independent-event continuity. Approval freezes its exact quantity and creates a signal bound to candidate/approval IDs. The new evidence/calculation models distinguish unapproved candidate sizing from a positive approved grant; do not change the v1 validator that equates ordinary calculation with its frozen signal quantity. Previews are immutable audit snapshots of displayed content, with no permission or inventory effects; approval recomputes against current revisions.

## MLC1-04 — Compatibility and completion gates

| Input/state | New reader | Older reader / rollback |
| --- | --- | --- |
| Schema 1–6 and existing research/state | Exact existing dispatch, serialized bytes and hashes | Unchanged |
| Schema 7 with exceptions disabled | Ordinary behavior plus explicit disabled reasons; no grant | Reject unsupported version, no downgrade |
| Schema 7 with enabled exceptions | Eligibility plus exact local approval required | Reject unsupported version; preserve records |
| New candidate/authorization/research events | Verify version, digest, occurrence, cutoff and state | Preserve bytes, block operations, never treat as an ordinary signal |

T02 sequential slices: T02a models plus codec and contract tests; T02b draft model/dispatch and tests; T02c review hashing and issue dispatch plus tests. Each slice contains at most five source/test files. Public activation, extraction and execution support remain unavailable until their owning tasks complete; a domain codec alone is not shipped support.

T04 sequential slices: T04a expanded bilingual definitions, semantic review and integration tests (four files); T04b current prompt/version dispatch and tests (up to five files); T04c provider/config defaults and loop prompt compatibility (up to five files). T05 owns compact preparation and predecessor patch propagation. Permission fields and expanded definitions require validated source meaning even when the binding claims literal SOURCE, not only SOURCE_SEMANTIC.

T01 is accepted only with V01 and paired-document checks. Later tasks require executed evidence in the [P1 verification report](../../verification/2026-10-24-market-linkage-p1.md); no unchecked task is a completed feature.

T06 inspection found `ck_daily_record_kind` excludes new evidence kinds. Additive migration `0026_market_exceptions` widens this constraint, preserves existing payload bytes, and adds a unique event command index. Downgrade refuses when new records exist. No user database is migrated during implementation. T06a models/repository/tests; T06b kind validation, immutable repository guard and migration; each slice is independently checked.

T09 verified slices: (a) v2 calculation/evidence, zero-authority occurrence seed and persistent unions; (b) existing activation/review dispatch; (c) owned candidate/approval bridge and runtime composition; (d) read/send/completion authority and focused race regressions. Generated artifacts and explicit old-contract projection changes belong to T11/T12.

## MLC1-05 — Frozen replay technical encoding (MLP1-T16)

`frozen-exception-event-v1` binds the original candidate projection, original v2 market evidence, immutable event, exact plan hash, provenance and deterministic order; an envelope hash protects all of them. `exception-replay-program-v1` freezes the ordered `exception_authorization_events` and the existing explicit `ResearchSimulation` operation shape for loop replay. Single research uses `unified-research-input-v2`, with that event stream alongside its existing operation script. Schema 7 selects `backtest-run-v8`; older input variants omit new optional fields and retain original hashes. Monitor-loop schemas retain their existing single/scheduled/workbench shape while an explicit v8 formula and optional frozen exception program distinguish the new behavior.

Private replay never imports a live grant as an executable local record. It retains original identities as source evidence, verifies the exact frozen plan hash/content, occurrence, route, consumed evidence, grid and original window, then applies the frozen event through the shared command policy to the isolated session. Private plan/review and event receipt IDs may differ; this mapping is explicit and cannot be exported as live authority. Recorded events remain labeled RECORDED_LOCAL; research events remain labeled RESEARCH_SCENARIO. A consumed event is an audit assertion, never an execution command. Events before the research start are rejected rather than silently treated as an opening approval; choose a start that includes the required evidence and event timeline. Future events are consumed only at their original receipt time. No future event participates in private authority identity.

The loop `exception_program.operations` records explicit execution requests at `at`; it retains the existing `NEXT_ELIGIBLE_MINUTE_CLOSE` model and configured response delay. It must first bind a current eligible exception reminder, then execute no earlier than the next complete eligible minute. Single research `operations` retain their existing explicit simulation-at-time semantics. Neither entry infers an operation from an approval or `FOLLOW_REMINDERS`. Loop reports retain each source operation, authorization outcome, request outcome and provenance; an empty provenance tuple means no authorization was supplied. These are execution-model distinctions, not changes to the approved quantity/window policy.


## MLC1-06 — Persisted replay evidence

Single-research decisions persist `exception_outcomes` in their existing decision records. Schema 7 signals may use `ResearchSignalReference.market_linkage_ref`: the complete, hash-validated evidence is retained once in the same decision's `market_linkage` or `signal_linkage` pool. Both pre-operation and post-operation states resolve and validate the original frozen calculation. A missing or substituted reference is rejected. This lossless representation preserves the existing 32 KiB item limit; Schema 1–6 serialization remains unchanged. Publication binds outcome provenance/identity/time to the frozen input; loop publication additionally binds each requested operation and report request outcome to the actual audit trail.
