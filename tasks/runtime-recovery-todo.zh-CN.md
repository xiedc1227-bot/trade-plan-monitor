# 任务表：任意时段重启与自动恢复

> 状态：自 2026-09-21 获得实现授权起 IN PROGRESS。英文规范输入：`runtime-recovery-todo.md`；本文件为中文副本。
> 上位提案：`runtime-recovery-plan.zh-CN.md`。原 D1–D7/A01–A12 及 D8/A13 已获批准；D9/A14 业务意图已确认，但 API 待评审。
> 后续分配遵循提案第 2 节：架构、质疑式评审及疑难故障使用 `gpt-6-astra` / `xhigh`；有界实现使用 `gpt-6-sol` / `high`，已确定内容的文档同步使用 `gpt-6-sol` / `medium`。历史执行记录保留当时实际模型/强度。检查点评审仅在实际执行后才构成证据。

## 执行规则

### 当前交付顺序 — 2026-09-22

执行遵循提案第 7.1 节。以下五项成果作为面向用户的进度口径；下方 RR 任务仍是实现/验收索引，不是额外五个阶段。基线：`1f50439`，分支为 `codex/consolidate-r19-r32`。**业务第 1 步进行中，尚未完成。** 流程调整本身不改变运行行为；实际实现证据记录如下。

| 业务步骤 | 当前状态 | 完成证据 / RR 对应 |
|---|---|---|
| 1. 历史状态恢复 | 有界历史持仓和可归因风险已接入现有评估器；离线验证了跨独立进程重启及评估前突然退出后的恢复。仍缺已批准但尚未接通的五天准入/作废规则、长期活动计划的近期状态来源、支持期初持仓的评估及生产协调器集成 | 在真实临时 SQLite 中还原符合条件的中断所需历史目标状态；遗漏收盘按时间顺序处理；中断/重复恢复不增加规范结果或提醒意图；超过 120 小时安全作废计划；历史未知仅阻止受影响计划。RR007–RR010、C2、A13 |
| 2. 提醒安全 | 已有分类/存储及可选事务基础；缺少最终发送准入 | 两类计划在模拟渠道准入前使用重新读取的风险/持仓/恢复门禁证据；过时提醒抑制，相同且适用的退出提醒只保留最新，证据不足等待；保留不确定发送处理。RR011–RR013 |
| 3. 实际启停集成 | 已有协调器/重试基础；缺少生产生命周期集成 | 同一应用组装能从依赖不可用中恢复、校验重载、隔离旧任务并安全关闭；验收包含受控进程重启。RR004–RR006、RR010、RR014、C1/C3 |
| 4. 状态接口和页面 | 仅有契约草案 | 真实后端状态到达页面，区分待机/恢复中/受阻/连接异常并提供原因和重试信息；旧客户端安全失败。RR002、RR015–RR019、C4 |
| 5. 重启/故障验收 | 仅有局部组件证据 | 完成全部 A01–A14 场景、第 7 节全部离线门禁、迁移/回滚证据及最终独立审查；部署仍须单独批准。RR020–RR022、C5 |

主线顺序为 1 → 2 → 3 → 4 → 5。离线组装/重启测试基础提前到第 1 步，依赖重试测试随第 3 步执行，不等到第 5 步才首次运行。RR002 评审通过后，可并行准备独立的状态/客户端工作，但不能据此宣称第 4 步完成。原任务依赖仍是验收/默认启用门禁，不禁止提前测试注入式集成。

当前实现交接：用户已明确 V1a 时间规则：提醒不是成交；仅人工登记改变仓位，包含登记时间等于截止点的变更，不追溯倒扣此前仓位。有界历史读取器在激活起 32 个自然日内证明持仓、可归因风险和最早缺失收盘。可选服务路径已用准确历史批次、风险来源有效时间、事务保护及初始 `HOLD` 提醒连续补算两个遗漏收盘；跨独立进程重启和评估前突然退出后均不重复结果或意图。资料不足、历史受阻结果以及无法用旧版属性表达的期初持仓，均不能静默视为已完成收盘。仅新增索引的迁移 `0021_inventory_history_index` 已覆盖临时数据库升级/降级；未迁移用户数据库。V1a/V1b 基础已实现；V1c/RR009/C2 在已批准但尚未接通的五天门禁、长期活动计划的近期状态来源、支持期初持仓的评估、生产协调器接入及更完整重启/故障验收前保持未完成。命令及评审发现累积到成对 `docs/verification/runtime-recovery-acceptance.md`。迟到登记不再有待用户选择事项。

### 五天范围修订 — 2026-09-23

