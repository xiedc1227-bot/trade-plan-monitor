# 独立审查：daily-plan

> 2026-10-02范围已变更：用户授权删除日线券商订单/部分/未知跟踪，改为显式原子整手模拟。本文件记录此前范围，其完成/测试结论不批准新清理。请依据[当前清理契约/任务](../../tasks/2026-10-02-daily-plan-simulation-cleanup.zh-CN.md)及修订后的canonical规格继续。以下历史证据保留。

英文版本为 canonical；本文件是 `2026-10-01-daily-plan-independent-review.md` 的对应中文审阅副本。

## R01. 结论与检查点

**最终独立复查：无剩余实质问题；F1–F11 全部 CLOSED。** R07 是当前结论。R03–R06 保留早期问题和检查点，包括历史 OPEN 标签。协调员最终完整离线后端门槛已通过；R08 单独归因并记录该结果。

- 日期：2026-10-01。
- 审查员：用户指定、全新审查上下文的独立 `gpt-6-astra/high`，`/root/final_review_v2`。
- 审查基线：相对 `b2572b6` 的未提交 daily-plan 改动，包含未跟踪的实现、测试和文档。本报告是首轮工作区审查，不是某个已提交版本的认证。
- **首轮结论：Request changes。F1–F11 全部 OPEN。** 协调员已交 Sol 修复。报告修复完成或开始修复均不等于关闭问题，仍待独立复查。
- R03 保留首轮问题及 OPEN 标签作为历史证据。R07 记录最终独立复查状态；随后实现改动需实际检查后才获认证。
- 流程：Astra 设计 → Sol 实现 → Astra 独立审查 → Sol 修复 → Astra 复查。最终全量回归由协调员负责。

范围遵循用户恢复任务后的指示及 D01/D11/DP-A15/DP-A19：基本面和公告核验完全退出日线监控，保留为可见的非监控背景，不能变成技术事实、前提或阻断。可交易性、停牌和已认证交易日历仍是运行输入。既有指数行为以及 Schema 1/2/3、prompt v1–v6、ta-v1 是兼容边界。已读取且未修改原模板 `../docs/TradingAgents/reports/新提示词.txt`。

## R02. 方法与证据边界

审查使用 `code-review-and-quality` 和 `vue-best-practices`，读取仓库指示、原模板、日线规格/能力地图/任务上下文，枚举已跟踪及未跟踪文件，并沿领域模型、来源审核、持久化、运行时、API、通知和 Vue 边界检查新链路。阅读既有测试以识别意图与遗漏，不把通过数量本身作为正确性证明。

定向检查使用合成的已审核计划、临时 SQLite 数据库、`Chain`/`TestClient` 测试辅助、实际日线记账/运行服务或纯契约/计算函数。通过 `.venv/Scripts/python.exe` 执行临时内联复现，没有修改源码或测试。具体输出记录如下。生产组装仅离线检查，没有调用实时 provider。测试提供的是合成人工策略，不是批准用户的历史计划。

以下证据类型含义：

- **SQLite/API/runtime 复现：** 临时持久化状态，使用正常保存/审核/启用 API 和/或实际运行服务；各问题明确具体命令边界。
- **纯函数复现：** 使用合成输入调用实际契约、审核或计算函数。
- **生产/UI 静态链路：** 直接检查调用签名和状态转换；不声称已独立执行生产或浏览器复现。

文件路径相对仓库根目录。函数名是稳定、精确的定位点；审查消息中的行号对应首轮基线，可能随修复移动。

## R03. 必须处理的问题

### F1 — P1 — OPEN：CLEAR 风险沿用旧计划范围

**文件/定位：** `src/trade_plan_monitor/decision/daily_risk.py` 的 `advance_daily_risks`，初始化 `dict(old)` 分支；`src/trade_plan_monitor/runtime/daily_service.py` 的风险持久化。

**复现：** 保存、审核、启用版本1，设置 `involves_core=True`、`target_core_qty=0`；以正常收盘评估，使两个风险状态持久化为 CLEAR。保存、审核、启用版本2，改为 `involves_core=False`、`target_core_qty=100`。依次评估38.00及下一交易所时段收盘38.10，均低于38.18。普通风险确认为 CONFIRMED，却仍沿用旧 `True, 0` 范围。输出包含 `('ORDINARY_TECHNICAL', 'CONFIRMED', True, 0)`，而当前审核策略明确保护 CORE。

