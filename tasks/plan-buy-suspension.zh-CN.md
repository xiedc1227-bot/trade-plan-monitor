# 计划持续禁买——实施任务清单

状态：**已批准——PBS-T01完成；下一步PBS-T02** · 2026-11-15。[中文规格](../docs/specifications/monitoring/SPEC-plan-buy-suspension.zh-CN.md) · [英文任务正式输入](plan-buy-suspension.md)。

## 1. 授权与限制

用户于2026-11-15明确批准PBS-D01–PBS-D06全部推荐决定，并授权原调度会话将每项独立派发任务推进到完成或真正需要用户决定的阻断。任务仅实施获批的最小 `plan-buy-suspension` 增补，不重开无关PMA范围，不把既有PMA任务／检查点标记完成。保留原始03/04、历史契约及全部历史验收证据。PBS-T01仅文档：本任务不授权代码实现、业务测试、用户数据库访问／迁移、真实提取／行情调用、启动服务或提交／推送。

由原派发会话继续调度，每项实施任务使用独立任务会话；优先使用 `gpt-6.1-sol`，行为实现／审查使用 `high` 推理，纯文档同步使用 `medium`。合适时复用已有获授权任务会话。重叠文件同时只能有一个写入者。每个派发的代码／测试切片最多5个确切路径，修改前冻结路径。超出上限时，在同一要求内拆分编号子切片。配套文档归属更新独立成最多4个路径的切片。以上是派发边界，不要求为此新建模块或额外文档。任务会话回传证据后待命，不自行派发下一项。

复用现有领域、状态、审核及运行边界。不新增通用引擎、调度器、行情提供方、全局禁买服务、公共解锁入口、公共冻结格式或新底部识别器。下列模块路径是候选归属，不代表可以修改全部所列模块。新契约确切编号、文件清单和定向测试路径在PBS-T01及后续每次派发时冻结；缺少无关能力时继续阻断，不能静默扩大范围。

## 2. 顺序实施任务

仅PBS-T01已完成。要求以规格为准，实施不能换成更容易通过的验收标准。