- [ ] **V1d — 实现已批准的 D8/A13。** 120 小时边界、持久最后存活证据和未知/旧数据库处理已批准。增量结构 `0022_runtime_liveness`、持久化/判定及临时数据库的边界/损坏/旧库/降级测试已实现；**尚未接入生产心跳或作废门禁**。下一步：事务性作废计划并抑制队列工作，再于活动计划加载/发送前接入准入。本阶段不对用户数据库运行批量作废。
- [ ] **V2a — 评审 D9/A14 提醒页操作契约。** 保持风险与卖出信号独立；区分确认已读、未卖出及登记实际卖出数量。复用带幂等和审计的持仓扣减边界，再测试过时提醒、部分卖出及重复确认。五天准入决策后实现，不改变评估规则。

### 下一项完整成果：一次可证明的遗漏收盘

以下内部工作单元属于 RR009/C2。提交保持有界，不再给每个解码器单列业务里程碑或验证报告。第 1 步勾选完成前须扩展跨日及故障覆盖。

- [x] **V1a — 明确历史重建契约。** 依赖：既有写入/解码证据及 RR001。一次集中评审明确历史观察截止点与已接受生效日期的关系、迟到/非单调登记处理、风险来源有效时间，以及明确的字节/成员/历史预算。保留可变交易单位、原始快照及旧规范哈希。验收：成对规格包含示例时间线和明确的已知/未知结果；未决业务选择在实现使用方前交由用户判断。文件：成对 `docs/specifications/monitoring/SPEC-runtime-recovery.md` 及本成对任务表。验证：示例追踪到写入字段和 D3/D5，核对双语一致性并处理新安全发现；不重复评审未变更决策。
- [x] **V1b — 读取一次完整历史持仓。** 依赖：V1a。将确认/持仓变更解码与持久化持仓读取器一起完成，复用已有批次/期初校验及自有快照保护。验收：真实写入记录能还原请求目标的一致持仓；断链、成员缺失、超预算或矛盾历史返回类型化未知；不接受未提交/外部事务证据。源码范围：`src/trade_plan_monitor/state/`；测试：已有持仓审计/事务/批次历史测试及 NEW 专项持仓历史测试。验证：先失败的写入到读取用例，以及损坏/事务/预算用例，再运行受影响持仓回归组。内部源码/测试提交保持有界，不新增通用历史框架。
- [ ] **V1c — 执行遗漏收盘并重新打开验证。** 依赖：V1b、已评审的风险来源重建及既有 RR008/RR010 保护。在临时存储中接通发现、准确历史输入及初始 HOLD 的现有评估事务；使用模拟行情源，不使用真实发送器。验收：一次遗漏收盘只提交一次；重新打开存储并重复发现不增加结果/意图；提交前退出可回滚、旧激活不能提交、前提缺失仅阻止依赖计划。源码范围：既有 `runtime/service.py`、恢复编排及评估事务边界；NEW `tests/integration/test_missed_close_execution.py`。验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_execution.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_recovery_activation_fences.py -q`；C2 关闭前补齐生产协调器、长期活动计划经验证的近期来源、已批准但尚未接通的五天门禁及进程重启覆盖。仅重新打开 SQLite 不代表完整进程重启验收。

### 验证节奏与交付

- 修改期间：有意义的先失败测试、受影响测试组和静态检查；涉及代次/事务/身份边界时补充对应回归。同一完整成果内测试使用方，不只测试每个解析器。
- 完整成果检查点：运行该成果的集成恢复/故障场景和跨模块回归组；评审接通后的整体修改。一份成对成果报告记录命令、受测版本/修改和结果。修复后重跑受影响检查；无需重复生成未变化的成功证据。
- 最终验收/默认启用前：提案第 7 节全部命令，包括不新增排除项的完整 `not live` 测试及隔离状态下的浏览器验收。既有失败不能豁免或改为跳过。专项通过不关闭 C0–C5。
- 基线失败保持未解决：此前报告 `docs/verification/2026-09-22-opening-balance-decoding.md` 记录排除重型回测文件后的 3734 通过 / 4 失败 / 1 跳过 / 4 未选中。这是历史有范围证据，不是全量通过。涉及有关边界时复现相关失败；最终验收前解决全部四项。不在纯文档修改后反复花费一次全量运行重新发现未变化失败。
- 交付格式：业务步骤；已接通场景（或明确仅为基础组件）；实际证据；剩余决策/失败；下一项完整动作。不按提交/测试数量推算百分比。保持当前分支；本流程调整不授权推送、切换/合并分支、真实行情/渠道操作或部署。

### 实现检查点 — 2026-09-21

成对证据见 `docs/verification/2026-09-21-runtime-recovery-foundations.md`。完成基础切片不代表 C0–C5 通过，也不代表启用生产恢复路径。

| 任务 | 当前状态 |
|---|---|
| RR001 | 已编写成对行情源/恢复规格；完整契约评审尚未完成 |
| RR003 | 已实现并独立评审；完整性、兼容性及并发不覆盖导入测试通过 |
| RR004 | 已实现并评审注入式运行门禁；装配及所选股票失败后的独立调度尚未完成 |
| RR005 | 已实现并评审检查点模型/仓储/迁移及 SQLite 最新 head 断言 |
| RR006 | 已实现/评审持久化准入、`RecoverySchedule` 与注入式单所有者 `RecoveryCoordinator`；生产生命周期集成尚未完成 |
| RR007–RR008 | 纯目标计算及注入式单证券获取验证准确的已提交覆盖；已组合测试协调器/控制器/SQLite 恢复；历史获取/重放及生产集成尚未完成 |
| RR010 | 参考键已绑定计划类型/内容、真实激活与股票语义；已评审等待后的缓存/准入校验；更完整的 generation/重配置义务尚未完成 |
| RR002 | 已增加成对的详细状态/协议草案供评审；未改变协议源码/默认路径，不关闭 C0/C4 |
| RR011–RR013 策略/存储切片 | 显式风险分类器与旧版来源证明已独立评审；已增加隔离的旧版适用性分类器、交付迁移/仓储及可选原子 HOLD 入队；RR012 初始 HOLD 评估事务接线已实现并独立审查，未在生产装配启用；当前证据持久化重建及发送器集成仍未完成 |
| RR009 | 已增加有界发现及只读 SQLite 发生/激活证据读取器；超出证明预算的直接来源、历史状态重建及顺序执行尚未完成 |
| RR011–RR022 | 尚未完成；继续遵守下方依赖，不以此增量检查点作为发布批准 |

- 用户于 2026-09-21 授权实现已批准提案/职责图。由其细化的行情源/恢复契约与隔离、注入式基础切片同步落地；未评审的协议/业务变化及生产默认切换仍受门禁约束。此授权不包括真实迁移或部署。
- 每个编码任务先编写有意义的失败测试；保留无关修改及旧规范身份的黄金测试。不能因测试描述旧行为而跳过：只用已批准新契约测试替换明确被取代的断言。
- 下列路径相对仓库；NEW 表示拟新增。内部代码修改控制在约 3–5 个源码/测试文件；超出时在同一完整成果内拆分，不新增业务里程碑。相关修改同步成对规格/契约；RR017/RR021 保留生成契约/运维验收义务。
- 新路径通过相应检查点前，复用当前默认生产行为。通过依赖注入和现有组装提前集成，不永久维护第二套生产框架。只有 RR020 且所有前置契约和保护就绪后，才启用新默认路径；不能等到 RR020 才首次集成测试。
- 每个任务记录修改路径、精确命令、实际结果及剩余失败。执行无法确认时，不得声称使用了指定模型/强度。

### 继续实现检查点 — 2026-09-21

本轮增加隔离的 RR006/RR008/RR010 切片，不将这些完整任务标记完成。细节与实际验证见 `docs/verification/2026-09-21-runtime-recovery-increments.md` 及其中文副本。新协调器在类型化依赖重试期间持续存活，本地维护上限为 30 秒，存储/程序错误仍明确暴露。按范围获取不会将部分、未来或日期错误的数据判为就绪。排队期间的本地取消保留原有行情源退避。参考缓存不能跨计划类型或真实激活变化复用。

显式风险最新状态和旧版只读来源切片均经独立评审；用户批准的重复退出提醒只补最新一条规则已记录，但未接入发送。最终功能验证为 3095 通过、4 项既有失败；未改动的重型回测文件已在此前全量运行中通过。R32 依赖真实日期的测试已修正，未改动实际执行门禁。本检查点不授权默认切换、真实操作、合并或部署。

### 交付安全检查点 — 2026-09-21

后续隔离增量增加迁移 `0019_alert_delivery_eligibility`、带 revision 校验的分类/审计、有界缺失记录初始化，以及显式启用的 `enqueue_recoverable`。规范提醒/结果身份及现有生产默认行为不变。可操作提醒的来源过期与状态风险适用性分离；已存 ELIGIBLE 不是持续有效的发送许可。旧版纯策略核对原始证据、最新官方风险阶段、当前持仓/T+1，以及已批准的重复退出只保留最新一条规则。其日历和当前状态输入仍靠注入，不是已完成的持久化读取器。

详见 `docs/verification/2026-09-21-recovery-delivery-metadata.md` 及 ADR 0007 和对应中文副本。评估事务、当前权威事实、最终逐渠道准入及端到端崩溃/重启证据完成集成之前，RR011–RR013 和 C0/C2/C3 仍未完成。本增量不授权真实迁移、通知、生产切换或部署。

### 评估事务检查点 — 2026-09-21

本次继续工作前，已按要求将 `964fde2` 和 `6dff7ae` 同步到既有 GitHub 分支。RR012 继续采用隔离事务切片：严格的构造参数显式启用后，将旧版两条评估路径及显式提醒写入接到既有 HOLD 辅助方法。辅助方法在初始化元数据前规范化入队层的带时区时钟。判断回滚须涵盖认领/结果/转换/提醒/元数据/审计，不回滚此前已提交的行情事实。细节及最终验证记录在成对 `docs/verification/2026-09-21-recovery-evaluation-transactions.md`。

当前仍处于恢复核心/通知安全阶段，尚未完成生产集成：这些切片不关闭 C0–C5。既有工厂不启用选项；该选项不使发送器强制执行 HOLD。当前权威事实重建、最终发送准入、生命周期/状态/UI 接线和进程重启验收仍是 RR020 的前置条件。按要求推送之后产生的本地提交，不自动推送或部署。

### 遗漏收盘发现检查点 — 2026-09-21

隔离的 RR009 扫描器不依赖待处理标记，即可发现已到期的旧版收盘候选。实际激活、历史策略、权威日历及准确完成证据仍是不同输入。每次最多覆盖 32 个自然日；窗口结束不证明整体恢复完成。无法归属和可能乱序的历史均显式呈现。它不将今天的状态送入当前评估器处理历史日期，不改变生产启动路径，也不发送通知。证据记录在成对 `docs/verification/2026-09-21-missed-close-discovery.md`。

RR009 保持未勾选：有界持久化归属见下一检查点；权威历史状态重建及带激活/generation 校验的顺序执行仍未完成。既有仅哈希认领、缺口之后已有结果、当前持仓上下文及风险写入时间语义，均须在不重写规范身份、不改变交易规则的前提下处理。扫描器不是恢复屏障或发布门禁。

### 持久化收盘证据检查点 — 2026-09-21

下一 RR009 切片共享已有测试覆盖的激活链证明，并在一个自有 SQLite 快照中读取激活范围、日历、认领、完整结果及发布。发生证明不依赖是否创建提醒或风险信号类型。缺失/损坏/过大/错误激活证据保持未知，确认不存在还必须经过有界孤立发布检查。正常长期运行也可能保守地耗尽发布历史预算；这是已记录的启用前直接来源要求，不声称任意长度历史都已可恢复。

详见成对 `docs/verification/2026-09-21-close-recovery-evidence.md`。RR009 的权威历史状态重建及安全顺序执行仍未完成；未启用回放、真实通知、结构迁移或生产默认行为。当前快照事实不是持久有效的修改/发送许可。

### 持仓批次证据检查点 — 2026-09-22

RR009 的下一项前置工作在既有审计事务中，为未来手工批次买入和减仓保存版本化命令日期及完整前后快照。它保留批次哈希、事件身份、持仓规则和幂等行为，不重建历史组合，也不启用回放。旧记录不变，不能从写入时间获得缺失的减仓日期。契约见配套双语运行时恢复规范；验证记录见双语 `docs/verification/2026-09-22-position-lot-recovery-evidence.md`。

后续历史状态工作仍须验证这些记录，证明逐批次/持仓历史完整性，明确期初余额和确认语义，并单独处理风险来源有效日期。现有证据预算和因果缺口仍会阻断未知范围。RR009 和 C2 保持未勾选；不启用生产恢复、真实服务、迁移或真实发送。

### 持仓批次解码检查点 — 2026-09-22

隔离的纯解码器校验单条版本化批次变更审计：有界严格 JSON、元数据绑定、准确的旧版哈希及买入/减仓不变量。旧版证据缺失、版本不支持和数据无效返回类型化未知，不从写入时间推断。它兼容既有非 UUID/自定义交易单位约定，不改变变更准入。测试先行及独立审查证据见双语 `docs/verification/2026-09-22-position-lot-evidence-decoder.md`。

本检查点仅完成单条记录解码。持久化逐批次读取器仍须在同一快照内证明有界唯一链条、已提交发布及与当前批次的一致性。仅限制审计查询返回行数不能限制数据库扫描工作量；既有审计表没有实体类型/实体 ID 索引。完整持仓、期初余额/确认、风险来源有效日期和安全顺序执行仍未完成。RR009/C2 和生产集成尚未完成。

### 单批次历史检查点 — 2026-09-22

RR009 的下一增量在自行管理的单个 SQLite 快照内读取一个批次的完整已存审计/发布链。要求唯一买入根节点、每次准确减仓、当前行一致及有序确定性发布。证据缺失、冲突、损坏或超过预算时保持未知。该证据不是完整持仓，也不是回放/发送许可。不会用七天客户端回放过滤器排除更早的已存发布。

增量迁移 `0020_lot_history_indexes` 支持准确审计范围及按序聚合事件查询；仅改变索引，在临时数据库验证。读取器、迁移及审查证据见双语 `docs/verification/2026-09-22-position-lot-history.md`。完整持仓、期初余额/确认、风险来源有效时间语义及顺序执行仍阻止 RR009/C2 关闭及生产集成。

- 此处识别的事务归属待办由下方检查点处理；单批次增量本身并未认证相邻读取器。

### 恢复读取器事务归属检查点 — 2026-09-22

`LegacyCloseRecoveryReader`、`LegacyAlertOriginReader` 和 `PositionLotHistoryReader` 共用小型预检，要求会话全新，且每个 mapper/表级绑定均使用同一个应用 SQLite Engine。在进入上下文或执行 SQL 前拒绝外部 Connection 和跨引擎绑定，不改变调用方事务。真实测试复现了两个旧读取器在修复前错误证明未提交证据的问题。本次关闭已识别的绑定缺口，不代表历史状态重建或整个恢复读取器信任边界完成。

详见成对 `docs/verification/2026-09-22-recovery-reader-transactions.md`。RR009 下一切片须先保存期初持仓和持仓确认历史，才能重建完整历史持仓。风险来源有效时间、历史预算、因果顺序执行及更广泛的集成门禁仍未完成。不启用生产默认路径、行情/通知渠道操作、数据库结构迁移或部署。

### 持仓写入证据检查点 — 2026-09-22

未来确认保存完整原始前后行及新建的期初持仓。期初持仓减仓保存已接受的交易日期、交易单位及原始前后行。每次批次买入/减仓和期初持仓减仓，还独立记录关联来源的持仓变化，包括确认缺失/过期的情况。既有准入、响应、哈希、发布身份、ID/时钟调用次数和事务归属不变；不包含迁移或历史猜补。

详见双语 `docs/verification/2026-09-22-inventory-recovery-evidence.md`。本增量完成写入保存，不表示完成历史持仓重建。RR009/C2 保持未勾选：有界解码、来源/链条校验、完整性截止点、迟报/倒序登记、风险来源有效时间及顺序执行仍未完成。最终发送准入、生命周期/状态集成及实际进程重启验收属于后续门禁；未启用真实行情源、真实通知、生产默认路径或部署。

### 期初持仓减仓解码检查点 — 2026-09-22

`decode_opening_balance_mutation` 现可校验单条有界期初持仓减仓审计，返回不可变自洽证据或类型化未知。保留原始时间戳，同时校验既有 DTO 哈希、准确范围和变更算术。继续支持当日可卖、不同交易单位、非整百余额及相互独立的写入/关闭/有效日期。复用严格解析基础函数，不修改既有写入器或批次解码器。

详见双语 `docs/verification/2026-09-22-opening-balance-decoding.md`。这是三种持仓相关解码切片中的第一种，不是持久化历史读取器。确认和持仓变更收据解码、来源/链条证明、明确的完整性策略及顺序执行仍未完成；RR009/C2 保持未勾选。不包含分支创建/切换、迁移、生产恢复、真实通知、推送或部署。

## 规格门禁

- [ ] RR001 — 确定语义和恢复规格。强度：`xhigh`。依赖：提案/职责图批准。
  - 验收：D1–D6、A01–A10 精确；模块接口、实际激活边界、全部信号投递分类和增量迁移明确批准，不靠推测。
  - 文件：在 `docs/specifications/monitoring/` 下 NEW 成对 provider-contract 规格和成对 runtime-recovery 规格（4 个文件）。
  - 验证：逐项追踪决策/验收 ID，检查双语一致，取得规格批准。
- [ ] RR002 — 确定状态/协议及发布契约。强度：`xhigh`。依赖：RR001。
  - 验收：D7 定义可区分状态、精确协议/版本协商、旧客户端安全刷新、两类计划及局部不可用行为；旧全局 `readOnly` 字段无歧义。
  - 文件：NEW 成对 runtime-status 规格及 `docs/specifications/monitoring/SPEC-local-web.md` / `SPEC-local-web.zh-CN.md`（4 个文件）。
  - 验证：评审有效/无效状态及新旧客户端消息示例、A11–A12 可追踪性和双语一致。

### 检查点 C0 — 契约已批准

- [ ] 对照用户已批准提案完成 RR001–RR002 评审；数据源语义、提醒资格、数据库结构及兼容性变化明确。2026-09-21 的实现指令允许推进隔离基础切片；本门禁通过前不切换生产默认路径、不扩大未批准语义。

## 行情源与恢复基础

- [x] RR003 — 引入兼容语义记录导入。强度：`high`。依赖：C0（2026-09-21 指令授权隔离基础切片）。
  - 验收：A01–A02；迁移幂等、仅导入已验证范围、原证据不变；语义版本忽略元数据但检查适配器兼容性。
  - 文件：NEW `src/trade_plan_monitor/runtime/provider_contract.py`、`src/trade_plan_monitor/live_profiles.py`、`tests/unit/test_live_certification_profiles.py`、NEW `tests/unit/test_provider_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_live_certification_profiles.py tests/unit/test_provider_contract.py -q`。
- [ ] RR004 — 替换整份证据运行门禁。强度：`high`。依赖：RR003。
  - 验收：股票/指数门禁独立；旧 READY 不授予当前健康；元数据刷新无害，不兼容变化在物理请求前被拒绝。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/web/monitor_composition.py`、`tests/integration/test_production_certification_gate.py`、`tests/integration/test_certified_production_runtime.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_certified_production_runtime.py -q`；RR020 前使用注入的组装。