**后果：** 从未触发的风险以后可能授权卖出与当前审核版本相悖的 CORE。

**修复与回归：** 未触发的 CLEAR 从适用的已审核分支刷新范围；保留 PENDING/CONFIRMED 义务以及重评因果元数据。测试首次跌破前范围双向改变，并证明修改不能削弱已锁定义务。证据：SQLite/API/runtime 复现。验收：DP-A03/DP-A16。

### F2 — P1 — OPEN：订单报告可以破坏占额权限

**文件/定位：** `src/trade_plan_monitor/state/daily_accounting.py` 的 `report` 关联额度校验及 `snapshot` 订单折叠；`src/trade_plan_monitor/decision/daily_lifecycle.py` 的 `own_reserved > remaining`。

**复现：** 对同一 BUY100 信号，在临时 SQLite 中通过实际记账服务，以当前 revision 分别登记不同 `external_id` 的两笔 PENDING100。两次写入成功，下一运行评估抛出 `ValueError: pending order quantity exceeds immutable signal remainder`。随后对第一笔外部编号提交 CANCELLED1，改为 `side=SELL`、`bucket=CORE`、`signal_id=None`，仍被接受，并通过覆写该订单身份将 BUY 总占额从200降为100。

**后果：** 被接受的报告可以释放无关 BUY 额度，或持续破坏之后的评估。逐报告数量检查不能约束原信号的累计权限。

**修复与回归：** 固定外部订单归属（symbol/side/bucket/signal），校验明确状态转换以及关联剩余额度下的累计未成交量，保留真实成交及幂等性。真实超出原意图的交易需走明确的不关联审计路径，不能静默取得信号权限。通过公开 API 覆盖多订单、部分成交、UNKNOWN 对账、身份冲突撤单、重试与回滚。证据：SQLite/记账/runtime 复现。验收：DP-A11/DP-A12/DP-A18。

### F3 — P1/P2 — OPEN：后继版本使旧信号永久停留 READY

**文件/定位：** `src/trade_plan_monitor/runtime/daily_service.py` 的 `run_inputs` 后继版本 `continue`；`src/trade_plan_monitor/decision/daily_lifecycle.py` 的 `confirm_daily_signal` 前序状态门槛。

**复现：** 周五确认的信号在周二变为 READY100，然后启用版本2。周三16:00评估，历史信号仍为 `READY`，`executable_qty=0`、`new_order_qty=100`，阻断为 `SUCCESSOR_EQUIVALENCE_REVIEW_REQUIRED`。后继分支跳过了到期/重置持久化。因为前序信号仍 READY，之后的独立确认被拒绝。

**后果：** 正常替换版本会永久阻断合法的后续独立信号，历史信号还展示误导性的新订单额度。

**修复与回归：** 在不授予执行权的前提下推进历史生命周期/到期，将可执行及新订单量都置零，支持跨版本/plan_id 的已核验新独立证据。保留旧消费量和未知订单。测试 READY/部分成交换版、到期、reset/event 重新授权及重启。证据：SQLite/API/runtime 复现。验收：DP-A07/DP-A09/DP-A18。

### F4 — P1 — OPEN：忽略 SELL 占额和 UNKNOWN 订单

**文件/定位：** `src/trade_plan_monitor/decision/daily_lifecycle.py` 的 SELL 执行分支；`src/trade_plan_monitor/decision/daily_risk.py` 的 `risk_execution`；`src/trade_plan_monitor/runtime/daily_service.py` 的发送时复核。

**复现：** 实际 TACTICAL100、已报可卖100，同批持仓已有另一笔 UNKNOWN SELL100。普通计算仍返回 READY、可执行100、新订单100且无阻断；风险计算也返回 RISK_EXIT、TACTICAL100，分配同一已交收 lot100且无阻断。PENDING SELL 同样没有扣除。

**后果：** 监控可能授权卖出已经被其他委托占用、或可能已经卖出的持仓。

**修复与回归：** 将卖单占额与 bucket/lot 可用量对账，区分自己的持续意图和新订单，UNKNOWN 执行保持锁定但保留已确认风险义务。发送时复用相同权限计算。覆盖普通/风险重叠、外部 PENDING/UNKNOWN SELL、部分成交/撤单及明确的未成交订单完整性。证据：纯函数复现及运行调用链检查。验收：DP-A08/DP-A12/DP-A16/DP-A18。

