# 能力地图：daily-plan

英文版本为 canonical；`CAPABILITY-MAP-daily-plan.zh-CN.md` 是中文审阅副本。日期：2026-10-02。用户已授权仅模拟交易清理，实现按本双语设计继续，无需再次批准。不批准或启用任何实际来源计划。

| Module ID | 职责及契约章节 | 依赖 |
|---|---|---|
| `daily-plan-contract` | 未发布Schema4有限条件、完整100股模拟与兼容边界；[规格](../specifications/monitoring/SPEC-daily-plan.md) D01–D05。 | 既有 `plan-domain`、`market-data` |
| `daily-plan-monitor` | 持久确认/窗口、普通/严重技术风险、提醒及用户触发原子模拟交易；隔离的最小daily模拟持仓/T+1；D06–D10。 | `daily-plan-contract`、既有 `strategy-state`、`monitor-runtime`、`notification-outbox` |
| `daily-plan-review` | V7忠实候选、来源映射、人工审核/启用、技术/运行证据及独立显式模拟动作；D11–D13。 | `daily-plan-contract`、`daily-plan-monitor`、既有 `ai-plan-drafting`、`local-web` |

顺序：`daily-plan-contract` → `daily-plan-monitor` → `daily-plan-review`。稳定module ID不变。审核可展示缺项候选，但宣称支持启用需完整生产链路。既有通用daily记录及unit of work承载最小模拟状态，不新增券商服务、订单实体或迁移框架。模拟交易绝不写共享真实/旧持仓表。接口由规格中的提供方章节定义。[计划](../../tasks/daily-plan-plan.md)、[任务](../../tasks/daily-plan-todo.md)及[清理交接](../../tasks/2026-10-02-daily-plan-simulation-cleanup.md)定义当前工作。

在API/领域/状态/运行/UI/测试中删除本轮daily券商报告、外部ID、部分执行、PENDING/CANCELLED/UNKNOWN订单跟踪、占额及客户库存分配。只改名或隐藏表单不算完成。提醒发送不改仓，用户显式且合格的模拟为完整100股倍数的一笔事务。保留防重、T+1、CORE保护、最大仓位、不同风险cause、官方收盘恢复及QFQ/日历保护。

原始 `../docs/TradingAgents/reports/新提示词.txt` 不变。基本面/公告仅在生成计划时审核，保留可见非监控背景，不能以技术事实或执行阻断回归。可交易/停牌仍为运行输入。指数行为、旧Schema1/2/3、prompt v1–v6、ta-v1及共享旧库存API不变。未发布Schema4/v7可原地收紧；旧开发证据保留并明确不支持，不转换成模拟成功。使用离线夹具/临时数据库。不接券商、不自动交易、不调实时provider、不读写生产数据库、不commit/push/deploy。2026-10-01验证为历史，不批准新范围。
