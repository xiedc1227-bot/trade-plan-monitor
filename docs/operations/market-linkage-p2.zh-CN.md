# 操作说明：market-linkage-p2

[英文规范版](market-linkage-p2.md) · [规格](../specifications/monitoring/SPEC-market-linkage-p2.zh-CN.md) · [验收证据](../verification/2026-10-26-market-linkage-p2.zh-CN.md)。

## MLP2-O01 — 准备与审核

使用 `/plans` 和 `plan-extract-v11`，仅复制交易提示词的 A。A 必须明确定义 Schema 8 / condition-plan-v4、完整 P1 大盘政策、`pretrade-policy-v1`、数量与费用政策。B 是研究解释，不产生执行权限。原文 G01–G14 对照表保留在规格中。

`ATR_RATIO_TIERS` 必须提供 `base_qty`、`metric=ATR14_OVER_CLOSE` 及 1–10 个连续 `[lower, upper)` 档位，覆盖零至无穷（末档 `upper=null`）。系数须非递增且在 0 到 1 之间，小数使用字符串。`quantity_policy.mode=DERIVED_MARKET_FACTOR` 不含 `base_quantity`；`FIXED_Q0` 使用现有 `MARKET_FACTOR` 数量政策。混用会阻断审核。

候选缺失值保留为 null，阻断可执行审核。服务器不补数量、档位、零费用、有效日期、数字盈利门槛或 BROKEN_STRONG 数量。人工补充走现有明确、绑定来源的审核流程；原文或政策变化须重新审核准确内容。

`NONE` 不含费用字段。`PREVIEW_ONLY` 显示估算，不否决交易。`REQUIRED` 至少增加一个明确非空门槛，按 ALL 组合，以包含等号的 `>=` 比较。两个估算模式均要求准确适用证券、费用表 ID／版本、有效日期、来源摘录、佣金／最低佣金、费用项目及包含关系、每股滑点。`classification=ESTIMATE` 不证明当前交易所或券商费率；P2 不提供生产费用表。

明确目标价须位于审核压力区间内，并遵守端点是否包含的定义，风险价须等于审核风险线。PRESSURE/RISK 各需 PRICE_STRUCTURE 加另一独立维度；MA20 与 BOLL_MIDDLE 均计为 TREND。这里检查来源完整性，不自动判断主观价位是否经济合理。

## MLP2-O02 — 数量、估算与执行

正式日线确认时，使用已准入的 `daily-ta-v2` ATR14 和同一复权收盘价。先将 `base_qty * multiplier` 向下取整到官方申报网格与 100 股模拟网格的交集，得到 Q0，再应用原大盘系数。基准1000 ×0.5 得 Q0=500，普通 WEAK 授权200。基准100 ×0.5 无合法 Q0，不能转入例外。基准200 ×0.5 得 Q0=100，在 P1 条件成立时 WEAK_MINIMUM 可申请恰好100。

确认时冻结 Q0 和政策依据。后续报价对同一完整数量重算费用，不改量。REQUIRED 失败阻断 BUY，恢复仅能在原执行窗口内重新取得资格；审核假设变化会使旧权限失效。风险退出绕过 BUY 费用门槛；实际成交／资金与研究估算分开。

各费用项目向上取整为整数分；佣金采用明确的最低值，已包含费用不重复收费。数量 q、买价 e、目标 t、风险价 z、滑点 sb/ss：`B=q*(e+sb)+buy_fees`，`T=q*(t-ss)-target_fees`，`Z=q*(z-ss)-risk_fees`，收益=`T-B`，损失=`B-Z`。门槛比值采用精确分数。往返成本含买入／目标卖出费用与滑点，价差为 cost/q。无效价格、费用表过期或必要数据不可用得到 UNKNOWN；只有 REQUIRED 将其转为否决。

WEAK_MINIMUM 保持恰好为兼容最小量。BROKEN_STRONG 的人工数量框初始为空，填写不超过 Q0 和当前容量的合法整笔 Qe。查看估算后，明确批准这次机会，再单独确认整笔模拟。批准和预览不改变库存；单次消耗、撤销、原期限及修正失效仍有效，不支持部分模拟。

## MLP2-O03 — 只读 API 与通知

`POST /api/v1/plan-economics-previews` 接受 `planVersionId`、`ruleId`、可选 `occurrenceId` 和 `proposedQuantity`。`occurrenceId` 是服务器例外 `candidate_id`，不是信号 ID 或序号；预览例外时必填。仅 BROKEN_STRONG 接受建议数量，其余数量取服务器依据。客户端报价、费用或批准字段被拒绝。接口沿用本地 API 准入，不写入预览、候选、批准或交易。

响应含 `computedAt`、`planVersionId`、`ruleId`、`quantity`、`evidence`（`p2-pretrade-evidence-v1`）、`economics`（`p2-economics-v1`）和 `authorityGranted=false`。依据缺失、当前过期或不匹配返回409；无效请求字段返回422。来源、启用、仓位或行情依据变化后刷新运行状态。成功估算不是批准凭证；模拟在自己的受保护事务中重新核验。

界面展示冻结数量、当前估算、费用项目与门槛阻断；当前上下文变化后丢弃迟到的预览响应。通知标明对应规则的费用模式和独立批准／执行要求，发送时检查会抑制过期的可操作提醒。

## MLP2-O04 — 冻结研究与兼容

Schema 8 研究使用 `backtest-run-v9`、冻结计划／费用表、明确例外事件及独立模拟操作。来源区分 RECORDED_LOCAL 与 RESEARCH_SCENARIO。同一政策与运行服务在隔离临时状态中执行，不读取当前供应商费用表或本地批准；接收／可用时间边界防止未来依据授权过去决策。P2 信号报告保留数量证据，解析共用联动及交易前依据引用后再执行完整信号准入校验；现有 Schema 7 压缩表示不变。

审核内容使用 `plan-review-content-v5`，已消费依据连续性使用 `p2-consumed-v1`。Schema 1–7 文档、哈希和权限保持原表示。存储增加可选版本化 JSON 字段，无需 SQL 结构迁移或历史改写。实际降级前备份：旧读取器必须拒绝执行 Schema 8，并保留原记录；不能将 Schema 8 改标签为 Schema 7 强行兼容。

## MLP2-O05 — 边界与本地验证

金额上限、自动构建仓位、券商订单／部分成交、非100股模拟、事件相对期限发现、自动基本面／公告判断、未验证的市场／供应商覆盖，以及日线联动的五分钟确认仍不在 P2 内。原文必要的不支持约束会阻断导入，不能删除或换成方便的默认值；人工技术事实仍限于现有范围。

使用[任务检查 V01–V08](../../tasks/market-linkage-p2.zh-CN.md)及实际验收报告。后端目录分进程运行，因为现有单元／集成文件有重复模块名；仅排除 live 测试。本地证据使用合成行情、费用和临时数据库，不证明实时服务可用性、当前费率、真实成交或部署完成。