### F5 — P1/P2 — OPEN：来源排除可以隐藏技术策略

**文件/定位：** `src/trade_plan_monitor/domain/daily_scope.py` 的 `require_nontechnical_exclusion`；`src/trade_plan_monitor/ai/daily_review.py` 的 `build_daily_review` INVENTORY_ASSERTION 处理；`src/trade_plan_monitor/ai/daily_extraction.py` 的允许分句类型。

**复现：** 原文 `股价低于39.45元时买入100股。` 可以整句作为 HUMAN_SCOPE_SELECTION 排除，审核返回 `issues=()` 和 BACKGROUND：有限校验漏掉了这一明确的价格/数量/买入策略。另将 `收盘跌破38.18元时停止加仓。` 标为 INVENTORY_ASSERTION、paths为空并填写足够长且看似具体的理由，审核同样无问题。后一类型也可由 AI 输出。

**后果：** 必须保留的技术原文可以通过非策略分类从审核/启用契约中消失。

**修复与回归：** 对常见明确技术价格/动作/数量语句关闭两种压制通道，同时保留真实库存叙述及精确基本面排除，并维持技术剩余跨度覆盖。不要求万能自然语言分类器。覆盖以上原句、混合条款、未知基本面措辞、AI 分句分类、预览及已保存审核。证据：纯审核校验器复现。验收：DP-A02/DP-A03/DP-A15/DP-A19。

### F6 — P1 — OPEN：一条技术事实能充当全部三个证据维度

**文件/定位：** `src/trade_plan_monitor/domain/daily_plan_models.py` 的 `DailyEnabledRule` 和 `DailyTradePlan.semantic_contract`；`src/trade_plan_monitor/decision/daily_conditions.py` 的 REVIEWED_FACT 匹配；`src/trade_plan_monitor/decision/daily_lifecycle.py` 的普通确认。

**复现：** 将 `price_structure`、`volume_or_candle`、`technical` 三个根都设置为同一 `REVIEWED_FACT`，`fact_kind=TECHNICAL`，完整 Schema 4 仍通过。运行时按事实种类/日期匹配，同一事实因此满足三个根。相同结构漏洞也允许各根全部采用同一指标叶。

**后果：** 单个技术事实或指标即可授权普通交易，绕过独立价格结构、量价/K线和技术指标三个维度的要求。

**修复与回归：** 校验每个维度允许的证据族和 ALL/ANY 成功路径，不能靠无关备选绕过必需维度；保留合法组合条件。在契约/草稿层形成问题，并增加实际审核/启用/runtime 负例及合法三维正例。证据：完整模型纯函数复现及计算链追踪；未声称独立执行了 F6 端到端交易复现。验收：DP-A03/DP-A04/DP-A05。

### F7 — P1 — OPEN：生产立即重评把 Clock 对象当函数调用

**文件/定位：** `src/trade_plan_monitor/runtime/production.py` 的 `ProductionMonitorPipeline.__init__` 日线服务组装；`src/trade_plan_monitor/runtime/daily_service.py` 的 `reevaluate_version`；`src/trade_plan_monitor/runtime/clock.py` 的 Clock/SystemClock；`src/trade_plan_monitor/web/monitor_composition.py` 的日线重评回调。

**链路：** 生产把 `clock=clock`（调度器 Clock 对象）传入日线服务，但 `reevaluate_version` 执行 `self._clock()`。Clock/SystemClock 只有 `now()` 和 `sleep_until()`，没有 `__call__`。公开 FACT/POSITION/REPORT 路由先提交变更，再调用此回调。浏览器 fixture 注入的是 `lambda: chain.now`，掩盖了不匹配。

**后果：** 真正生产立即重评会在用户变更已提交后抛出 `TypeError: 'SystemClock' object is not callable`，请求失败且没有完成预期运行状态更新。

**修复与回归：** 统一使用明确的时钟契约。使用离线 Clock/provider 检验真正的 ProductionMonitorPipeline 组装和公开变更回调，不是另造一个专用 callable-clock service。验证提交响应及更新后的 runtime/outbox。证据：生产静态链路。验收：DP-A03/DP-A18/DP-A20。

