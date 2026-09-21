# 运行恢复增量验证 — 2026-09-21

> 英文规范输入：`2026-09-21-runtime-recovery-increments.md`；本文件为中文评审副本。从 `f15fda9` 继续实现；这是实现证据，不是部署批准，也不是完整任意时段重启验收。

## 范围与剩余门禁

- RR006：注入式、单次使用的 `RecoveryCoordinator` 负责有界本地协调、合并唤醒、公平工作、停止准入和可中断维护。类型化依赖重试留在循环内；意外故障向外传播。尚未替换既有生产生命周期。
- RR008：`RecoveryService.recover_scope` 一次获取一个证券，按冻结截止点过滤，重新检查排队跨日，并回读准确的已提交覆盖。缺失的历史日期仍保持缺失。组合模拟行情源/控制器/临时 SQLite 测试验证了临时故障、其他证券继续推进及随后恢复。
- 请求控制边界：本地校验在行情源 I/O 前终止工作时，`RequestNotStartedError` 保留现有恢复状态，不得将其当作成功的行情源响应。
- RR010：参考复用键包含计划类型/内容哈希、持久化版本、真实激活 revision/时间、交易日期和股票语义 revision。获取后及截止点准入前的检查拒绝已变化的捕获身份。既有评估身份与事务内校验不变。
- RR002：成对的详细状态/协议草案及本地 Web 修订。未改变 REST/WebSocket schema、生成类型或前端源码。草案评审不关闭 C0/C4。
- 用户在本轮另外批准显式 `RISK_ALERT` 按最新状态处理：追平后仍成立可进入候选发送，已解除抑制且保留历史，未知保持等待。成对恢复规格独立于评估器重复抑制记录了此规则。
- `notifications/recovery_eligibility.py` 以注入式纯策略实现该规则，输入为类型化激活计划/屏障；不保存抑制/屏障，不生成替代提醒意图，不调用通知渠道。调用方仍须建立权威当前事实并进行最终发送准入校验。
- 用户还批准旧版仅补发仍符合最新风险及目标持仓的提醒，已被替代的保留记录但不重放。成对规格记录了该批准及证据约束。只读评审发现：待卖出不一定更新风险行，盘中与官方收盘 `WAIT` 含义不同，恢复时的 `updated_at` 不能证明来源日期顺序。没有凭不完整证据启用旧版分类器。
- 用户随后批准：同一已证明的激活、跌破阶段和目标持仓内，相同 `RISK_EXIT_READY` 指令仅选择最新一条，较早记录保留审计。成对规格按官方来源日期排序，不按恢复写入时间排序。该替代规则已记录，供尚未完成的旧版交付集成使用，不声称已启用。
- `notifications/recovery_provenance.py` 新增只读来源读取器，而非交付分类器。它核对规范原始提醒/结果/认领、确定性发布 sequence 及激活/审计链，包括当前链末端、一致的 sequence 高水位及原始激活截止点。同哈希重新激活仍保留原始 revision。缺失、损坏或超出预算的历史返回类型化 `UNKNOWN`；真实数据库故障向外传播。全新会话校验保留调用方未提交/已缓存状态。激活事件/审计集合各自最多 1000 行；来源核验不使用七天截止限制。
- 全量运行暴露一项无关的 R32 测试依赖当天真实日期，而实际执行门禁只允许 2026-09-17。仅修正测试时钟：许可日期和过期日期用例继续执行真实门禁，并保留配置变更拒绝。执行脚本未改动，也未延长任何真实外发授权。

RR004 装配、漏收盘发现/重放、完整参考/历史获取、runtime-generation/重配置集成、原子交付资格与每计划风险屏障、默认生命周期接入、状态/UI 实现及进程重启验收仍未完成。未改变生产数据库/配置/证据，未访问真实行情源/通知渠道、安装依赖、部署或重启服务。本轮不声称 RR006/RR008/RR010 的全部验收条件已经完成。

## 测试先行与评审证据

