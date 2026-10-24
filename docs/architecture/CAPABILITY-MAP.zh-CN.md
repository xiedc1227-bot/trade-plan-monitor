# 能力地图：Trade Plan Monitor

## 产品边界

本地单用户应用绑定 `127.0.0.1`，最多监控10个 A 股代码。单一 `/plans` 工作台负责 Schema 5 固定计划、Schema 6 联动计划和 Schema 7 逐机会例外计划的提取、人工审核、明确启用、日线/五分钟混合监测及明确整单模拟。联动使用正式日线证据确认，下一交易所交易日执行；例外批准与执行相互独立。基本面仅在生成计划时审核。提醒和已读绝不改变库存。详见[单一交易计划流程](../specifications/monitoring/SPEC-unified-plan.zh-CN.md)。

## 维护模块

| Module ID | 职责 | 依赖 |
|---|---|---|
| `plan-domain`, `ai-plan-drafting` | 当前类型化计划、原文证据、遗漏与准确人工审核；`plan-extract-v10` 仅负责提取 | `local-web`, `strategy-state` |
| `market-data`, `index-identity`, `index-data` | 已认证归一化、日历、正式日线/完整分钟证据及共用参考指数事实 | `provider-contract` |
| `decision-engine` | 纯函数、精确、原文定义的条件求值；当前与冻结重放契约分离 | `plan-domain`, `market-data` |
| `market-regime`, `relative-strength` | 四态日线分类及对齐的5/20交易日个股／指数比较 | `index-data`, `market-data` |
| `confirmation-selection`, `quantity-policy` | 绑定来源的S0/S1/S2、官方数量规则及普通路径向下取整；Schema 7 WEAK_MINIMUM恰好最小量／BROKEN_STRONG人工明示数量，每个机会只冻结一次 | `market-regime`, `relative-strength`, `strategy-state` |
| `market-linkage-workflow` | Schema 6/7审核、独立的机会预览／批准／拒绝／撤销、原子消耗、共享运行／冻结回放、来源更正防护及来源标记；[P0操作](../operations/market-linkage-p0.zh-CN.md)、[P1操作](../operations/market-linkage-p1.zh-CN.md) | 全部四个联动模块 |
| `strategy-state`, `live-state-store` | 不可变计划/审核身份、限定范围事实、完成证明及原子隔离模拟记账 | `decision-engine` |
| `monitor-runtime`, `live-market-runtime`, `live-index-runtime` | 单一自有调度器、有界采集、持久恢复、启用栅栏及真实进展 | `market-data`, `strategy-state` |
| `notification-outbox` | 事务性提醒身份、发送时资格及独立已读 | `strategy-state`, `monitor-runtime` |
| `projection-availability`, `web-availability`, `local-web` | 权威读取、监控协议 `2`、同源命令及无障碍 Vue 展示 | `strategy-state`, `monitor-runtime` |
| `plan-index-conditions`, `monitor-index-view` | 历史计划专属指数解释与当前共用指数展示；Schema 6判断归属 `market-regime` | `index-data` |
| `backtest-data`, `backtest-engine`, `backtest-results` | 冻结数据集、无未来数据的确定性研究及完整性校验的结果发布 | 冻结 `plan-domain`, `market-data` |
| `backtest-jobs`, `backtest-api`, `backtest-web` | 单一持久工作槽、类型化资源及独立研究工作台 | `backtest-data`, `backtest-engine`, `backtest-results`, `local-web` |

## 开发边界

[market-linkage-p1](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md) 在三个既有联动模块中增加原文许可的 `WEAK_MINIMUM`、`BROKEN_STRONG` 人工授权。Schema 6 保留 `BLOCK_P1`，只有明确的 Schema 7 才能申请机会批准。冻结研究要求明确授权事件及独立操作，绝不读取当前本地批准。[有序任务](../../tasks/market-linkage-p1.zh-CN.md)与[验收报告](../verification/2026-10-24-market-linkage-p1.zh-CN.md)记录已执行检查点及全项目验收状态。

领域逻辑放在 `src/trade_plan_monitor`；HTTP 适配与 Vue 展示后端权威结果。行情 I/O 位于短 SQLite 事务之外。当前模拟库存、历史真实持仓记录及回测行情/结果库保持隔离。冻结 Schema 1–4 字节/哈希仅被读取或重放，不静默转换成活动 Schema 5/6/7 计划。既有 Schema 5/6 字节/哈希保持不变。

按依赖顺序实现：契约与审核 → 归一化证据 → 纯求值 → 原子持久化 → 自有运行时与出站箱 → 投影/API → Vue。遵循相应现行规格与确定性测试。真实供应商调用、用户数据库迁移及部署仍需单独授权；本地验收不能证明实时可用性。