### F8 — P1/P2 — OPEN：风险重评与完成缺少持久生命周期边界

**文件/定位：** `src/trade_plan_monitor/web/daily_service.py` 的 REASSESSMENT 变更；`src/trade_plan_monitor/decision/daily_risk.py` 的 `advance_daily_risks`；`src/trade_plan_monitor/runtime/daily_service.py` 的重评及风险持久化；`src/trade_plan_monitor/notifications/daily_models.py` 的风险事件身份。

**复现：** 以两种技术事实确认严重风险。POST 独立重评，使用当前审核目标及稍后的原因消除证明，成功后存储状态为 CLEAR。下一次 `reevaluate_version` 使用未改变的 head 官方收盘及旧事实，又将风险设为 CONFIRMED。复现期间共享 F1 编辑刚开始；问题根源是重新使用已被取代的原因，不是某一中间补丁。另首轮源码没有在持仓达到保留目标后写入 FULFILLED 的转换。

**后果：** 已接受的原因消除证据无效；已完成减仓仍显示 CONFIRMED/RISK_EXIT0 并阻止后续独立交易。真正新风险出现时，固定分支/cause 身份还可能与此前通知冲突。

**修复与回归：** 持久化重评生效边界及被取代证据/原因边界，重评后更新当前投影，区分未来新风险发生与已解除风险。按 D07 实现目标完成：持仓达到审核目标可完成义务，不额外发明强制解除门槛。保留旧信号消费、执行未知和独立信号要求；重评或 FULFILLED 均不能复活旧剩余额度。覆盖旧证据重放、后续新证据、完成及新通知身份。证据：SQLite/API/runtime 重评复现，加完成/身份静态链路。验收：DP-A09/DP-A16/DP-A18。

### F9 — P2 — OPEN：UI 无法逐批完成人工补充

**文件/定位：** `web/src/composables/useDailyWorkbench.ts` 的 `supplement`/`refreshPreview`；`src/trade_plan_monitor/web/routers/daily_plans.py` 的 `_preview`；`src/trade_plan_monitor/state/daily_review_store.py` 的补充登记集合相等校验。

**链路：** 每次补充先刷新预览；即使候选精确内容哈希未变，预览也删除全部 HUMAN_SUPPLEMENT 绑定。客户端只提交本次新条目，`expectedRevision=0`；首次登记后同候选存储 revision 已是1。第二批产生冲突，此前 mapping 权限却已被丢弃。保存还要求已登记补充集合与 mapping 完全相等。

**后果：** 先补几项、检查、继续补充的正常流程无法完成。一次性批量补齐的浏览器 fixture 没覆盖这一行为。

**修复与回归：** 精确内容未变时保留服务端已登记权限，用返回 revision 合并逐批补充，并能在预览/重载后恢复继续审核。内容改变仍须使旧权限失效。覆盖两批补充 → 预览 → 保存/审核/启用，以及内容改变负例。证据：UI/API/持久化静态链路；未独立执行浏览器复现。验收：DP-A02/DP-A03/DP-A20。

### F10 — P1 — OPEN：遗漏一个官方收盘后普通风险不可恢复

**文件/定位：** `src/trade_plan_monitor/runtime/daily_service.py` 的 `run_inputs` 仅将 series 最后一根交给风险推进；`src/trade_plan_monitor/runtime/production.py` 的 `_recover_pending_close_batches` 排除 DailyTradePlan，以及 `prepare_daily_inputs`。

**复现：** 风险线38.18，周五官方38.00形成 PENDING。监控错过周二。周三提供完整认证序列，包含周五38.00、周二38.10、周三39.00，并评估周三官方收盘。结果仍为 PENDING，阻断 `NEXT_OFFICIAL_CLOSE_UNVERIFIED`，尽管必需的周二证据已经存在。以后各天均晚于预期第二收盘，也无法解决缺口。

**后果：** 本应周二收盘确认的风险无法在周三就绪，并无限卡住。普通信号在有效下一时段内启动时，同样需要可达的收盘重建入口，不能只恢复已经创建的信号。

