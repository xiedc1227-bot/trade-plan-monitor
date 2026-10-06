# 回测 CLI 移除验证 — 2026-10-06

## 范围

用户明确要求移除且不保留 CLI 兼容。已删除 `backtest` 命令树（`sync`、`verify`、`run`、`list`、`prune`）、专用参数解析与服务注入、`BacktestApplicationService`、命令专用协调器和关闭策略，以及合成夹具生成器的 `--run` 分发。共用工作者工厂继续供生产 Web/API 组合使用。应用启动和无关的监控/AI 命令保留。

实施方案、任务清单、提案、当前规格、README 和回放指南已同步更新中英文。历史验证报告和已完成任务历史继续作为历史证据。不新增回测兼容别名或替代 CLI。

## 验证

- 实施前，新增的六项命令表面用例在原 CLI 下失败；移除后通过，覆盖创建文件前拒绝旧命令，以及保留 Web 启动参数。
- 命令/配置、协调器、存储、当前 HTTP 回放、打包及报告重建专项测试：**73 项通过**。
- 生产组合及数据/任务/运行/结果/导出 API 测试：**235 项通过、1 项跳过**。跳过项要求 POSIX 所有权语义，不适用于 Windows。两批测试均报告既有 Starlette/httpx 弃用警告。
- 相关文件 Ruff 检查、源代码编译及 `git diff --check` 通过。实际应用帮助不再包含 `backtest`，夹具帮助不再包含 `--run`。
- 删除的测试对应已退役接口。存储隔离断言改用生产组合，持久化报告重建直接在报告边界验证。当前 HTTP/任务/发布/导出覆盖继续保留。

在 `trade-plan-monitor/` 重现两批测试：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_command_surface.py tests/unit/test_config.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_results.py tests/integration/test_unified_replay_entries.py tests/integration/test_packaging.py tests/integration/test_backtest_runner.py::test_missing_report_files_are_rebuilt_from_materialized_results -q -m 'not live'
.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_exports.py -q -m 'not live'
```

## 边界

本次有意停止支持旧回测命令调用和已移除的 Python 服务封装。Web/API 和冻结结果格式继续支持。共用有界保留期清理服务保留为内部领域能力；移除 `prune` 命令不意味着新增自动清理调度器或替代的公开端点。

本次移除未调用供应商/AI/券商、修改生产数据、变更依赖、提交或推送。新的监控闭环回测仍处于方案阶段，本次未实现。此次后端移除未重跑全量测试或浏览器测试；此前记录的 OpenAPI 审批摘要不匹配不在这些检查范围内，未修改，也未宣称已解决。
