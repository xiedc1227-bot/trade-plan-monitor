# 契约：market-linkage-p3

状态：实施契约 — 2026-10-26。[已批准规格](SPEC-market-linkage-p3.zh-CN.md) · [英文规范版](CONTRACT-market-linkage-p3.md)。不新增策略阈值。

## MLP3-K01 — 版本与仓位归属

Schema9 / condition-plan-v5；审核域 plan-review-content-v6；提取 plan-extract-v12。P3TradePlan 扩展 Schema8，替换仓位模型，不推断 max_qty。`position.limit.mode=CAPITAL_ONLY` 必填 capital_policy，禁止 max_qty；QUANTITY_AND_CAPITAL 同时要求 max_qty 和 capital_policy。原可选分仓字段保持来源语义。所有 BUY 必须使用既有日线联动 TACTICAL P2Rule，普通 SELL 和技术风险分支保留范围。仅股数计划留在原 schema；公开和冻结9已在各自完整防护链通过后分别开放；历史输入仍保留原版本边界。

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

## MLP3-K08 — 已实现的当前 API 归属

当前 API 在 web/p3_schemas.py 中拥有 CapitalBookView、CapitalOpeningApiCommand、CapitalOpeningReceipt、CapitalPreviewCommand 与 CapitalPreviewView；不可变预算账本、事件、金额评估与严格开仓命令继续由领域层拥有。仅新增 K05 的三条路由。两套 OpenAPI 与生成 TypeScript 文件提供相同 P3 操作。能力 supportedSchemaVersions 增加9及 capitalExecutionVersion=condition-plan-v5；编辑器增加 capitalCandidateSchema。已有字段和路由保留。完整普通、例外与 HTTP 防护完成后开放当前公开9；历史冻结输入版本仍拒绝9；完成 T19/T20 防护的 v10 接受9。JSON 时间与列表在 API 边界转换，领域数字严格校验与完整500批次上限保留。收益预览同时接受当前9，仍不授予授权。

CapitalBookView.inventoryLots 在尚未建立成本账时也列出完整当前模拟批次标识与数量（最多500），不推断成本。既有日线提醒可选 capital_mode/capitalMode 标识来源政策，旧提醒省略该字段。

## MLP3-K09 — 冻结金额来源事件与批次引用

capital-opening-event-v1 拥有 source_event_id、plan_hash、symbol、provenance RECORDED_LOCAL/RESEARCH_SCENARIO、observed_at<=received_at<=available_at、order0..10000、明确 confirmed=true、source/excerpt/reason、完整 lots（最多500）、必须显式出现但可为 null 的 recorded_event 和封装哈希。每个批次记录必须显式出现但可为 null 的 source_lot_id（已记录来源不得为 null）、bucket、quantity、retained_basis_fen 与稳定引用：OPENING(lot_key) 或 BUY_SIGNAL(signal_id)。引用选择准确期初批次或实际整笔买入回执，不选择其他批次、不推断成本、不依赖私有数据库计数器。已记录事件必须是原始 OPENING/RECONCILIATION capital-book-event-v1 回执，其证券、成本、批次数量、来源文字与服务端时间相符。研究假设事件必须明确声明假设，不得冒充已记录回执。

capital-replay-program-v1 按 available_at/order 冻结唯一有序事件。最多10000事件并沿用8MiB输入上限。运行开始前已可用的事件可以为明确匹配的期初库存提供依据；未来事件仅在可用后应用，不能补齐过去未知成本。capital-exception-event-v1 保留新的完整金额计算；frozen-exception-event-v1 继续严格限制旧计算。unified-research-input-v3 与 backtest-run-v10 绑定明确金额输入、分离的授权／执行事件及既有研究账户。缺失成本声明保持 UNKNOWN，明确空金额程序不授予任何权限。完整输入参与哈希，未来来源事件不改变较早私有授权标识。禁止读取当前用户数据或可变当前预算／费用。

## MLP3-K10 — 已实现的私有回放与报告引用

CapitalReplayState 仅对已可用的冻结声明，在私有事务内调用 confirm_capital_opening，解析准确的 OPENING/BUY_SIGNAL 批次，并保留 CapitalReplayOutcome 的来源、封装、来源分类与私有记录哈希。必须匹配完整当前批次，声明不改变库存。政策替换后，延迟声明仍绑定冻结调度中的原审核快照；私有应用仍检查当前已审核 Schema9 计划与准确当前库存。这仅延续成本事实，不延续旧 BUY 授权。backtest-run-v10 仅在显式预算程序存在时接纳 Schema9。当前金额防护和准确实际分配记账继续共用；LoopAccount/ResearchValuation 的现金与盈亏保持独立。

研究 CapitalSignalReference 保留 market_linkage_ref/pretrade_ref/capital_execution_ref；signal_linkage/signal_pretrade/signal_capital 各自仅保存一份不可变证据。CapitalLinkageReference 仅复用 base_evidence_hash 对应的逐字节等价市场事实，同时保留独立 calculation/approval_binding/evidence_hash。读取器重建并校验完整 CapitalMarketDecision 与 DailySignalState；缺失或篡改引用会失败。无需截断即可保留原32KiB结果项与总量限制。可选 capital_outcomes 在旧报告中省略；发布与重读将其绑定到准确可用的冻结来源序列。联动 Schema6/7/8/9 的自动准备数据另行复制至少60个前序指数交易日，不将其混为个股 daily_observations；冻结要求编码和旧存储输入保持不变。准备、调度和工作台命令携带 capitalProgram 与 capital-exception-program-v1；旧输入不能借用这些字段或版本。

准备浏览器入口仅接受可选 capitalProgram/exceptionProgram 冻结记录。公开 capitalProgram 省略时，在持有的必填 v10 输入中规范为显式空 CapitalReplayProgram，不推断成本或授权；非零持仓成本缺失仍为 UNKNOWN。填写的声明仍须准确校验来源和上下文，当前用户账与研究成本绝不作为后备来源。