**修复与回归：** 按时间顺序把缺失的已认证官方日期送入持久状态机，保留真实确认日/最早执行日，并使补齐从实际启动/迟到数据生产路径可达。禁止发送已到期历史普通指令。覆盖漏过风险确认收盘、下一时段启动恢复普通信号、到期后恢复、数据缺失与停牌区分及重启。证据：临时 SQLite/runtime 复现及生产恢复链路。验收：DP-A06/DP-A07/DP-A13/DP-A18。

### F11 — P1 — OPEN：保护 CORE 的分支降低另一分支的 CORE 目标

**文件/定位：** `src/trade_plan_monitor/decision/daily_risk.py` 的 `risk_execution`，`affected` 和 `target = min(... eligible ...)`。

**复现：** 合法计划中，普通风险 `involves_core=False`、targetCORE100，严重风险 `involves_core=True`、targetCORE200。实际 CORE300 全部可卖。两个风险确认后，当前计算返回 targetCORE100、卖 CORE200；真正涉及 CORE 的只有严重分支，其目标200只要求卖100。实际库存可以不同于建议划分，不能以计划建议 CORE 数量排除此场景。

**后果：** 合并义务后卖出的 CORE 超过任何适用 CORE 分支授权量。

**修复与回归：** 仅在涉及该 bucket 的分支中取保留目标最小值；没有适用分支则完全保护该 bucket。除双方都保护/都涉及外，测试不同 CORE 涉及范围及实际持仓与计划目标不同。证据：纯计算器复现。验收：DP-A10/DP-A16。

## R04. 其他观察与已检查边界

- 日线来源剩余跨度处理中的狭窄 `. ! ?` 标点裁剪符合保留有意义技术余文的要求。`DailyExtractionOutput` 拒绝 AI 生成 HUMAN_SCOPE_SELECTION；这不等于关闭 F5 的其他通道。
- 当前风险分配先按审核申报规则调整 bucket 汇总可执行量，再分配内部 lot 扣账。实际成交40+60可以合并为合法100股卖单，算法本身不强制两笔40/60独立委托。但用户截图反馈正确指出 UI 措辞存在误导。协调员已交付展示修正：先呈现合法汇总申报量，内部40/60分配仅作为明确标注的记账明细。该 UI 修复尚未在本报告中独立复查。
- 已检查的日线公式代码在独立 v2 路径保持 MACD 柱为 `2*(DIF-DEA)`。新来源排除的预期契约不要求公告核验放行。这些观察不是整体功能批准。
- 完整计划启用与来源审核、真实持仓/成交分别处理。实际历史计划仍不完整且未启用。

## R05. 覆盖、限制与下一轮

主要覆盖包括：新增日线领域模型/验证/hash 分派；来源提取/审核/排除及已保存审核绑定；官方/QFQ 数据准入及指标/条件计算；持仓确认/报告折叠及持久状态；普通与风险生命周期；运行事务/调度/provider 组装及立即重评；提醒身份/当前发送；公开日线路由；Vue 工作台、审核、操作及递归字段编辑器；以及主要新增单元、集成、浏览器测试。

以上定向复现是独立证据。实现代理报告的测试数量、构建和浏览器通过仅为补充上下文，未重跑或冒充审查员自己的完整验证。本审查员未执行全量后端/前端回归，未调用实时行情/AI/通知，未读取生产数据库或密钥，未修改源码/测试。旧指数/兼容行为还需要协调员最终相关及全量测试，静态分派审查不能认证所有旧路径。此前已启用的旧三分支开发数据，以及每种迟到/修订 provider 数据场景，本轮没有全部独立执行。

下一步：接收稳定的 Sol 修复交付，以定向回归证据复查 F1–F11 和汇总申报 UI 修正，检查修复间相互作用（尤其 CLEAR/重评/cause 身份、占额/完成、后继版本/补齐权限），再按实际结果更新本双语报告的关闭/未关闭状态。只有实质问题解决后，才由协调员最终完整离线测试及双语功能验证报告确认完成。

## R06. 二轮独立复查检查点

**历史二轮检查点结论：Request changes。** 以下证据范围内，原始 F1、F2、F3、F5、F6、F7、F9、F11 缺陷已独立验证修复并关闭。F4、F8、F10 仍 OPEN；后续修复进行中，本检查点不认证这些新改动。