| 状态／编号 | 工作与现有归属 | 依赖 | 验收／交付物 |
| --- | --- | --- | --- |
| [x] PBS-T01 | 已记录2026-11-15对PBS-D01–PBS-D06的批准，冻结新计划／草稿／状态／提示词编号、确切支持组合、接替绑定及T02.1路径。仅修改本规格／任务双语文件，共4个。 | 已获用户批准 | 规格第6.1节及下文第2.1节记录冻结内容和已核对HEAD。已检查原文哈希、双语结构／编号／链接及文档范围；不实现代码、不运行业务测试。日期已经明确批准，公共冻结支持仍排除。 |
| [ ] PBS-T02 | 增加有限的新普通计划保护契约、校验、草稿分派及可执行编解码／哈希处理。从第2.1节冻结的五个T02.1路径开始；修改可执行编解码／哈希归属及兼容测试前，单独冻结T02.2切片。保留历史共享基类。 | T01 | PBS-A02/A10：新契约准确往返；保护条件／起点必填约束；不扩展Schema6–9；不支持的组合拒绝；旧契约语义不变。T02.1单独完成不代表T02完成，也不允许启用。 |
| [ ] PBS-T03 | 在现有提取归属内，增加新当前契约对应的版本化输出／提示词支持，v12不变；补充离线样本测试。 | T02 | PBS-A01/A10：保留完整持续义务，不编造未明确的周期／起点，不以瞬时条件／SELL／背景替代；不调用真实服务。 |
| [ ] PBS-T04 | 扩展来源覆盖和现有审核／补充流程，绑定特定原文哈希的澄清及接替意图。归属：现有 `state/source_coverage_*.py` 及审核校验。 | T02–T03 | PBS-A01/A08：澄清缺失或绑错原文则阻断；仅消除对应义务；原始03/04其他阻断保留；原文直接结果与澄清后证据分开。 |
| [ ] PBS-T05 | 持久化 `DailyBuySuspensionState` / `buy-suspension-state-v1`，包含隔离存储中新增的 `BUY_SUSPENSION` kind／约束／载荷分派；实现单一确定性状态转移函数及按时间顺序的工程回放测试。归属：`state/daily_state_models.py`、`state/daily_models.py`、`state/daily_repository.py` 及现有决策／状态边界，拆分有界切片。 | T02 | PBS-A02–A04/A07：精确纳入／价格边界、持久锁存、连续进度／证明、不使用未来数据、触发证据修订不解锁；“已核查无跌破”证明失效／修订则阻断并复核；无关上下文不串扰。仅临时测试状态，不迁移用户数据库。 |
| [ ] PBS-T06 | 在 `runtime/daily_service.py`、`runtime/recovery.py`、现有已核实历史／数据适配器及 `state/repositories.py` 接入完整K线处理和有界历史／停机补查，包括重启。按规格第4节增加保护条件专用的事务失效／内容证明围栏；不存在可直接调用的历史区间修订证书。拆分有界切片。 | T05 | PBS-A03/A04/A07：可取得且稳定的历史经有限个有界批次完成；缺口／价格基准／日历不确定或批次预算耗尽则阻断BUY且不截断；补查发现跌破后即使回升仍禁买；经实际分钟写入路径将已核查 `2430` 改为 `2419`，证明BUY前资格已失效、重新核查后锁存。测试重启及补查／提交过程中变化。永久输出未核实不算实现可恢复区间。 |
| [ ] PBS-T07 | 在信号生成、实际BUY提交及排队可行动通知发送前执行保护。归属：`decision/unified_lifecycle.py` 及现有运行／网页提交／通知边界；必要时拆编号子切片。 | T05–T06 | PBS-A05/A06：两笔批次、旧信号／请求均受限；同根K线及并发跌破／BUY顺序正确；不重复成交、不回滚；符合条件的SELL／风险保持独立。 |
| [ ] PBS-T08 | 经现有审核、前序计划及启用事务，实现普通更新继承和确切已审核接替启用。归属：`state/daily_review_store.py`、`web/daily_service.py` 及现有各计划类型启用适配器。 | T04–T07 | PBS-A04/A08：普通03 → 04继承；复制／重建／降级不能清锁；前序修订／审核过期则拒绝；新保护条件须核查自身区间；测试明确不再设置保护的废止分支、承认前序未核实状态且不清除历史的接替，以及起点之前拒绝BUY；不建通用谱系系统。 |
| [ ] PBS-T09 | 将保护状态及证据投影至现有只读就绪结果。归属：`web/plan_readiness_models.py`、`web/plan_readiness_service.py`、`web/plan_readiness_summary.py` 及定向API测试。 | T06–T08 | PBS-A09：监控健康但禁买与未知／未就绪不同；GET不拉行情、不转移状态、不写入；过期投影不能作为提交许可。 |
| [ ] PBS-T10 | 同步公共当前契约归属及两种生成前端契约；拒绝新契约进入不兼容冻结适配器。归属代码、生成产物及双语API文档分别使用子切片。 | T02/T09 | PBS-A10：生成检查通过；旧字节／哈希不变；不发生丢字段的旧契约导出或意外公共冻结支持；不能把归属代码、全部生成文件和文档塞入超限切片。 |
| [ ] PBS-T11 | 在 `web/src/components/plans/` 现有计划审核／就绪组件内展示触发／起点／证据、监控健康、BUY禁令及接替要求；补定向组件测试。 | T08–T10 | PBS-A09/A11：不设解锁按钮或新页面；现有审核与启用保持分开；强制原文错误仍阻断；前端测试／类型／构建通过。 |
| [ ] PBS-T12 | 完成隔离的端到端工程验收、兼容检查及独立审查；独立有界切片编写语义一致的中英文验收报告。 | T01–T11 | 确切候选版本的PBS-A01–A12证据；真实浏览器场景和项目四种视口；运行／回放、并发、SELL独立、旧哈希及不支持导出拒绝；明确列出未解决原文／PMA门禁。 |

T02稳定后，T05可以独立于T03–T04准备，但并行代理不得写共享文件。默认按顺序推进，以减少集成风险。六项决策获批后，范围内常规步骤无需重复用户确认；新增交易解释、公共冻结格式或用户数据操作仍须单独决定范围。

### 2.1. PBS-T01完成记录与首个实施切片

