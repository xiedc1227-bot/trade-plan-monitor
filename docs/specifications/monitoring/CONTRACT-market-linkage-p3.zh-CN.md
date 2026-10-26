# 契约：market-linkage-p3

状态：实施契约 — 2026-10-26。[已批准规格](SPEC-market-linkage-p3.zh-CN.md) · [英文规范版](CONTRACT-market-linkage-p3.md)。不新增策略阈值。

## MLP3-K01 — 版本与仓位归属

Schema9 / condition-plan-v5；审核域 plan-review-content-v6；提取 plan-extract-v12。P3TradePlan 扩展 Schema8，替换仓位模型，不推断 max_qty。`position.limit.mode=CAPITAL_ONLY` 必填 capital_policy，禁止 max_qty；QUANTITY_AND_CAPITAL 同时要求 max_qty 和 capital_policy。原可选分仓字段保持来源语义。所有 BUY 必须使用既有日线联动 TACTICAL P2Rule，普通 SELL 和技术风险分支保留范围。仅股数计划留在原 schema；公开和冻结9准入分别等完整防护链完成后才开放。

## MLP3-K02 — 政策与精确判定

金额政策共用必填字段：policy_version=capital-policy-v1、currency=CNY、scope=SYMBOL_CORE_AND_TACTICAL、account_scope=SIMULATION、正数 cap_fen。OPEN_COST_CAP 另需准确的 P2 FeeSchedule 作为 buy_cost_schedule；MARKET_VALUE_CAP 则要求 valuation=CURRENT_ADMITTED_QUOTE，禁止成本表。与 P2 economics 共存的费用表须规范化内容相等，不仅 ID 相同。仅金额禁止虚假 max_qty。小数输入仍为字符串，严格整数数量／分值保留9007199254740991，批次上限500，事件／操作上限10000。未知明确表示，不当作零或无上限。

先计算来源选定 q。成本：after=K+q*(p+buy_slippage)+buy_fees；市值：after=(N+q)*p，均须 <=cap_fen。明确股数上限另要求 N+q<=max_qty。不缩量、不改量、不从金额生成 Q0。容量区分 BOUNDED(remaining_qty)、UNBOUNDED(无股数上限且库存已知)、UNKNOWN；仅新 capital-market-calculation-v1 携带该联合，历史数量计算保留 capacity=int|null 原含义。capital-limit-evidence-v1 记录政策哈希、阶段、准确 q、报价、库存／账本版本、占用、剩余金额及阻断，不产生 BUY 权限。capital-consumed-v1 绑定策略语义，不绑定瞬时接收身份，不产生独立新信号。

## MLP3-K03 — 账本与期初依据

capital-book-v1 按单证券／库存流记录独立正数版本、库存版本、初始化／校正时间、完整批次及依据哈希。批次包含 lot_id、bucket CORE/TACTICAL、正整手 quantity、retained_basis_fen（非负安全整数或 null）、来源回执引用。lot_id/bucket 唯一，完整数量须等于当前库存，成本合计溢出无效。不从真实账户或研究现金推断。

独立 simulation_capital_book 当前表和 simulation_capital_event 仅追加表与库存共用事务。事件记录 command ID、请求哈希、预期／结果版本、种类 OPENING/RECONCILIATION/BUY/SELL/UNKNOWN_CHANGE、服务器时间、前后哈希及来源／假设。唯一命令身份保证重放或冲突，不能二次生效。旧 daily-simulation-v1 原载荷不变。

期初输入绑定已审核计划／版本、expectedInventoryRevision、expectedBookRevision（仅无账本时为0）、observedAt、出处及完整有来源批次成本。当前服务器记录接收／审核／可用时间，禁止未来观察或倒签。非零未知成本须明确人工校正。已初始化空库存可只读推导 K=0/bookRevision0，首次明确 BUY 在同一事务创建并记账，不初始化未知持仓。修正追加依据，不改已完成效果。

## MLP3-K04 — 分配、未知历史与原子性

BUY 记录冻结适用费用表下准确预算借记。SELL 使用库存实际选定分配：released=floor(basis*sold/old_qty)，余分保留在余批，最终卖完释放全部。不改变最近优先／持仓范围分配、T+1 或底仓保护。卖出所得／利润不抬高上限，计划切换不重置成本，新费用表仅影响未来买入。旧计划买入无 P3 借记时记录未知成本；旧二进制／版本不匹配在校正前未知。缺成本不成为市值上限或 SELL 前提。

同一事务复核当前库存／账本／政策／报价，更新双账本、消费唯一整笔信号并提交回执／出站箱。相同键／正文重放原回执，正文变化／处理中／版本冲突409。失败不留部分库存、预算、事件或消费。预览／审核／批准不预留；普通和 P1 例外数量继续冻结，只有当前合格完整数量才执行。风险 SELL 绕过 BUY 金额判定；真实存储故障仍是原子错误。

## MLP3-K05 — 接口与错误

GET /api/v1/simulation-capital-books/{symbol} 读取有界当前模拟资源。已有非零已知库存但缺账本为 UNKNOWN，不能编造零账本。POST /api/v1/simulation-capital-openings 为明确幂等人工命令，不启用计划，回执含 inventoryChanged=false、authorityGranted=false。

POST /api/v1/plan-capital-previews 接受 planVersionId、ruleId、可选 occurrenceId（例外 candidate_id），仅 BROKEN_STRONG 可含 proposedQuantity，拒绝客户端价格／成本／容量／批准。响应 computedAt、planVersionId、ruleId、quantity、evidence、assessment 和字面 authorityGranted=false；不写入，不产生可用于执行的回执。缺失／过期当前权限409、无效正文422，沿用既有结构化准入错误和字节预算。受保护接口存在后才生成准确类型，当前上下文变化后丢弃迟到界面响应。

## MLP3-K06 — 冻结研究与依据边界

backtest-run-v10 携带 Schema9、冻结期初事实、明确预算校正事件和独立模拟／例外授权。capital-exception-event-v1 承载新计算证明，旧 frozen-exception-event-v1 继续严格校验。校正事件含 RECORDED_LOCAL/RESEARCH_SCENARIO 来源及有序可用／接收时间，未来事实不补过去缺口，不读取可变当前账本／费用源。研究实际结算／现金／盈亏与预算估算分开，包括仅仓位上限资金模式，不编造 max_qty／现金。

保留32KiB结果项和原来源／输入／报告总上限，在入队／权限变化前准入体积。共用证明须解析并复核完整依据，不截断或删证明。旧读取器拒绝9；增量迁移仅临时库测试，回退保留新依据并阻断9。用户库迁移、live 供应商、部署及推送未授权。

## MLP3-K07 — 实施接缝与阶段证据

T01 基线 V01：98项通过、1条既有 Starlette 警告、3.00秒。原文哈希／摘录冻结到 tests/fixtures/p3_original_prompt.json 并独立核验。按模型／哈希→纯费用／金额／成本→存储／期初／原子记账→提取／运行／例外防护→受保护 HTTP／生成契约→界面／浏览器→冻结读取器／工作器→全量回归／文档顺序推进。不能在防护链未就绪时批量改 schema 集合开放9。保留 tasks/plan.md、tasks/todo.md。