- 独立定向执行：`test_daily_history_regression.py`、`test_daily_orders_regression.py`、`test_daily_risk.py`、`test_daily_risk_allocations.py`、`test_daily_source_exclusions.py`、`test_daily_plan.py`、`test_daily_plan_review_service.py`、`test_daily_scope_http.py`：**39 passed**，9.57 s。审查员也检查了权限、证据维度、排除及生命周期的改动。F1 刷新 CLEAR 范围并保留 pending 范围；F2 拒绝总量超额占用及 external identity 篡改；F3 使历史权限到期并将后继版本新委托投影清零；F5 拒绝原具体隐藏技术策略路径；F6 要求每个成功 ANY 路径证明对应维度；F11 仅合并适用 bucket 目标。
- 独立执行 `test_daily_supplement_batches.py` 加 `test_daily_production_reevaluation.py`：**5 passed, 1 failed**，3.54 s。F7 的真实生产构造服务使用不可调用时钟，事实、持仓和真实成交命令均可处理。F9 服务端登记的人工补充可经历两批、重复预览、重载及启用；改内容后旧权限失效，客户端伪造补充被忽略，重复版本保存受控冲突。失败项为下述 F10。这些是独立运行结果，未复制实现方结论。

### F4 — OPEN：剩余占额与保留目标的交互

`daily_lifecycle.check_daily_execution` 在部分成交改变信号投影状态后，把该信号自身 UNKNOWN 余额视为可用。独立纯计算复现：SELL planned100/filled40、actualTACTICAL60/sellable60、自身 UNKNOWN60，返回 executable60/new_order60 且没有阻断。UNKNOWN100 → 真实成交40 后余量必须保持锁定，不能取决于信号显示状态。

`daily_risk.risk_execution` 从可卖量扣除挂单，同时也必须从需要减持的量扣除挂单。独立纯计算复现：actualTACTICAL200、sellable200、审核 target100、pendingSELL100，仍返回另一次 executable100。已有加新增委托会把持仓降到0而非100。

相反边界也失败：记账保留完全成交后的旧 UNKNOWN 订单 quantity0。独立纯计算复现：旧 UNKNOWN SELL quantity0，加 actual/sellableTACTICAL100、target0，返回 executable0/unavailable100 及 `SELL_ORDER_RECONCILIATION_REQUIRED`。需过滤零余额或规范终态，同时不能放开真实 UNKNOWN60 余额。三个反例均已直接交实现负责人，后续改动待复查。

### F8 — OPEN：完成不能复活旧权限或抑制新原因

独立 SQLite/API/runtime 复现：周五 BUY100 在周二 READY；周五严重风险证据确认风险；周二10:00 真实 CORE SELL100 完成风险退出。一秒后新鲜可交易报价让**同一个旧 BUY 信号**重新 READY、executable100/new_order100。D07 允许完成风险，但不能撤销 `RISK_OR_REVIEWED_INVALIDATION`；需保留旧消费和挂单，并要求真正独立的后续信号。已有历史测试等到收盘，因此遗漏了同窗口复活路径。

仅按日期的完成/重评切点还会抑制周二10:00 完成后、周二稍晚官方收盘的真正新原因。代码检查确认 `close_date <= cause_cutover_date` 排除了整天。需依据已消费收盘/证据及实际切点时刻，让稍晚官方收盘可产生不同原因，同时立即重放仍保持 CLEAR。修复正在进行，本检查点不认证它们。

另一个独立 SQLite/API/runtime 复现确认原原因去重缺陷仍存在：周五严重风险在周二产生提醒；周二重评清除且持仓不变；全新周二严重风险证据确认新原因；周三当前持仓/报价再次允许卖出同一 openingCORE100。第二个风险为 CONFIRMED 且确认日为周二，但因两次 `risk_action` 完全相同而 `event_ids=()`。稳定的 symbol/kind risk_id 及 `daily_alert_key` 未包含不同原因的证据/日期。需将原因身份加入提醒去重，并在发送时校验该原因。

### F10 — OPEN：真实生产恢复仍拒绝所需日线证据

审查员独立执行真实 composition/lifespan 恢复测试。周五首次真实调度 OFFICIAL_CLOSE，预期 PENDING 实为 CLEAR，阻断 `DAILY_SESSION_OR_BASIS_UNVERIFIED`，未能到达后续恢复断言。`production.prepare_daily_inputs` 请求750个日历日并保留500根日线，但生产参考数据刷新仅覆盖366天。严格完整交易日准入因此拒绝超出已加载日历的日线。需让真实认证日历覆盖与日线/指标预热范围一致，不能缩短 fixture 或绕过准入。源码修复后复查周五首收盘准入、错过周二确认、周三启动、当前 QFQ 基准、原执行日期及动态预热需求。