已核对代码基线：`ec1eca437940bd5fd79c556c0d5ebbcd41949a68`。T01唯一写入路径为 `docs/specifications/monitoring/SPEC-plan-buy-suspension.md`、`docs/specifications/monitoring/SPEC-plan-buy-suspension.zh-CN.md`、`tasks/plan-buy-suspension.md` 和 `tasks/plan-buy-suspension.zh-CN.md`。派发时四文件均为已存在的未跟踪PBS草案，不包含无关改动。

已批准口径：完整5分钟收盘严格 `<2420`、本计划全部BUY、仅确切新计划审核后启用可恢复、原始03起点 `2026-09-30T09:30:00+08:00`、普通03 → 04继承，以及原文哈希绑定的澄清／报告。恢复包括明确废止旧保护或承认前序未核实区间，两者均不能把历史证据改为已核查无跌破。规格第6.1节冻结 `schema_version=10` / `condition-plan-v6`、`BuySuspensionTradePlan`、`BuySuspensionPlanDraft`、`plan-review-content-v7`、`buy-suspension-state-v1`、`plan-extract-v13`、`plan-buy-suspension-extraction-v1`、`monitor-loop-update-extraction-v2` / `monitor-loop-update-extract-v2` 和 `buy-suspension-replacement-v1`。这些是待实现的新契约，不是已有代码入口。

首个切片为 **PBS-T02.1——领域／草稿准入**，相对 `trade-plan-monitor/` 恰好五个写入路径：

1. `src/trade_plan_monitor/domain/unified_plan_models.py`——独立的 `BuySuspensionDefinition` 和 `BuySuspensionTradePlan`，保留Schema5基类字段。
2. `src/trade_plan_monitor/domain/unified_plan_validation.py`——独立的 `BuySuspensionDraftDefinition` / `BuySuspensionPlanDraft`、确切转换及校验／from-executable分派。
3. `src/trade_plan_monitor/domain/plan_hash.py`——增加Schema10可执行 `plan-review-content-v7` 哈希域及精确当前哈希准入，保留所有旧哈希域／内容。共享 `CurrentPlanDraft` 联合类型延至T02.2，确保同一切片保持历史v12封装限定Schema5–9。
4. `src/trade_plan_monitor/domain/daily_plan_validation.py`——确切Schema10草稿加载、错误分派及 `plan-review-content-v7` 草稿哈希域，保留旧规范化／哈希。
5. `tests/unit/test_plan_buy_suspension_contract.py`——新增领域／草稿边界的确定性测试。

T02.1验收：可执行类型 ↔ 草稿 ↔ JSON载荷解析，经新模型转换及 `load_daily_draft_json` 后保留保护条件与明确起点，可执行／草稿审核内容哈希一致；允许表示不完整草稿定义，但不能转为可执行计划；拒绝版本错误、保护类型／周期错误、非边界／非 `+08:00` 起点和不支持的类型组合。有效5分钟边界不能静默取整。确认原文要求却遗漏保护仍是T04明确的覆盖阻断，不声称结构模型能推断原文义务。测试旧Schema5–9拒绝新字段及旧载荷／哈希行为不变。本切片不扩大历史v12封装，也不把Schema10路由至服务启用／冻结流程。`2419/2420/2421` 的工程阈值判断由T05完成，不能以模型校验冒充。

