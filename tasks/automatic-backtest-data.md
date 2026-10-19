# Automatic backtest data preparation

## AD-01 — Approved behavior and boundaries

The user authorized implementation of one start action: check local evidence, fill missing historical data, validate and freeze the dataset, then replay the reviewed plan chain. Remove `应用到当前 URL`, `同步历史数据`, `本地验证数据集` and `刷新已缓存表面` from the UI. No AI call is needed. Read-only visits must never authorize downloads. Keep progress, cancellation, safe same-request retry and explicit retry after failure. Existing frozen inputs, datasets and reports must remain unchanged.

## AD-02 — Implementation

- [x] Derive scope and warm-up on the server from the reviewed single plan or collection. Add a read-only data check with strict manifest binding; final admission rechecks and freezes authority. Verified result-owned copies may be reused with identical authority/account/requirements/cutoff; at most 20 matching inputs are inspected, and new submissions never rewrite old objects.
- [x] On start, automatically check, submit the existing bounded durable data-sync job only if needed, wait for its authoritative status, recheck, then submit the existing run command. Keep sync requests idempotent and prevent continuation after cancellation or navigation. Do not add a second worker or silently resume old jobs.
- [x] Make historical data management read-only. Explain that preparation happens automatically at start. Preserve list filtering, paging and task inspection/cancellation.

## AD-03 — Acceptance and verification

- [x] Deterministic tests cover cached/no-network, missing-data sync, verification failure, uncertain submission retry, cancellation/late completion, unmount and immutable historical results. Frontend 1112 / backend 259 passed, with 1 platform skip; type/build, both contract checks and 3 focused real Chrome journeys passed. The cancellation mutation was detected and restored.
- [x] The four already-reviewed actual plans completed continuous replay with 1468/1468 events; automatic verified-copy reuse needed no download or AI request. Source hashes match the baseline, the old full report is unchanged, and 47 retained files keep their hashes. Record actual evidence and limits in [AD-V03–AD-V04](../docs/verification/2026-10-18-automatic-backtest-data.md#ad-v03--four-actual-plans); README, operations, specification and task status are updated in English and Chinese.

Code follows existing Python domain/service boundaries and Vue Composition API with TypeScript; no dependency or database migration is planned. Tests live in `tests/integration` and `web/tests`; documents retain their existing paired locations. Commands: `.venv/Scripts/python.exe -m pytest`, `npm test -- --run`, `npm run type-check`, `npm run build`, `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`.