独立完整模型准入还接受 `macd_min_observations=500` 配 `MACD_HIST` offset1。`DailySeries` 和生产数据上限500，因此该条件永远拿不到所需501根记录。同一边界影响 sequence500+offset1 及 volume499+offset1。需支持真实有界历史需求，或在新日线审核/启用阶段拒绝不支持的预热/偏移组合，不能批准永久无法计算的契约。

最后自适应日历补丁引入另一个独立复现的生产边界：最近750天增加50个已认证工作日假日，触发1500天请求；真实 OFFICIAL_CLOSE 随后在 `refresh_references` → `_commit_trading_days` → `references.upsert_trading_days` 抛出 `ValueError: days must not exceed 1000 rows`。需同一事务内有界分批保存所有认证日期。同时核对扩大持久日历返回超过1000个开放交易日时相邻的 `DailySeries.session_dates` max1000 边界，不能丢弃日线或关闭一致性校验。该源码补丁待修复，尚未通过审查。

### 委托合并边界与剩余限制

独立临时 SQLite 记账验证：同一 externalId 的 TACTICAL SELL40 再 SELL60 可接受并扣账100。同一 externalId 的 CORE SELL100 再 TACTICAL SELL100，第二笔因 bucket 身份不可变而拒绝。当前 UI 泛称内部批次可合并同一委托，需明确仅限同 bucket，并按 bucket 展示申报/登记量；不能暗示跨 bucket200 可作为一笔真实委托登记。这是有限的 UI/契约澄清，不要求建设券商 OMS。

二轮尚未独立执行 Chrome、全量回归或实时集成。旧兼容/指数、每种修订 provider 数据场景及此前已启用旧开发记录仍适用 R05 限制。剩余修复稳定后由协调员负责最终广泛回归。

## R07. 最终独立复查

**结论：本次已审查 daily-plan 改动无剩余实质问题，F1–F11 全部 CLOSED。** 这关闭审查问题，不能代替协调员最终完整离线回归，也不认证实时部署/provider。

| 问题 | 最终状态 | 独立验证的修复 |
| --- | --- | --- |
| F1 | CLOSED | CLEAR 使用当前审核范围；pending/confirmed 义务保留其范围。 |
| F2 | CLOSED | 总委托权限及不可变 external order 身份防止占额损坏；同 bucket 真实40+60仍可登记。 |
| F3 | CLOSED | 旧权限持久到期；后继版本投影不授新委托量；后续独立事件可创建新发生项。 |
| F4 | CLOSED | 正 UNKNOWN 余额在部分成交后保持锁定，零余额不再阻断，外部卖单占额及已覆盖的目标减持量不会重复提供。 |
| F5 | CLOSED | 已复现的具体技术策略排除与 INVENTORY_ASSERTION 绕过被拒绝；人工范围来源与 AI 输出保持分离。 |
| F6 | CLOSED | 每条成功条件路径证明自己的价格、量能/蜡烛、技术维度。 |
| F7 | CLOSED | 真实生产构造服务正确使用时钟；公开事实/持仓/成交变更刷新持久当前快照。 |
| F8 | CLOSED | CLEAR 重放不复活已消费风险证据；达到审核目标可 FULFILLED；旧普通权限持续失效；后续独立 BUY 与同日稍晚新风险原因有效；新风险原因产生不同提醒且发送时复核原因。 |
| F9 | CLOSED | 已登记补充以正确修订号经历连续批次、预览和重载；内容改动及客户端伪造补充不继承权限。 |
| F10 | CLOSED | 真实调度/启动恢复按当前 QFQ 基准处理遗漏官方收盘；所需历史有界且已认证；扩大日历通过存储、准入与运行输入限制。 |
| F11 | CLOSED | 仅在涉及该 bucket 的分支中合并保留目标。 |

最终独立运行及定向证据：

