# 计划库读取状态验证 — 2026-10-20

## PL-R01. 故障证据

本地 `backtest-preparation.sqlite3` 中存在 19 条准备记录，其中包含 8 份 `SINGLE` / `REVIEWED` 版本。结果库中存在 5 条运行记录及 14,800 条明细。通过 SQLite `mode=ro` 与 `PRAGMA query_only=ON` 获取计数，没有导出计划原文。这些计数证明仍有记录保留，不能作为全部历史完整无缺的审计结论。

运行中的计划库与运行列表接口均返回 HTTP `503`。`/api/v1/backtest-service` 返回 `DEGRADED`、`canRead: false`、`physicallyDrained: true` 及 `SERVICE_REPAIR_REQUIRED`。组件错误地将读取失败与空列表提示同时展示。直接只读执行计划库投影及响应校验，可以成功返回全部 8 份已审核版本。隔离 SQLite 备份上的元数据初始化也成功。隔离异步生命周期诊断在观察期内未完成，已停止它的两个辅助进程。没有捕获运行中服务降级时最初的异常或超时，因此最初触发原因尚未确认。

## PL-R02. 恢复与范围

向 `/api/v1/backtest-service/recovery-requests` 显式提交 `RETRY_PREPARATION` 与 `resumeJobIds: []`。接口返回 `202`；服务转为 `READ_READY`、`canRead: true`，计划库返回 8 份已审核版本。既有 Chrome 页面随后显示 2 条时间线，每条 4 次更新。没有恢复回测任务，没有删除业务记录、重新创建计划或改写原文。

UI 现已区分读取失败与空结果，说明 HTTP `503` 的恢复入口，重试期间隐藏旧错误，并在刷新失败时保留上次成功列表及选择、明确标注记录可能过期。双语操作说明位于 `docs/operations/plan-reuse.md` 与 `docs/operations/plan-reuse.zh-CN.md` 的 `PR-O10`。

## PL-R03. 验证

- `npm test -- --run tests/unit/PlanLibrary.spec.ts tests/unit/PlanLibraryPagination.spec.ts`：22 项通过，包含修复前失败的 3 项新增回归测试。
- `npm run type-check` 与 `npm run build`：通过，已更新打包前端资源。
- `npx playwright test tests/e2e/plan-library-versions.spec.ts`：Chrome 中 3 项通过。新增流程验证 HTTP `503`、显式刷新列表、恢复 8 个版本、刷新失败保留已选末端版本，以及成功响应确认空列表；观察到的请求中没有变更请求。原有 200% 文字及 30 条时间线分页流程也通过。
- 另在 Chrome 检查实际本地页面：显示 2 条时间线及 8 个版本。截图为本会话可视化目录中的 `plan-library-restored.png`。

运行服务最初降级的触发原因与创建页的整体改版不在本次已验证修复范围内。保留了工作区已有改动。