- [x] RR005 — 持久化有界行情恢复检查点。强度：`high`。依赖：RR003、临时数据库迁移批准。
  - 验收：重启保留冷却/重试状态，不保存凭证；迁移增量、幂等，拒绝破坏性丢失待完成状态。
  - 文件：`src/trade_plan_monitor/state/migrations/versions/` 下 NEW 迁移、`src/trade_plan_monitor/state/models.py`、NEW `src/trade_plan_monitor/state/runtime_recovery.py`、NEW `tests/integration/test_runtime_recovery_storage.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_storage.py -q`，使用临时数据库升级/重启用例。
- [ ] RR006 — 增加受控协调/重试准入。强度：`high`。依赖：RR004–RR005。
  - 验收：A04–A05；故障键稳定、单次权限复检、保留共享冷却、工作有界且合并；不陷入永久权限封锁循环。
  - 文件：NEW `src/trade_plan_monitor/runtime/reconciliation.py`、`src/trade_plan_monitor/runtime/request_control.py`、`tests/unit/test_monitor_runtime.py`、NEW `tests/unit/test_runtime_reconciliation.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q`，使用假时钟和物理请求计数。

### 检查点 C1 — 行情源恢复

- [ ] A01、A02、A04、A05 离线通过；串行请求/冷却上限不变；使用 `xhigh` 检查迁移和新记录完整性。

