# 旧计划缺心跳维护验收 — 2026-09-23

## 范围与结果

已批准的 D8/A13 缺心跳处理接入生产网页装配和系统页面。存在活动计划但没有心跳时进入 `BLOCKED`，不再无限显示数据过期/恢复中，也不自动重放计划。网页继续可用，但监控任务、行情请求、心跳和提醒发送均不启动；普通 HTTP 写入返回 `409`。预览列出准确的活动计划身份及指纹。经过独立勾选确认后，一笔事务作废这些计划，清理并审计待处理收盘，抑制已有投递资格并记录批次审计。持仓和已确认成交不变。操作人须先重启工具再新建计划。

## 验证依据

- 有意义的 RED 测试首先因缺失人工处理模块、类型化阻断准入和 HTTP 端点而失败；实现后这些场景通过。
- 临时 SQLite 测试覆盖预览指纹变化、预览后新增心跳、第二个计划停用失败时回滚、保留 1,000 股持仓、重复确认不重复审计、普通写入受阻、受阻启动不请求行情/不产生任务，以及作废后在同一解释器内新建应用生命周期进入 `DEGRADED` 且旧计划不再出现。另一个独立进程在首只计划事务内停用后被杀：重新打开时两只计划及待收盘任务均仍在、没有审计；第二个进程按同一预览准确作废一次，持仓不变。
- `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_plan_expiry.py tests/integration/test_runtime_liveness.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py tests/integration/test_web_api.py -q --tb=short` — 218 passed，存在一个既有 Starlette/httpx 弃用警告。此前一次回归发现全局依赖仅接受 HTTP 参数，导致四项 WebSocket 测试失败；改用 `HTTPConnection` 后四项全部通过，WebSocket 行为未变。
- `npm test -- --run` — 46 个文件中 670 passed，包含 `SystemView.spec.ts` 的 14/14 及响应丢失时结果不确定的场景。`npm run type-check` 和 `npm run build` 通过。测试夹具补齐遗漏的 dashboard 假响应后，`npm run test:e2e -- tests/e2e/legacy-maintenance.spec.ts` 在隔离 Chrome 中通过。已目视检查 375 px 系统页截图：没有水平溢出或丢失确认控件。浏览器控制台/请求审计及 WCAG 2.1 A/AA axe 扫描通过。
- 生成 51 路径的 OpenAPI/前端契约后，`.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` 通过。所有读取与写入仅涉及临时数据库；没有真实行情源、真实提醒、用户数据库、部署或 GitHub 推送。

## 剩余门禁

V1d 仍需为没有现存投递资格记录的旧未发提醒留下持久终态，并完成全面安全复核。V1c/RR009 仍有有界历史证明和生产恢复集成义务。本切片不关闭业务第一步，也不批准生产迁移。更广的全链路进程重启与提醒发送故障验收仍待完成。
