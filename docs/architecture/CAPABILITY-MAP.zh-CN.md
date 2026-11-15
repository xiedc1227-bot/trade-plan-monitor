# 能力地图：Trade Plan Monitor

## 产品边界

本地单用户应用绑定 `127.0.0.1`，最多监控10个 A 股代码。单一 `/plans` 工作台负责 Schema 5 固定计划、Schema 6 联动计划、Schema 7 逐机会例外计划、Schema 8 交易前政策及 Schema9 金额上限的提取、人工审核、明确启用、日线/五分钟混合监测及明确整单模拟。联动使用正式日线证据确认，下一交易所交易日执行；例外批准与执行相互独立。基本面仅在生成计划时审核。提醒和已读绝不改变库存。详见[单一交易计划流程](../specifications/monitoring/SPEC-unified-plan.zh-CN.md)。

## 维护模块

| Module ID | 职责 | 依赖 |
|---|---|---|
| `plan-domain`, `ai-plan-drafting` | 当前类型化计划、原文证据、遗漏与准确人工审核；`plan-extract-v12` 仅负责提取 | `local-web`, `strategy-state` |
| `source-condition-coverage` | 已交付工程：原文义务／关系、遗漏阻断及准确当前审核／操作绑定；历史字节及审核保持分离 | `plan-domain`, `ai-plan-drafting`, `strategy-state` |
| `extraction-v12-acceptance` | 语料／真值、独立评分及准确版本真实供应商签收；语料验收仍待完成 | `source-condition-coverage`, `ai-plan-drafting` |
| `monitor-readiness` | 已交付工程：逐规则只读解释当前覆盖／审核、运行、数据、持仓／资金及通知；不授予权限、不触发采集 | `source-condition-coverage`, `strategy-state`, `monitor-runtime`, `market-data`, `notification-outbox` |
| `market-data`, `index-identity`, `index-data` | 已认证归一化、日历、正式日线/完整分钟证据及共用参考指数事实 | `provider-contract` |
| `decision-engine` | 纯函数、精确、原文定义的条件求值；当前与冻结重放契约分离 | `plan-domain`, `market-data` |
| `market-regime`, `relative-strength` | 四态日线分类及对齐的5/20交易日个股／指数比较 | `index-data`, `market-data` |
| `confirmation-selection`, `quantity-policy` | 绑定来源的S0/S1/S2、官方数量规则及普通路径向下取整；Schema 7 WEAK_MINIMUM恰好最小量／BROKEN_STRONG人工明示数量，每个机会只冻结一次 | `market-regime`, `relative-strength`, `strategy-state` |
| `market-linkage-workflow` | Schema 6/7审核、独立的机会预览／批准／拒绝／撤销、原子消耗、共享运行／冻结回放、来源更正防护及来源标记；[P0操作](../operations/market-linkage-p0.zh-CN.md)、[P1操作](../operations/market-linkage-p1.zh-CN.md) | 全部四个联动模块 |
| `p3-capital-policy` | Schema9 纯金额／并用成本及市值限制、明确来源含义与审核身份 | `plan-domain`, `ai-plan-drafting` |
| `p3-capital-ledger` | 独立审核的完整批次开仓／校正、保留成本及实际分配原子连续性 | `p3-capital-policy`, `strategy-state` |
| `p3-capital-gate` | 准确整笔成本／市值条件，已知无股数上限与未知容量，共享费用算术 | `p3-capital-policy`, `p3-capital-ledger`, `p2-trade-economics` |
| `p3-capital-workflow` | 共用当前／例外／冻结防护，有界 API／界面、发送时校验与报告引用校验 | 全部三个 P3 模块，既有 P0/P1/P2 流程 |
| `strategy-state`, `live-state-store` | 不可变计划/审核身份、限定范围事实、完成证明及原子隔离模拟记账 | `decision-engine` |
| `monitor-runtime`, `live-market-runtime`, `live-index-runtime` | 单一自有调度器、有界采集、持久恢复、启用栅栏及真实进展 | `market-data`, `strategy-state` |
| `notification-outbox` | 事务性提醒身份、发送时资格及独立已读 | `strategy-state`, `monitor-runtime` |
| `projection-availability`, `web-availability`, `local-web` | 权威读取、监控协议 `2`、同源命令及无障碍 Vue 展示 | `strategy-state`, `monitor-runtime` |
| `plan-index-conditions`, `monitor-index-view` | 历史计划专属指数解释与当前共用指数展示；Schema 6判断归属 `market-regime` | `index-data` |
| `backtest-data`, `backtest-engine`, `backtest-results` | 冻结数据集、无未来数据的确定性研究及完整性校验的结果发布 | 冻结 `plan-domain`, `market-data` |
| `backtest-jobs`, `backtest-api`, `backtest-web` | 单一持久工作槽、类型化资源及独立研究工作台 | `backtest-data`, `backtest-engine`, `backtest-results`, `local-web` |