## 交易时段与业务状态恢复

- [ ] RR007 — 计算交易时段感知恢复目标。强度：`high`。依赖：C1。
  - 验收：A03/A10；日历未知仍有重试唤醒，待机不意味着可操作实时数据，跨日和回拨不使用未来数据。
  - 文件：`src/trade_plan_monitor/runtime/scheduler.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、`tests/unit/test_monitor_runtime.py`、`tests/unit/test_runtime_reconciliation.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py -q`，覆盖完整时段矩阵。
- [ ] RR008 — 用有界步骤恢复精确局部覆盖。强度：`high`。依赖：RR007。
  - 验收：空/部分记录不能证明就绪；截止点冻结；各范围公平推进，不由启动全股票批次独占，保留指数现有重试上限。
  - 文件：`src/trade_plan_monitor/runtime/recovery.py`、`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、NEW `tests/integration/test_runtime_recovery_coverage.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_recovery_coverage.py -q`；包含部分/跨日获取及容量受限用例。
- [ ] RR009 — 发现完整错过的收盘义务。强度：`high`。依赖：RR008。
  - 验收：15:20 前停止/17:00 后重启及多日停机，按因果顺序恢复符合条件的缺失收盘；未知历史状态仅阻止依赖计划。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、NEW `tests/integration/test_missed_close_recovery.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_missed_close_recovery.py -q`；RR012–RR013 前不投递历史提醒。
