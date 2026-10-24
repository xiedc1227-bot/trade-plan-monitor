# 规格：market-linkage-p0

状态：APPROVED — 用户于2026-10-24批准六项决策及规格，并明确授权按任务清单实施。实施进度按验收记录；未完成任务不代表已交付。
实施证据维护在[验收报告](../../verification/2026-10-24-market-linkage-p0.zh-CN.md)。
中文审核副本；[英文正式规格](SPEC-market-linkage-p0.md)。[实施任务](../../../tasks/market-linkage-p0.zh-CN.md)。

## MLP01 — 目标与授权

让通用交易计划提示词中的普通大盘联动低吸规则能够在单一 `/plans` 流程中表达、审核、监测和回放。本规格覆盖已批准的P0实施与本地验收。实时部署和用户数据库迁移不在本次范围内。

依据：[README提示词](../../../README.zh-CN.md#generic-trade-plan-prompt)、[当前流程](SPEC-unified-plan.zh-CN.md)、[指数身份](SPEC-index-identity.zh-CN.md)、[指数事实](SPEC-index-data.zh-CN.md)、[历史指数条件](SPEC-plan-index-conditions.zh-CN.md)。已有指数事实和历史 Schema 2 条件可复用，但不证明当前 Schema 5 已支持联动。不得覆盖其他进行中的计划或任务清单。

## MLP02 — 能力地图与实施顺序

| Module ID | 范围／规格 | 依赖 |
| --- | --- | --- |
| `market-regime` | 精确板块指数证据和四类状态；[规格](SPEC-market-regime.zh-CN.md) | 现有指数身份／数据与日历 |
| `relative-strength` | 对齐个股／指数5／20交易日收益及个股MA20；[规格](SPEC-relative-strength.zh-CN.md) | `market-regime` 证据契约、现有个股日线 |
| `confirmation-selection` | 有来源的S0／S1／S2组合与唯一选中路径；[规格](SPEC-confirmation-selection.zh-CN.md) | `market-regime`、`relative-strength`、现有条件 |
| `quantity-policy` | Q0、折减、合法数量及不可变信号数量；[规格](SPEC-quantity-policy.zh-CN.md) | `confirmation-selection`、现有库存／生命周期 |
| `market-linkage-workflow` | 提取、审核、持久化、运行时、界面与回放；[规格](SPEC-market-linkage-workflow.zh-CN.md) | 以上四个模块 |

按表中顺序构建，每个模块同步接入提取／审核并做针对性验证。这些是逻辑边界，不是独立服务或新产品工作台。P0-5贯穿所有阶段；完整集成属于发布门槛。

## MLP03 — 范围与排除项

P0为TACTICAL中按日线确认的普通BUY规则增加明确选择的大盘政策。既有非联动条件、普通SELL、技术风险退出、提醒与五分钟监测保持原义。P0不增加指数驱动SELL或清仓。既有更高优先级风险继续阻止买入。大盘改善本身不产生买入信号。

必须完整表达提示词大盘表的六行。非例外路径可成为可操作方案；弱市最低申报量例外、明显破坏但个股强势例外均明确保留为 `P1_EXCEPTION_REQUIRED`，授权数量为零。不得将它们启用为自动可执行例外、删除或改成人工事实。P0允许审核含这些忠实表达的阻断路径的计划，同时启用其中普通路径。在能力实现并验收前，当前提示词的A阻断行为继续适用。

排除项：P1例外审批、任意公式、按波动自动推断Q0、普通买入建立CORE、非100股模拟交易、券商接入、基本面监测、自动修改风险线、额外供应商及默认认证所有板块。现有不支持的供应商／日历范围继续阻断；尤其BSE映射本身不代表BSE指数或历史日历可用。

## MLP04 — 审核决策

| ID | 建议决策 | 原因／影响 |
| --- | --- | --- |
| MLP-D01 | 新联动计划使用 `schema_version=6`、`execution_mode=CONDITION_PLAN`、`execution_version=condition-plan-v2`；继续原样支持既有 Schema 5 计划 | 动态数量改变执行语义，需保留历史字节／哈希并避免静默转换。内部版本不成为界面选择器。 |
| MLP-D02 | 联动仅使用准确交易日D的完整正式日线确认，下一交易所交易日执行 | 避免盘中状态抖动与未来数据。既有固定五分钟规则继续支持。 |
| MLP-D03 | 个股／指数使用相同计划交易日上的全部观测；停牌／缺失个股日不填充 | 相对强弱未知不授予豁免。这是保守选择，可能减少可判断日期。 |
| MLP-D04 | 确认时先计算大盘调整后的完整数量，再检查剩余额度；额度不足整笔阻断 | 保留现有原子模拟，不自动按额度缩量或以部分数量替代。 |
| MLP-D05 | 对单个信号固定选中路径和数量；后续证据变化使权限失效，不调整数量 | 避免自动扩量、重复交易和静默改变策略。新信号必须满足已审核独立信号政策；原有效信号不额外延迟。 |
| MLP-D06 | P0不批准两类强势例外，展示资格证据并保持P1阻断 | 无需虚构人工豁免流程即可交付普通路径。 |

六项决策与实施均已明确批准。策略变化仍须同步中英文规格修订。

## MLP05 — 共用契约

联动规则使用 `quantity_policy` 替代固定 `quantity`；固定规则保留 `quantity`，两种形式互斥。联动BUY还包含 `market_policy` 和明确的基础 `condition`（S0）。含联动规则的计划包含由服务端派生的 `reference_market`，复用 `AUTO_BOARD` 与 `board-index-map-v1`；提交身份不匹配时拒绝。

`market_policy.policy_version=market-linkage-v1`、`market_policy.base_confirmation=S0`、`market_policy.exception_policy=BLOCK_P1` 标识完整展开且绑定来源的决策表，不是隐藏的默认交易规则。阈值、路径谓词、数量系数与确认组均须可追溯到原文或已审核补充。仅有S0／S1／S2名称而没有定义，仍属未解决。

各模块输出共用 `decision_session`、`evidence_cutoff`、`source_hashes`、`formula_version`、操作数、结果与原因。最终投影包含 `regime`、`relative_strength`、`selected_confirmation`、`base_quantity`、`quantity_factor`、`candidate_quantity`、`authorized_quantity`、`blocked_reasons`，有信号时包含 `signal_id`。无法计算时 `candidate_quantity` 可为空；`authorized_quantity=0` 表示没有交易权限，绝不是零数量普通动作。

保留深度4、总条件叶子50的限制；校验展开后的S0／S1／S2，不静默删除子条件。生成时的重复只能在证据与来源绑定等价时归一化。不建议新增依赖。修改代码前须明确持久证据、投影及哈希版本；旧序列化器不得被注入新的默认字段。

## MLP06 — 时序与产品不变量

同一截止时间约束个股数据、指数数据、限定范围事实和计划权限。记录必须既属于已完成交易日，也已在截止时间前可用。D缺失时不得退回更早一天。来源修订保留旧证据并使受影响的待执行权限失效，不改写已执行历史。同日修订不构成新的独立信号。

实时监测和冻结回放调用同一纯政策函数。历史个股／指数修订与复权基准必须冻结；后来的供应商修订不得改变早期判断。模拟库存、真实持仓记录、回测组合保持隔离。网络I/O位于事务外。审核、启用、已读及提醒均不改变库存。

## MLP07 — 实施约定与验证

沿用Python 3.14、严格不可变Pydantic模型、精确Decimal、pytest、FastAPI／SQLite和Vue／TypeScript技术栈。领域规则放在 `src/trade_plan_monitor/domain` 和 `decision`；指数事实保留在 `market_index`；适配器和Vue展示服务端权威结果。使用snake_case和职责单一的纯函数，例如 `classify_market_regime(evidence) -> MarketRegimeEvidence`；政策求值不得隐式读取时钟／供应商。保留现有质量检查，不凭空新增覆盖率阈值。

从 `trade-plan-monitor/` 验证的命令（实际结果见验收报告）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_market_linkage_review.py tests/integration/test_market_linkage_runtime.py tests/integration/test_market_linkage_replay.py -q
.\.venv\Scripts\python.exe -m pytest -m "not live" -q
.\.venv\Scripts\python.exe -m ruff check src tests
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/market-linkage.spec.ts
```

新增测试路径是计划交付物。单元检查须独立断言算术与分支预期；集成使用真实临时SQLite和确定性供应商；浏览器验收使用本地合成数据。不隐含真实供应商调用或用户数据库变更。实际运行仍需满足已有供应商认证要求。

## MLP08 — 发布标准与文档索引

模块验收ID MR-A01–MR-A05、RS-A01–RS-A04、CS-A01–CS-A05、QP-A01–QP-A05、WF-A01–WF-A06须全部通过，并具备任务追踪和双语验证证据。覆盖全部大盘路径、未知、相等边界、日期对齐、原子性、重启、未来数据变异、来源修订、重复消费信号及非联动计划不变。涉及生产组合的任务不能只凭纯函数测试宣布完成。

始终保留来源语义、冻结身份和双语文档。涉及P1范围、额外供应商／依赖或策略决策改变时须修订规格。不得伪造人工批准、删除不支持依赖来通过审核、绕过风险，或用离线测试宣称实时认证。所有代码工作须先获得实施授权。

本规格、五份模块规格及[任务清单](../../../tasks/market-linkage-p0.zh-CN.md)构成已批准实施包。配套能力地图、README提示词、API契约、操作指南和验收报告描述已实现能力及验收边界。