## 开发边界

[market-linkage-p1](../specifications/monitoring/SPEC-market-linkage-p1.zh-CN.md) 在三个既有联动模块中增加原文许可的 `WEAK_MINIMUM`、`BROKEN_STRONG` 人工授权。Schema 6 保留 `BLOCK_P1`，只有明确的 Schema 7/8/9 才能申请机会批准。冻结研究要求明确授权事件及独立操作，绝不读取当前本地批准。[有序任务](../../tasks/market-linkage-p1.zh-CN.md)与[验收报告](../verification/2026-10-24-market-linkage-p1.zh-CN.md)记录已执行检查点及全项目验收状态。

领域逻辑放在 `src/trade_plan_monitor`；HTTP 适配与 Vue 展示后端权威结果。行情 I/O 位于短 SQLite 事务之外。当前模拟库存、历史真实持仓记录及回测行情/结果库保持隔离。冻结 Schema 1–4 字节/哈希仅被读取或重放，不静默转换成活动 Schema 5/6/7/8/9 计划。既有 Schema 5/6/7 字节/哈希保持不变。

按依赖顺序实现：契约与审核 → 归一化证据 → 纯求值 → 原子持久化 → 自有运行时与出站箱 → 投影/API → Vue。遵循相应现行规格与确定性测试。真实供应商调用、用户数据库迁移及部署仍需单独授权；本地验收不能证明实时可用性。

P2 增加 `p2-source-policy`、`p2-volatility-sizing`、`p2-trade-economics` 和 `p2-pretrade-workflow`：来源绑定的档位先于大盘系数得出 Q0，版本化估算和可选明确 BUY 门槛在运行及 backtest-run-v9 中共用。冻结数量、当前报价门槛复核、只读预览、逐机会批准和独立整笔模拟各有职责。参见 [P2 操作说明](../operations/market-linkage-p2.zh-CN.md)和 [G01–G14 边界](../specifications/monitoring/SPEC-market-linkage-p2.zh-CN.md)。真实／部分券商成交、自动基本面及日线联动五分钟确认仍在范围外。P3 仅扩展隔离、单证券模拟金额上限。

P3 使用 backtest-run-v10 及显式预算开仓／授权／操作输入，保留研究现金／盈亏隔离。不选择 Q0、不缩整笔数量、不推断开仓成本、不隐式批准。BUY 金额失败不阻挡实际技术风险 SELL。参见 [P3 操作说明](../operations/market-linkage-p3.zh-CN.md)、[G01–G14 剩余边界](../specifications/monitoring/SPEC-market-linkage-p3.zh-CN.md)及[实际验收状态](../verification/2026-10-26-market-linkage-p3.zh-CN.md)。全项目验收以报告为准，局部阶段不认证真实供应商、真实账户、迁移或部署。

PMA扩展既有原文审核及运行投影，参见[操作指南](../operations/plan-monitor-assurance.zh-CN.md)、[覆盖契约](../specifications/monitoring/SPEC-source-condition-coverage.zh-CN.md)及[就绪契约](../specifications/monitoring/SPEC-monitor-readiness.zh-CN.md)。完整的已审核定义可以反复求值；澄清、必要事实及批准仍须明确完成。已验证的H04登记仅限Schema5 ordinary REVIEWED_FACT/TRADE_DATE准确叶子。账户上下文识别不证明账户事实真实。缺值草稿就绪仅接受原生校验合法、未审核、未启用且owner完整唯一的Schema5草稿；Schema6–9不完整草稿及owner缺失／重复的Schema5草稿仍不可用／503。历史语义通过不能提供当前覆盖或执行资格。

[完整冻结回归仍为FAILED](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r140--完整冻结回归保留七项失败)，[有界草稿就绪](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r141--有界缺值草稿就绪查询不缩小规则范围)及[完整来源浏览器修复](../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r142--完整来源浏览器正例保留原计划阻断)属于后续定向工程证据。完整T22/A12、F083／原始03/04／C05及最终验收仍开放，真实提取为0/48。持续入场前禁买取消仍不支持。[唯一一次安装审计](../verification/plan-readiness-installation.zh-CN.md)在打开SQLite前停止，实际事实未采集，空数组不能证明没有计划。工程交付不认证语料准确率、安装就绪、用户数据库迁移或部署。