- [ ] RR010 — 隔离依赖变化及两类计划恢复。强度：`high`。依赖：RR008–RR009。
  - 验收：A06/A09；参考键覆盖需求和激活；同股票显式转旧计划补取缺失资料；旧代次不能提交当前决策。
  - 文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/production_context.py`、`tests/integration/test_explicit_runtime_production.py`、NEW `tests/integration/test_recovery_activation_fences.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_explicit_runtime_production.py tests/integration/test_recovery_activation_fences.py -q`。

### 检查点 C2 — 恢复目标正确

- [ ] A03、A06、A07、A09、A10 离线通过；使用 `xhigh` 独立检查收盘发现、状态重建及激活语义。

## 通知安全与生命周期

- [ ] RR011 — 增加持久投递资格，不改变哈希。强度：`high`。依赖：C0、C2、迁移批准。
  - 验收：历史资格/过期/抑制持久化，事件载荷/哈希不变；旧待发送记录按安全关闭方式分类，不删除。
  - 文件：NEW 增量迁移、`src/trade_plan_monitor/state/models.py`、`src/trade_plan_monitor/notifications/outbox.py`、`tests/unit/test_notification_outbox.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/unit/test_notification_outbox.py -q`，包含迁移中断/黄金载荷用例。
- [ ] RR012 — 两类评估事务都应用提醒资格。强度：`high`。依赖：RR010–RR011。
  - 验收：A08；状态/声明和投递资格原子提交；保留历史结果哈希、真实风险通知及显式激活身份；不提交无条件可投递的陈旧意图。
  - 文件：`src/trade_plan_monitor/runtime/service.py`、`src/trade_plan_monitor/runtime/explicit_service.py`、`tests/integration/test_explicit_runtime_production.py`、NEW `tests/integration/test_recovery_alert_eligibility.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_eligibility.py tests/integration/test_explicit_runtime_production.py -q`。
- [ ] RR013 — 停机后待发送提醒增加投递门禁。强度：`high`。依赖：RR012。
  - 验收：过时未发送操作消息被抑制且有审计原因；风险消息等待每计划当前状态恢复门禁及最新状态复核（D1 突破/D2 解除）；两类计划加载器及现有不确定发送处理正常。
  - 文件：`src/trade_plan_monitor/notifications/dispatcher.py`、`src/trade_plan_monitor/notifications/outbox.py`、`tests/integration/test_notification_delivery.py`、`tests/integration/test_recovery_alert_eligibility.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_recovery_alert_eligibility.py -q`，仅使用假渠道。
- [ ] RR014 — 降级启动期间保持协调器运行。强度：`high`。依赖：RR006–RR013。
  - 验收：A04/A11；本地启动独立于行情 IO；唯一所有者、可中断等待、进展截止时间及安全停止；预期错误不耗尽崩溃监督预算。
  - 文件：`src/trade_plan_monitor/runtime/service.py`、`src/trade_plan_monitor/runtime/reconciliation.py`、`src/trade_plan_monitor/web/monitor_composition.py`、`tests/integration/test_runtime_lifecycle.py`、`tests/integration/test_monitor_production_composition.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q`，针对注入的新生命周期；公开默认切换保留到 RR020。

### 检查点 C3 — 安全自主运行

- [ ] A04、A08–A11 离线通过；使用 `xhigh` 审查提交/崩溃/发送窗口、代次变化和物理工作线程清理。

## 状态与用户可见恢复

- [ ] RR015 — 如实投影生命周期和局部状态。强度：`high`。依赖：C3、RR002。
  - 验收：存活/恢复/待机/阻止区分有效；全局布尔值不授权工作；正常连接不能掩盖协调器进展逾期。
  - 文件：`src/trade_plan_monitor/runtime/health.py`、`src/trade_plan_monitor/web/routers/health.py`、`tests/integration/test_runtime_lifecycle.py`、NEW `tests/integration/test_runtime_status_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_runtime_status_contract.py tests/integration/test_runtime_lifecycle.py -q`。
- [ ] RR016 — 返回兼容两类计划的局部总览投影。强度：`high`。依赖：RR015。
  - 验收：A06/A12；等待/新股票不隐藏健康条目，显式规则结果读取正确存储，缓存决策不升级为可操作。
  - 文件：`src/trade_plan_monitor/web/persistent_monitor_read_service.py`、`src/trade_plan_monitor/web/routers/dashboard.py`、`src/trade_plan_monitor/web/routers/symbols.py`、`tests/integration/test_persistent_monitor_read_service.py`、`tests/integration/test_runtime_status_contract.py`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_persistent_monitor_read_service.py tests/integration/test_runtime_status_contract.py -q`；保留现有未提交指数读取测试。
