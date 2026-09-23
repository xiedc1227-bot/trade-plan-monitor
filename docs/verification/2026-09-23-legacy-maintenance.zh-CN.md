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

V1d 仍需明确无法分类旧提醒的安全复核处置、在维护状态中显示清理失败，并完成全面安全复核。V1c/RR009 仍有有界历史证明和生产恢复集成义务。本工作不关闭业务第一步，也不批准生产迁移。更广的全链路进程重启与提醒发送故障验收仍待完成。

## 终态回执事务基础能力

`DeliveryEligibilityRepository.suppress_invalidated_identity` 现会将规范提醒与准确计划身份核对；缺失回执时先建立 HOLD，再在调用方事务内提升为终态 `SUPPRESS/ACTIVE_IDENTITY_INVALID`，留下两条按修订号记录的审计。身份不符不写入；重复抑制幂等；回滚会恢复已有 HOLD。读取器现在允许旧版提醒使用这一通用作废原因，修复了此前与长停机/人工批量抑制相矛盾的校验，同时仍拒绝显式规则专属的终态原因。新增 RED 测试先因缺少方法而失败。随后 `tests/integration/test_delivery_eligibility_storage.py`、`tests/unit/test_legacy_recovery_delivery_eligibility.py` 和 `tests/integration/test_runtime_plan_expiry.py` 合计 116 项通过，存在一个既有警告；Ruff 与差异空白检查通过。

下述已接通的分批清理使用此基础能力。若在启动事务内全量扫描旧提醒，重启耗时会依赖历史数据量及损坏记录；现有“当前活动计划身份”发送门禁仍是即时安全边界。V1d 与业务第一步仍未完成。未触及用户数据库或外部发送器。

## 准入后有界旧提醒清理

启动只冻结带索引的提醒最高序号。随后每次 30 秒存活心跳最多按序检查 100 条旧提醒，回执/审计事务提交后才推进内存游标。每批还必须持有刚写入的心跳修订号，使已被替代的运行实例无法写入清理状态。规范提醒的计划 ID/版本/哈希/标的须与已停用的 `PlanVersion`，以及准确记录超过 120 小时或旧库人工作废原因的停用审计共同匹配；普通停用本身不足以终态抑制。终态作废版本也会在激活时被拒绝，避免清理完成前复用原身份使旧提醒再次变成“当前”；普通再激活不受影响。逐提醒终态不宣称历史上未曾向外部发送。规范提醒损坏或元数据损坏时留下稳定、不含载荷原文的 `ALERT_INVALIDATION_UNCLASSIFIED` 审计，不猜测回执。暂时清理失败会回滚该批并重试，不阻断心跳。重启可能重新扫描先前行，但不重复终态回执。在清理完成前，发送器的当前计划身份门禁仍即时排除旧提醒。本增量不含结构迁移、行情请求、发送请求或持仓变化。

先失败的测试证明心跳后缺少回执、有界清理模块缺失、普通已停用版本被错误抑制，以及终态作废版本可被重新激活。临时 SQLite 测试覆盖超过 120 小时准入、人工作废后重启、两条批量上限、旧心跳修订号拒绝、批内失败回滚/重试、暂时心跳失败后重试、损坏行审计及后续有效行继续处理、普通停用不终态抑制，以及终态版本拒绝/普通版本允许再激活。停用审计损坏时激活拒绝。受影响的仓储/提醒/运行时/API 回归组 609 项通过，存在一个既有 Starlette/httpx 警告。V1d 在清理故障可见性、无法分类记录处置及完整发布评审前仍未完成。
