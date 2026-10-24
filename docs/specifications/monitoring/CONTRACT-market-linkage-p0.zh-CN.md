# 契约盘点：market-linkage-p0

## MC01 — 授权与基线

用户于2026-10-24批准MLP-D01–MLP-D06并授权实施。盘点基线：`c7378a4`，分支 `main`。本附录落实MLP-T01的文档部分，验收仍取决于基线验证与以下检查，不表示生产能力已具备。

## MC02 — 实际边界盘点

以下路径相对于 `src/trade_plan_monitor/`，以 `web/` 开头的浏览器路径除外。

| 边界 | 实际读写端 | 必需变更 |
| --- | --- | --- |
| 执行格式 | `domain/plan_codec.py`、`domain/unified_plan_models.py` | 明确Schema 6分派，保留Schema 1–5序列化与拒绝语义 |
| 草稿／校验 | `domain/daily_plan_validation.py`、`domain/unified_plan_validation.py` | 明确联动草稿分支，不回退Schema 4 |
| 哈希 | `domain/plan_hash.py`、`state/daily_repository.py` | 新内容域，旧规范JSON和哈希不变 |
| AI提取 | `ai/plan_extraction.py`、`ai/extraction.py`、`ai/loop_plan_extraction.py` | 按版本处理候选和来源绑定，不赋予批准权限 |
| 更新／准备 | `ai/plan_update_extraction.py`、`ai/preparation_wire.py`、`ai/plan_delta_wire.py`、`ai/predecessor_patch.py`、`ai/update_review.py` | 完整及补丁流程均保留联动政策，拒绝静默转换 |
| 审核 | `ai/daily_review.py`、`state/daily_review_store.py`、`web/plan_service.py`、`web/daily_service.py` | 内容与来源绑定包含全部策略叶子，正确使批准失效 |
| 持久状态 | `state/daily_state_models.py`、`state/daily_repository.py` | 封闭新证据载荷和联动信号变体，旧记录不变 |
| 执行 | `decision/unified_lifecycle.py`、`state/simulation.py` | 持久化固定完整数量，不从固定规则数量重算 |
| 运行时 | `runtime/daily_service.py`、`runtime/production.py` | 个股／指数配对采集和明确联动分派 |
| 读取／发送权限 | `runtime/status_authority.py`、`web/runtime_status_read_service.py`、`notifications/outbox.py`、`notifications/dispatcher.py` | 完成与发送检查绑定双方已使用证据集 |
| 回放 | `backtest/run_input.py`、`backtest/runner.py`、`backtest/loop_dataset.py`、`backtest/plan_schedule.py`、`backtest/plan_updates.py`、`backtest/preparation_review.py` | 联动输入与审核准入，保留旧冻结格式 |
| HTTP | `web/routers/plans.py`、`web/routers/daily_plans.py`、`web/preparation_schemas.py` | 在现有操作族增加明确变体，不支持读取端拒绝 |
| 浏览器契约 | `web/src/api/generated.ts`、`web/src/api/generated-runtime-status.ts`、`web/src/composables/usePlanWorkspace.ts` | 按实际服务端模型生成，展示服务端判断 |

## MC03 — 固定载荷决策

执行身份为 `schema_version=6`、`execution_mode=CONDITION_PLAN`、`execution_version=condition-plan-v2`。既有根字段保持类型和边界。联动计划必填 `reference_market`，按现有板块映射派生。联动普通规则使用BUY／TACTICAL、日线确认、下一交易日执行、明确的 `condition` 作为S0、明确LOW_BUY区域、有效期、独立信号和失效政策；包含 `market_policy` 与 `quantity_policy`，禁止 `quantity`。固定规则禁止两个政策字段，保留 `quantity`。

`market_policy` 必填 `policy_version=market-linkage-v1`、`base_confirmation=S0`、`exception_policy=BLOCK_P1`。展开后的状态、强弱和S1／S2定义为MR03、RS02及CS02–CS03规定的精确版本常量，展开策略值须具备明确来源审核绑定。只有版本名称不足以证明来源。S0仍是完整用户定义树。必填Decimal系数序列化为字符串。QP01规定的全部数量政策字段必填，不以可选字段默认值补造策略。

草稿以null和未解决证据保留缺项，不因此变成可执行计划。展开条件计入深度4与叶子50限制。共用数量预检接受明确Q0、系数、最低量和递增单位，校验严格整数和Decimal系数，返回共同合法最大数量或无数量，不具备库存或执行权限。

## MC04 — 哈希与兼容矩阵