- [ ] RR017 — 版本化传输并重新生成契约。强度：`high`。依赖：RR016。
  - 验收：精确实现 RR002 版本握手、安全拒绝不兼容客户端、序号/代次刷新语义；OpenAPI 和生成类型一致。
  - 文件：`src/trade_plan_monitor/web/websocket.py`、`tests/integration/test_websocket.py`、`tests/integration/test_openapi_snapshot.py`、`openapi.json`、`web/src/api/generated.ts`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_websocket.py tests/integration/test_openapi_snapshot.py -q`；批准生成后运行 `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check`。
- [ ] RR018 — 前端分离传输与业务恢复状态。强度：`high`。依赖：RR017。
  - 验收：保留代次刷新、重连和快照序号保护；后台降级不会形成含糊不清的无限 STALE/重连循环。
  - 文件：`web/src/composables/useMonitorStream.ts`、`web/src/stores/monitor.ts`、`web/tests/unit/useMonitorStream.spec.ts`、`web/src/api/health.ts`。
  - 验证：`npm --prefix web run test -- --run tests/unit/useMonitorStream.spec.ts`；`npm --prefix web run type-check`。
- [ ] RR019 — 展示待机、重试和局部进展。强度：`high`。依赖：RR018。
  - 验收：原因/下次重试或必要操作明确；没有工作时不展示恢复横幅；缓存截止时间可见，健康条目仍可用。
  - 文件：`web/src/views/SystemRouteView.vue`、`web/src/components/health/MarketStatusStrip.vue`、`web/tests/unit/SystemHealthRoute.spec.ts`、NEW `web/tests/unit/RuntimeRecoveryStatus.spec.ts`（若需额外指数卡片工作，另拆任务）。
  - 验证：`npm --prefix web run test -- --run tests/unit/SystemHealthRoute.spec.ts tests/unit/RuntimeRecoveryStatus.spec.ts`；`npm --prefix web run type-check`。

### 检查点 C4 — 端到端状态契约

- [ ] A06、A11、A12 及类型/契约门禁通过；`xhigh` 评审检查旧缓存客户端、显式计划读取及真实进展与连接活动的区别。

## 集成与交付

- [ ] RR020 — 启用完整路径并离线证明真实进程重启。强度：`high`；故障分析/评审：`xhigh`。依赖：C4。
  - 验收：所有目标时段覆盖 A01–A14；在提交和投递窗口停止/终止/重启；迁移中断安全；不访问行情源，不发送真实通知。
  - 文件：`src/trade_plan_monitor/web/monitor_composition.py`、NEW `tests/integration/test_anytime_runtime_recovery.py`、`web/tests/e2e/production-restart.spec.ts`、`web/tests/e2e/r13-active-process-restart.spec.ts`、NEW `web/tests/e2e/runtime-recovery.spec.ts`。
  - 验证：`.\.venv\Scripts\python.exe -m pytest tests/integration/test_anytime_runtime_recovery.py -q`；`npm --prefix web run test:e2e -- production-restart.spec.ts r13-active-process-restart.spec.ts runtime-recovery.spec.ts`，使用隔离测试状态。
- [ ] RR021 — 同步运维与验证证据。强度：`high`。依赖：RR020。
  - 验收：重启/首次数据源验证/重新配置/回滚说明准确；仅记录实际执行的测试；中英文一致。
  - 文件：`docs/operations/live-certification.md`、`docs/operations/live-certification.zh-CN.md`、NEW 成对 `docs/verification/runtime-recovery-acceptance.md` / `runtime-recovery-acceptance.zh-CN.md`。
  - 验证：对照两种语言的 ID/命令/阈值/字段；逐项追踪 A01–A14 结果证据。
- [ ] RR022 — 运行全量离线门禁和最终质疑评审。强度：`xhigh`。依赖：RR021。
  - 验收：提案第 7 节全部门禁通过，保留现有无关修改，无未解决实质问题，差异不包含密钥或放宽的测试；真实环境限制如实列出。
  - 文件：成对验收报告及本成对任务表（4 个文件）；不在评审任务中夹带修复，修复返回有界实现任务。
  - 验证：执行提案第 7 节全部完整命令，检查差异和崩溃矩阵；可核验时记录实际模型/强度及用户评审结果。

### 检查点 C5 — 可进入部署评审，尚未部署

- [ ] 用户评审已完成的离线证据。生产备份、真实行情验收和上线另行授权。仅当明确批准的范围实际达成时，才将专项标为完成。
