# 能力地图：Trade Plan Monitor

## 产品边界

本地单用户应用绑定 `127.0.0.1`，最多监控10个 A 股代码。单一 `/plans` 工作台负责 Schema 5 提取、人工审核、明确启用、日线/五分钟混合监测及明确整单模拟。基本面仅在生成计划时审核。提醒和已读绝不改变库存。详见[单一交易计划流程](../specifications/monitoring/SPEC-unified-plan.zh-CN.md)。

## 维护模块

| Module ID | 职责 | 依赖 |
|---|---|---|
| `plan-domain`, `ai-plan-drafting` | 当前类型化计划、原文证据、遗漏与准确人工审核；`plan-extract-v8` 仅负责提取 | `local-web`, `strategy-state` |
| `market-data`, `index-identity`, `index-data` | 已认证归一化、日历、正式日线/完整分钟证据及共用参考指数事实 | `provider-contract` |
| `decision-engine` | 纯函数、精确、原文定义的条件求值；当前与冻结重放契约分离 | `plan-domain`, `market-data` |
| `strategy-state`, `live-state-store` | 不可变计划/审核身份、限定范围事实、完成证明及原子隔离模拟记账 | `decision-engine` |
| `monitor-runtime`, `live-market-runtime`, `live-index-runtime` | 单一自有调度器、有界采集、持久恢复、启用栅栏及真实进展 | `market-data`, `strategy-state` |
| `notification-outbox` | 事务性提醒身份、发送时资格及独立已读 | `strategy-state`, `monitor-runtime` |
| `projection-availability`, `web-availability`, `local-web` | 权威读取、监控协议 `2`、同源命令及无障碍 Vue 展示 | `strategy-state`, `monitor-runtime` |
| `plan-index-conditions`, `monitor-index-view` | 冻结计划专属指数解释与当前共用指数展示；不新增当前指数判断 | `index-data` |
| `backtest-data`, `backtest-engine`, `backtest-results` | 冻结数据集、无未来数据的确定性研究及完整性校验的结果发布 | 冻结 `plan-domain`, `market-data` |
| `backtest-jobs`, `backtest-api`, `backtest-web` | 单一持久工作槽、类型化资源及独立研究工作台 | `backtest-data`, `backtest-engine`, `backtest-results`, `local-web` |

## 开发边界

领域逻辑放在 `src/trade_plan_monitor`；HTTP 适配与 Vue 展示后端权威结果。行情 I/O 位于短 SQLite 事务之外。当前模拟库存、历史真实持仓记录及回测行情/结果库保持隔离。冻结 Schema 1–4 字节/哈希仅被读取或重放，不静默转换成活动 Schema 5 计划。

按依赖顺序实现：契约与审核 → 归一化证据 → 纯求值 → 原子持久化 → 自有运行时与出站箱 → 投影/API → Vue。遵循相应现行规格与确定性测试。真实供应商调用、用户数据库迁移及部署仍需单独授权；本地验收不能证明实时可用性。