规范JSON继续使用排序键、UTF-8、紧凑分隔和禁用NaN。完整计划身份仍为准确执行规范JSON的SHA-256。Schema 6审核内容只排除 `plan_id`、`version`、`name`、`metadata`，使用 `plan-review-content-v3` 域加NUL字节和规范字节。Schema 5保留 `plan-review-content-v2`，更早域保持字节一致。

新联动判断证据使用 `market-linkage-evidence-v1`，联动信号计算使用 `market-linkage-calculation-v1`。两者按既有域／NUL／规范哈希原语处理完整版本化载荷。包含交易日、截止时间、计划／审核身份、全部已使用来源哈希、选中路径、Q0、系数与数量，后来事实不得进入决策；完整证据保留已准入采集时间用于审计，独立连续性哈希按 MC06 排除易变获取状态。待执行信号引用不可变计算；执行时另行核验库存资格。

| 载荷 | 新读取端 | 旧读取端／回退 |
| --- | --- | --- |
| Schema 1–4历史 | 既有准确解码／回放 | 不变 |
| Schema 5固定 | 既有准确解码／启用 | 不变 |
| Schema 6联动 | 专用校验和新哈希域 | 明确不支持版本，不能降级 |
| 旧状态／证据 | 原封闭模型 | 不变 |
| 联动状态／证据 | 明确版本载荷 | 保留存储，阻断不支持操作 |

既有公开路由保留，只扩展类型化请求／响应变体。生成模式变更和快照哈希须在实际生成后记录，不能在此编造。回退禁用联动启用／执行并保留记录。临时数据库迁移不得改写历史JSON。

## MC05 — 验证门槛

产品修改前运行基线领域／审核测试，保留失败并排查。在各归属任务测试准确旧格式往返、不支持版本拒绝、执行／草稿内容哈希一致、严格来源绑定和重启安全持久化。边界盘点、双语一致与基线诊断未记录前，MLP-T01不算完成。后续任务须有实际实现测试，不能只凭本盘点完成。

## MC06 — 已实现的存储与接口扩展

可执行分支为 Schema 6 / `condition-plan-v2`，研究输入使用 `backtest-run-v7`。联动日线事实使用 `market-linkage-index-v1`；回放冻结 `market-linkage-replay-source-v1` 来源，包含准确观测时间、修订、日历范围及参考指数身份。循环回放清单携带可选 `linked_index_source`；缺省字段不进入旧格式序列化。存储的循环回放输入在任务运行前校验来源和计划时序。既有运行时JSON存储接受明确的封闭扩展，无需破坏性迁移。

`MarketLinkageDecision.evidence_hash` 覆盖完整规范载荷，包括 `QuantityCalculation.calculation_hash`。内部计算摘要覆盖自身有界操作数、结果和阻断原因；外层判断把计算绑定到规则、计划内容、日期和使用证据。`consumed_hash` 单独绑定来源身份和政策，排除易变的当前时钟与库存变化，用于失效判断而不调整数量。解码时校验两个摘要。模拟操作在既有事务内检查准确冻结数量与当前来源权限。读取、完成证明捕获／匹配及提醒发送准入拒绝已被替代的指数证据，不改变库存。

官方数量规则使用 `cn-equity-buy-grid-2026-07-06`，携带有日期的来源和URL。更早日期或不支持的证券前缀返回未知。市场合法数量与既有100股模拟规则取交集。这不认证任何供应商或BSE日历。

没有新增HTTP路由。生成产物新增26个可达模型，扩展15个既有模型；两个API配置的准确Schema 5投影均与 `c7378a4` 比较。产物摘要记录在[U-MLP](SPEC-unified-plan.zh-CN.md)。既有 `/review-context` 登记修正旧测试白名单遗漏；该路由在本次变更前已获批并实现。

日线内容身份使用 `market-linkage-index-content-v1`，覆盖准确K线值、日期和来源类别，排除刷新 `observed_at` 与整批 `provider_revision`。完整证据仍保留两字段用于审计／截止时间校验。后续修订按观测时间排序，不能按内容哈希修订号的数值排序；缓存的早期输入不能覆盖它。

个股连续性同样排除采集记录派生的 `bar_id`、`received_at`、`available_at` 和 `adjustment_as_of`，但保留已准入价格、交易日、提供方及复权基准身份。数值确认操作数和强势值采用规范 Decimal 内容；等值格式变化不算修订。完整决策证据保留原始采集字段及操作数。即使 S0 仅包含 `REVIEWED_FACT` 叶子，日线收盘回放依赖仍须生效。
