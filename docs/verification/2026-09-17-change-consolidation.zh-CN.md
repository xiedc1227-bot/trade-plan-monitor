# 修改整理 — 2026-09-17

英文规范输入：`2026-09-17-change-consolidation.md`；本文件为中文评审副本。

## 范围与交付

用户要求整理既有修改并推送至 GitHub。交付分支为 `codex/consolidate-r19-r32`，不代表批准合入或部署。验证暴露了两项可复现失败，因此有意不更新 GitHub `main`。

- 保留已获取的 `origin/main` 之后的 37 个既有提交，包括连续的 R19–R32 历史。创建交付分支前，本地 `main` 已从 `e947397` 快进至 `c92f18d`；没有重写既有提交。
- 将既有成交额修正及其测试/规格单独分组：当日累计成交额与上一交易日从开盘至相同截止点的桶进行比较，并要求上一交易日时段完整。
- 保留双语运行恢复提案与任务表的 DRAFT / NOT STARTED 状态。发布文档不代表批准其设计、迁移、实现或上线。
- 仅修正 `tests/integration/test_source_treatment_review_api.py` 的导入排序，不改变断言或运行行为。
- 保留隔离的 R29–R32 工作树及历史证据，不重放任何已消费的验收请求，不启动 R33。

## 已执行验证

命令在 `trade-plan-monitor` 中使用既有虚拟环境运行。

| 检查 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 纯导入排序修正后通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照与前端类型为最新 |
| 待提交双语文档 | 49 对文件均存在且章节数量一致；运行恢复的决策/验收/任务 ID 次数也一致 |
| `git diff --check` | 通过；Git 提示已有的 LF/CRLF 转换提醒 |
| 下方定向测试命令 | 158 项通过、2 项失败、1 项既有 Starlette 弃用警告，耗时 40.58 秒 |
| 未修改的 R32 `c92f18d` 上复测相同两项 | 均复现，耗时 5.05 秒 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short` | 已启动，在长时间回测容量组中主动中断；不宣称全量通过 |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_turnover.py tests/integration/test_market_index_runtime.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_live_pipeline_acceptance.py tests/integration/test_r29_v6_extraction_acceptance.py tests/integration/test_r30_ai_timeout_budget_acceptance.py tests/integration/test_r32_ai_transient_acceptance.py tests/unit/test_r30_ai_timeout_budget.py tests/unit/test_r26_ai_timeout_diagnostics.py tests/unit/test_r28_field_binding_diagnostics.py tests/integration/test_source_treatment_review_api.py -q --tb=short
```

## 未解决的合入阻塞项

两项失败均位于 `tests/integration/test_live_pipeline_acceptance.py`，在不含成交额修改的干净 R32 工作树中也能复现：

1. `test_market_index_persistence_reuses_an_older_canonical_content_revision`：头记录的 `updated_at` 保持 `10:36`，而断言要求 `10:38`。持久化路径在推进头记录前合并了 issues 相同的重复 BLOCKED 快照。该合并规则与规范版本复用之间的预期关系需单独限定范围处理。
2. `test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`：恢复后的参考状态为 LIVE，测试要求 BLOCKED。持久化路径在后续获取结果非 LIVE 时保留已有 LIVE 头记录。需解决契约与测试之间的关系，不能直接放宽断言。

相关持久化实现在已获取的 `origin/main` 至 R32 之间未变化。本报告记录证据，不决定改变上述任一生产规则。没有删除、跳过或放宽失败测试。合入/部署评审前仍需完成被中断的全量测试、前端构建/浏览器门禁，并解决失败项。

## 数据与发布边界

本次整理没有批准或执行真实 AI、行情或账户请求；仅 GitHub 同步在范围内。真实 `config/app.yaml` 仍未跟踪且未改变，SHA-256 为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`。

已检查待推送的 37 个既有提交历史中的常见凭证/私钥模式及本地真实凭证精确匹配，未发现匹配。这是有限检查，不是全面安全审计。真实配置、凭证、数据库及本地原始外发审阅包不纳入推送。保留已跟踪的 `data/r20-acceptance/r20-20260915-a/termination.json`：它仅含脱敏终态元数据、计数及零行摘要，不含上游原始响应或凭证。