新测试首先证明失败后，使用定向命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_buy_suspension_contract.py tests/unit/test_unified_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_market_linkage_contract.py tests/unit/test_market_exception_contract.py tests/unit/test_p2_policy_contract.py tests/unit/test_p3_policy_contract.py -m "not live" -q
```

后续T02.2须在另行冻结的最多五文件切片中处理 `src/trade_plan_monitor/domain/plan_codec.py`、`src/trade_plan_monitor/domain/market_linkage_validation.py`、`src/trade_plan_monitor/ai/plan_extraction.py` 的历史封装准入及确切路径测试。增加Schema10的 `CurrentPlanDraft` / `parse_current_draft` 分支时，保持既有v12封装解码限定Schema5–9；联动／P2／P3草稿类型不增加保护字段。不能把T02.1局部转换声称为公共可执行编解码往返。后续T03/T04负责新的版本化提取及来源／接替凭据，T05/T06负责实际历史证明／失效，T08负责运行启用绑定。`RecoveryService.recover_scope` 仅修复当日缺口；历史交易日复用已核实的 `HistoricalMinuteBatch` / `HistoricalMinuteProvider.historical_minute_batch` 及日历接入点，进行有界适配。T01不调用提供方。既有来源前序关系、五分钟哈希、不可变聚合及启用修订是已核实的复用接入点，不是现成禁买权限。

T01检查：两个原始样本SHA256均与规格第1节一致；中英文段落结构、稳定编号、契约标识、数值边界、链接及命令一致；相对派发状态仅上述四文档变化；已跟踪实现／PMA／原文／冻结文件未变。业务测试、真实提取及行情调用均为 **0**。T02.1不存在真正需要用户决定的阻断；实现／证明工作仍由后续对应任务完成。本任务不创建提交，由调度会话审查并保存本地提交。

## 3. 阶段检查点

| 编号 | 任务 | 退出标准 |
| --- | --- | --- |
| PBS-C01 | T01–T04 | 已批准的口径、版本化有界模型、提取／覆盖拒绝测试通过；全部原文澄清明确且已绑定；不能把原始输入误标完整。 |
| PBS-C02 | T05–T08 | 持久状态、有界恢复、全部BUY提交保护、SELL独立、续版／接替及竞争测试通过；普通更新或旧契约均不能解锁。 |
| PBS-C03 | T09–T12 | 只读就绪、生成契约、现有界面、隔离浏览器场景、相关回归及独立审查通过；验收报告区分工程完成与未解决PMA验收。 |

每个行为切片先证明定向失败，再实施最小改动，通过定向测试后执行相关阶段回归。记录确切候选修订、命令、结果数量、失败原因及产物路径。没有新改动或未解决疑点时不重复全量回归。不得隐藏、删除、跳过既有失败或改标结果来获得绿色检查点。

## 4. 已授权的验证计划

每个实施切片开始前冻结确切新测试路径。使用确定性样本、隔离临时数据库、独立临时目录／JUnit路径及项目已有浏览器隔离流程。测试或服务不得指向用户数据库。T01仅运行文档静态检查，不编写迁移文件。后续状态存储实现仅在隔离存储中测试，部署／用户数据库迁移仍在本范围之外。

定向测试分组包括：边界及价格基准；持久性及时间顺序回放；有界补查；信号／提交／通知竞争；前序／接替启用；原文覆盖与澄清绑定；只读就绪；当前契约生成及不支持冻结适配器的明确拒绝；界面生命周期及独立SELL。

候选阶段检查命令，在 `trade-plan-monitor/` 下运行，必要隔离路径／选项在最终报告记录：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_daily_plan_chain.py tests/integration/test_plan_readiness_api.py -m "not live" -q
npm --prefix web run test -- --run
npm --prefix web run type-check
npm --prefix web run build
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
.\.venv\Scripts\python.exe -m ruff check src tests
git diff --check
```

这些命令补充确切新定向测试及既有必需契约／浏览器检查，不能替代PBS-A01–PBS-A12。原始03/04场景保留全部其他原文阻断，不编造“完整计划已通过”样本。状态机使用单独明确标识的最小工程样本；附带已批准澄清运行的原始样本，必须相应标注。

## 5. 完成与交接

PBS完成要求全部任务、三个检查点及十二项验收均有可复现证据。行为变化时，在有界双语切片中同步相关模块／API／操作文档，不为每个小机制新增独立文档。保留受保护的PMA任务／检查点记录及历史证据；后续状态协调必须引用新证据，不能改写旧结论。

分别报告：（1）新能力工程结果；（2）原始03/04仍未解决的提取义务；（3）尚不支持的新契约公共冻结准备／回放；（4）剩余PMA-C05/C07/C08及实际监控就绪。PBS完成不会单独关闭后三类问题。规划有界后续工作前，须对照全部原文义务重新评估F083。

本次草案编写、T01及该确定性扩展验收消耗的真实提取调用：**0次**。后续真实验收仍须遵守既有**实际尝试总计48次**上限、独立真值／正例要求，不静默提高预算或替换原文。不操作或迁移用户数据库。T01不提交／推送；本地提交由原调度会话审查后处理，本任务不授权推送。
