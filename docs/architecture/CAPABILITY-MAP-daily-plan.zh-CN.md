# 能力地图：daily-plan

英文版本为 canonical；`CAPABILITY-MAP-daily-plan.zh-CN.md` 是中文审阅副本。日期：2026-10-02。状态：监控与显式整手模拟已实现并通过当前离线验收。实际来源计划仍需完整参数、人工审核和显式启用。

| Module ID | 职责及契约章节 | 依赖 |
|---|---|---|
| `daily-plan-contract` | 未发布Schema4有限条件、完整100股模拟与兼容边界；[规格](../specifications/monitoring/SPEC-daily-plan.md) D01–D05。 | 既有 `plan-domain`、`market-data` |
| `daily-plan-monitor` | 持久确认/窗口、普通/严重技术风险、提醒及用户触发原子模拟交易；隔离的最小daily模拟持仓/T+1；D06–D10。 | `daily-plan-contract`、既有 `strategy-state`、`monitor-runtime`、`notification-outbox` |
| `daily-plan-review` | V7忠实候选、来源映射、人工审核/启用、技术/运行证据及独立显式模拟动作；D11–D13。 | `daily-plan-contract`、`daily-plan-monitor`、既有 `ai-plan-drafting`、`local-web` |

模块依赖顺序为 `daily-plan-contract` → `daily-plan-monitor` → `daily-plan-review`，稳定module ID不变。既有daily记录与unit of work承载隔离模拟状态；交易不写共享真实/旧持仓表。接口和行为以[规格](../specifications/monitoring/SPEC-daily-plan.zh-CN.md)为准，完成记录集中于[任务](../../tasks/daily-plan-todo.zh-CN.md)，实际验收见[最终验证](../verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)。

提醒不改仓；显式且合格的模拟为完整100股倍数的一笔事务。券商订单报告、部分/未知订单、占额及客户分配已删除。保留防重、T+1、CORE保护、计划最大仓位、独立风险cause、官方收盘恢复及QFQ/日历保护。

基本面/公告只在生成计划时由用户审核，保留可见非监控背景，不参与技术条件或运行阻断。可交易/停牌继续作为运行输入。新增大盘指数逻辑暂缓，既有指数行为、Schema1/2/3、prompt v1–v6、ta-v1及共享旧库存API保留。旧开发证据明确不支持，不自动转换成模拟成功。2026-10-01验证只证明此前范围；当前实现未加入券商下单或自动交易。
