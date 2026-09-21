# 运行恢复基础实现 — 2026-09-21

英文规范输入：`2026-09-21-runtime-recovery-foundations.md`；本文件为中文副本。

## 范围与授权

用户于 2026-09-21 授权实现。本报告只覆盖隔离的行情源/恢复基础能力，不表示“任意时段重启”整体需求完成。生产装配尚未启用新恢复路径。未修改真实配置、请求真实行情、发送真实提醒、重启进程或迁移生产数据库；仅使用临时数据库和模拟传输。实现阶段未提交、推送或部署；随后用户另行授权整理提交并发布至 GitHub，不包括部署。

发布范围：已有开发分支 `codex/consolidate-r19-r32`，不合入 `main`，不改写历史。按契约、语义记录、检查点存储、请求准入、恢复目标/队列、注入式门禁及验证文档分组。发布前重新执行下方组合回归：368 项通过、1 项已有警告、41.39 秒。Ruff、生成契约和空白检查通过。对 27 个待提交文件进行有界检查，未发现常见凭证/私钥模式；真实配置和运行数据不在发布范围。这不替代下文的全量测试失败记录和启用限制。

## 已实现切片

- RR001：成对 `SPEC-provider-contract` 和 `SPEC-runtime-recovery` 细化已有且获批的 D1–D6 边界。详细传输/状态规格及完整 C0 评审仍待完成。
- RR003：历史证据读取与相互独立的持久语义旁文件。旧七天时效读取保持原契约；注入的新门禁使用 semantic revision。检查实际 SDK 兼容性；不重写原始证据和运行健康状态。原子、不覆盖式发布处理并发导入。
- RR004（部分）：通过 `ProductionSemanticBindings` 注入独立股票/指数门禁，包括仅指数看板路径。尚未切换公共装配，也未接入“已选股票失败后仍调度指数”的编排。
- RR005：增量 `0018_provider_recovery` 和有界检查点存储，每个行情源身份最多 74 行（64 个工作退避 + 9 个 operation 权限 + 1 个共享冷却）。存在检查点时拒绝降级。已更新原有最新 head 断言和元数据一致性检查。
- RR006（基础）：可选持久化控制器绑定、受控/合并的权限重查、有界公平范围队列、旧目标隔离及稳定重试准入。未绑定持久化仓储的控制器也保留迟到物理失败，但这不启用生产自动重试。它尚不是后台运行所有者。
- RR007/RR008（基础）：纯时段目标与精确持久化分钟覆盖检查，每个工作单元最多 240 个身份，冻结截止点，拒绝跨日/时钟回拨后沿用旧获取结果。尚未安装默认恢复协调器或业务状态重放。

## 执行分配与方法

行情源/门禁、重试/存储、覆盖判断子 agent 明确使用 `gpt-6-astra` / `high` 启动。独立基础、语义门禁与准入审查使用 `gpt-6-astra` / `xhigh`。这是工具确认的子 agent 设置，不声称主会话模型设置可变。用户选择跳过额外跨模型审查。
测试驱动与增量实现技能要求先出现失败案例再修改源码。接口设计与迁移技能使新路径保持注入式、存储保持增量式；并发/所有权假设经过独立审查。官方实现参考：[Python 3.14 任务取消](https://docs.python.org/3.14/library/asyncio-task.html)、[SQLAlchemy 事务边界](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)。

实际应用的技能：`using-agent-skills`、`spec-driven-development`、`api-and-interface-design`、`documentation-and-adrs`、`incremental-implementation`、`test-driven-development`、`deprecation-and-migration`、`source-driven-development`、`debugging-and-error-recovery`、`doubt-driven-development`、`code-review-and-quality`。它们指导了契约先行的增量切片、红/绿测试、官方资料核查和有界对抗审查修正；不构成真实操作授权。

## 验证证据

所有命令均在 `trade-plan-monitor` 中执行。

| 检查 | 实际结果 |
|---|---|
| 下方基础/回归组合命令审查后最终运行 | 368 项通过、1 项已有 Starlette 警告、43.60 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/unit -m "not live" -q --tb=short` | 1574 项通过，2 项失败见下文，15.14 秒；不声称全单测通过 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照及前端类型为最新 |
| `git diff --check` | 通过；存在原有 LF/CRLF 转换提示 |
| 全集成、前端构建/浏览器及真实进程重启验收 | 本基础检查点未执行 |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_live_certification_profiles.py tests/unit/test_provider_contract.py tests/unit/test_recovery_targets.py tests/unit/test_runtime_reconciliation.py tests/unit/test_request_recovery_admission.py tests/unit/test_monitor_runtime.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_sqlite_repositories.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py tests/integration/test_certified_production_runtime.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
```

## 发现与处理

独立基础审查发现三项有效问题，均通过失败测试复现并修正。第 2 轮在其限定范围内未发现未解决问题：

1. 并发发布旁文件可能覆盖另一导入。现在使用原子、不覆盖式链接发布；已存在目标只校验，不覆盖。
2. 目标切换后才返回的失败可能丢失重试期限。现在丢弃旧业务就绪结果，同时保留稳定范围的重试门禁。
3. 持有执行票据、无法继续准入时仍立即唤醒。现在执行中返回未来维护唤醒点，避免空转。

准入审查另发现三项有效问题，也均先复现再修正：

4. 普通调用方取消后丢失迟到的物理限流/权限/临时失败。现在由控制器拥有的完成处理先记录结果，再释放容量或所有权；已经记录的超时不重复计数。
5. 排队延迟缩短了 300 秒权限间隔。现在保留初始持久预留，并在物理提交前再次延长。
6. 正常返回时保存检查点失败，可能释放所有权，让可读的旧状态遗漏已知冷却。现在所有未解决检查点故障均在清理线程后阻止替换，不再保留单独的迟到故障标志。

准入审查共完成三轮有界检查；最终修正在限定范围内未发现剩余高置信问题，四项针对所有权/故障的检查通过。独立注入式语义门禁审查未发现具体回归/错误放行问题。随后再次执行上方最终组合命令。这些有界审查不代表 C1 尚缺少的自主集成或整体功能已批准通过。

## 已有失败与限制

两项单测失败均在本次未修改的文件中单独复现：

- `test_market_data.py::test_tushare_provider_errors_use_stable_codes_and_drop_raw_context[provider_error2-TRANSIENT]`：测试预期 TRANSIENT，行情适配器返回 TIMEOUT。
- `test_r14_bounded_acceptance.py::test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`：模拟请求缺少 temperature，但现有传输要求 `temperature == 0`；在模拟处理器之前抛出 BudgetDenied。这不是真实外部 AI 请求。

`2026-09-17-change-consolidation.md` 记录的两项失败也已复现（2 失败、3 通过、14 未选择）：旧规范指数版本 head 时间与待补收盘指数异常时的参考健康状态。未删除、跳过或放宽任何失败测试。

## 剩余工作

C0–C5 仍未完成。需完成 RR002 及 RR004 集成、安装持久运行协调器、发现漏执行收盘义务、隔离业务提交、增加原子提醒资格和恢复屏障、实现真实局部状态/版本化传输/UI，然后执行实际离线进程重启及完整验收门禁。不能据这些基础实现声称当前页面一直“恢复中”的问题已经解决。