| 产物 | 实际 RED | 实际 GREEN / 评审 |
|---|---|---|
| 协调器 | 初次收集因类不存在失败；随后单调等待上限测试因 `timeout=None` 失败；时间前跳测试抛出 `ValueError` | 12 个新测试；独立 Astra/xhigh 评审在三轮后结束 |
| 按范围获取 | 初始 9 个测试因 `recover_scope` 不存在失败 | 扩展为 20 个集成用例，包含组合恢复循环 |
| 本地取消 | 排队跨日重置先前临时错误退避：下次失败用了 30 秒而非 60 秒 | 回归现在保留 60 秒递进；已独立评审 |
| 参考身份 | 显式计划切换旧计划漏取涨跌停/历史、刷新接受重激活、截止点放行旧捕获：3 个行为失败 | 7 个新集成用例；独立评审在该切片内未发现实质问题 |
| 状态草案 | 独立评审发现协议预检前即可提交操作，以及显式 BUY/风险混合结果缺少逐规则有效性 | 两份语言稿均已修正；第二轮评审未发现新实质问题；不表示协议已实现 |
| 显式风险交付 | 首次收集因模块不存在失败；独立评审随后发现原始规则/动作不匹配返回 HOLD 而非 SUPPRESS；四个正常校验的事件用例复现偏差 | 50 个策略用例，包含规范复合条件三值语义；第二轮独立评审未发现剩余实质问题 |
| 旧版来源证明 | 16 个模块缺失失败；6 个链末端回归失败；1 个复用会话回归失败；7 个高水位/激活截止点回归失败 | 45 个集成用例；最终独立评审未发现剩余实质问题 |
| R32 测试时钟 | 原测试在 2026-09-21 失败；扩展许可/过期日期用例后，固定时钟之前为 1 失败、1 通过 | 整个 R32 文件 25 通过；独立评审确认执行门禁不变，测试时钟隔离 |

评审发现已逐项对照契约处理：主动让出事件循环、读取快照前清除唤醒、单调维护上限、单次使用所有权、包含配置变化的需求 revision、时间前跳重试归一化及取消不计成功，均属于有效可执行问题并已处理。取消协调器不代表等待行情线程退出；生命周期仍须在关闭存储前等待控制器清理。沿用用户此前选择，未增加额外跨模型评审。

编码子任务使用 `gpt-6-astra` / `high`；协议草案和独立边界评审使用 `gpt-6-astra` / `xhigh`。这些子任务设置不能证明父任务实际模型/强度。

## 已执行验证

在 `trade-plan-monitor` 中运行：

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_recovery_coordinator.py tests/unit/test_runtime_reconciliation.py -q --tb=short` | 24 通过 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_coverage.py -q --tb=short` | 20 通过，2.44 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_activation_fences.py tests/integration/test_production_semantic_gate.py tests/unit/test_r17_failure_diagnostics.py -q` | 编码 agent：40 通过，8.31 秒；一项既有 Starlette 警告 |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_recovery_delivery_eligibility.py tests/unit/test_explicit_rules.py tests/unit/test_notification_outbox.py -q` | 编码 agent：评审修正后 120 通过，0.76 秒；评审者独立重跑全部 50 个策略用例通过 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_provenance.py tests/unit/test_notification_outbox.py tests/integration/test_live_monitor_projection_migration.py -q --tb=short` | 编码 agent：最终评审修正后 112 通过，7.45 秒，其中包含 45 个新来源用例 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_r32_ai_transient_acceptance.py -q --tb=short` | 测试时钟修正后 25 通过、1 项既有警告，2.91 秒 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | 既有 OpenAPI 快照与生成的前端类型一致 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short` | 3006 通过、5 失败、1 跳过、4 个 live 排除、1 项既有警告；3002.35 秒 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 最终功能回归：3095 通过、4 项已知失败、1 跳过、4 个 live 排除、1 项既有警告；441.10 秒 |

全量门禁未通过。其中四项失败与 `2026-09-21-runtime-recovery-foundations.md` 的既有记录一致：规范指数头更新时间、待处理收盘的指数错误参考健康度、行情源 TIMEOUT 与 TRANSIENT 差异，以及 R14 模拟载荷被 temperature 校验拒绝。新增 `test_r32_execution_snapshot_detects_config_change` 失败已定位为真实日期依赖：脚本和测试起初均与 HEAD 一致，来自 `7df47b78`。仅修改测试后，其整个文件通过；上方全量数字仍保留修正前的实际结果。没有为宣称成功而删除、跳过或弱化失败测试；跳过项是既有 Windows/POSIX 所有权边界。

全量离线运行在新增显式风险策略和旧版来源测试文件之前完成收集；对应 50 和 45 个用例由单独记录的定向运行及最终功能回归覆盖。最终运行包含 R32 时钟修正及当前所有新测试，但不重复运行已在全量运行中通过且未改动的重型回测验收文件。剩余四项失败均与既有记录一致；门禁仍未通过。空白检查通过。对说明性占位符翻译及成对文档路径归一化后，成对文档的标题数量与技术字面量一致；runtime-status 的四个围栏 JSON 示例在两种语言中完全相同。最终高置信度秘密模式扫描覆盖全部 22 个修改文件，未发现匹配。这是限定范围的卫生检查，不是凭证审计。

## 修改范围

`runtime/reconciliation.py`、`runtime/recovery.py`、`runtime/request_control.py`、`runtime/production.py`、新增 `notifications/recovery_eligibility.py` 和 `notifications/recovery_provenance.py`；五个新增定向测试文件及隔离的 R32 测试时钟修正；成对的 runtime-recovery/runtime-status/本地 Web 规格、任务表与本报告。该增量不包含隐藏的生成契约或 UI 修改。