- `test_daily_orders_regression.py`、`test_daily_history_regression.py`、`test_daily_safety_boundaries.py`、`test_daily_plan.py`、`test_daily_risk.py`、`test_daily_risk_allocations.py`、`test_daily_scope_http.py`：**63 passed**，12.32 s。审查员阅读对应修复，包括持久 `risk_invalidated`、正余额过滤、挂单目标扣减、时刻切点、原因日期提醒身份/发送检查及500观察准入计算。
- `test_daily_production_reevaluation.py` 加 `test_daily_supplement_batches.py`：**7 passed**，7.03 s，在最后扩大日历边界前独立复核真实生产组装及两个真实恢复入口。
- 最后生产修复后，`test_daily_production_reevaluation.py`、`test_daily_plan_boundaries.py`、`test_daily_conditions.py`：**12 passed**，9.04 s。测试使用 SDK/provider fake 与临时 SQLite，但经过真实生产工厂、lifespan 和调度 deadline；恢复不调用替代的 `run_inputs`/`run_target` 路径。
- 审查员自己的原样内联生产反例在最终修复后重跑：最近750天增加50个已认证工作日假日，触发1500天日历请求。现产生 **500根真实日线、500个 series session 日期、无数据阻断且 ORDINARY_TECHNICAL PENDING**，完整运行日历包含1044个日期。没有虚构日线或交易日。此前存储1000与运行1000异常已解决。
- 源码检查确认仅日线路径日历回看750→1500→3000；同一事务每批最多1000且不截认证日历；完整日线运行输入上限3033个日期；`DailySeries` 使用单独且精确的原始日线窗口检查一致性。非日线参考历史仍为366天。理论预热/偏移总量超过500被拒绝；真实上市时间短/停牌历史仍返回缺少输入而非虚构记录。
- UI 与通知文本现明确 CORE/TACTICAL 分别申报、分别登记，仅同 bucket 内部批次可合并同一委托。独立 SQLite 证据确认同 bucket SELL40+SELL60 可登记。跨 bucket 重用一个 externalId 仍明确不支持，不再作出相反承诺。Chrome 执行/截图由协调员/helper 完成，不冒充本审查员独立浏览器运行。

剩余限制属于证据边界，并非未关闭的实质问题：本审查员未重跑完整后端/前端套件，未访问实时行情/AI/通知服务，未检查生产数据/密钥，未执行每一种 provider 修订场景，也未认证每个此前已启用旧开发记录。审查员未修改任何源码/测试，仅写入本中英文报告。协调员随后已完成固定源码最终后端回归；R08 单独归因并记录该结果。随后任何实质源码变化需要定向复查。

## R08. 协调员最终完成门槛

协调员 `/root` 对冻结生产源码执行 `.venv/Scripts/python.exe -m pytest -q -m "not live"`，报告 exit0：**6065 passed, 1 skipped, 4 deselected, 1 warning，3208.19s（53:28）**。这是协调员执行的完整后端回归，包含耗时的回测验收组；独立审查员**没有**运行该全量。审查员读取了 `C:/Users/xiedc/AppData/Local/Temp/daily-plan-final-backend.log` 的最终摘要并核对上述计数。警告为已有 Starlette/httpx 弃用提示。本报告永久记录结果，不依赖临时日志长期保留。

持久化的稀疏日历测试在完整套件已经收集测试后追加。审查员独立阅读并运行其临时来源，结果 **1 passed，3.00s**，确认经过生产 deadline 的真实750→1500 provider 请求、1533行已存日历、1044个完整运行日期和500根认证 series 记录。其永久路径为 `tests/integration/test_daily_sparse_calendar_regression.py`。helper 另行运行仓库永久副本：**1 passed，5.94s**，Ruff 通过。审查员比较临时/永久文件 SHA256，确认字节一致（`55fdf3ac047871a7565ba5b093c6d1eadd14a48ece890d0966eb391afa8f080b`）；审查员的3.00s 是临时副本执行，不能混同 helper 的5.94s 仓库执行。该追加回归**不计入6065**。生产源码未变，无需仅因新增测试文件重跑53分钟容量组。

最终审查结论仍为 **F1–F11 CLOSED，无剩余实质问题**。完整实现检查、永久追加用例结果及兼容/运行边界见 [Daily-plan 离线验证](2026-10-01-daily-plan.md) 及其[中文审阅副本](2026-10-01-daily-plan.zh-CN.md)。实时 provider/部署认证仍不属于本次离线任务。
