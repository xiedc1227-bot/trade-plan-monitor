# 单一计划流程验证

## V01. 范围与状态

日期：2026-10-03，Asia/Shanghai。状态：**LOCALLY_VERIFIED**。本报告覆盖当前 [U01–U08 契约](../specifications/monitoring/SPEC-unified-plan.zh-CN.md)，不沿用已取代的日线计划验收。基线：`880c76fecfbf002bbc1b73d717c54d542429e7e8`。改动仅在本地，尚未提交；未修改生产数据库、忽略的配置、凭证、实时供应商、部署或外部发布。

当前提取和操作使用一个 `/plans` 工作台、Schema 5 和 `plan-extract-v9`。条件保留各自周期，完整日线与完整五分钟证据可共存。原文规定的纯提醒规则不得转换成退出交易指令。基本面仍为生成时审核背景。明确模拟一次应用正数100股整数倍完整数量，并校验 T+1、CORE、容量、报价、审核及修订。

## V02. 删除的在线入口

- 独立日线提取模块、页面、工作台、路由、composable及重复组件；全部 `/daily-*` 公开操作及在线计划类型选择。
- 未使用的在线旧版/显式编辑器和运行面板；当前提取不再分派到 prompt v1–v7 或旧候选类型。
- AI 供应商/凭证写入及连接测试 HTTP 操作。保留配置读取与启动时不可变配置。
- 真实持仓成交/关闭/确认及持续人工事件风险写入操作，以及孤立界面。保留既有历史读取和存储记录。
- 旧一次性 AI 验收运行脚本及专用旧输出测试。原始源码仍可从 Git 基线 `880c76fecfbf002bbc1b73d717c54d542429e7e8` 恢复；既有请求授权不绑定到新提示词。

## V03. 具体保留依赖

| 依赖 | 当前或历史使用方 | 保留原因 |
|---|---|---|
| 冻结 Schema 1–4 编解码和模型图 | 既有计划/版本读取及历史回测输入 | 保留原始字节、哈希解释和审计证据；旧计划不能作为当前计划启用或模拟。 |
| `ai/daily_review.py` 与 `dailyMapping` 字段 | 当前准确原文/内容审核及历史审核解码 | 共用原文范围、排除、人工补充和审核哈希；名称是兼容细节，不是第二条提取路径。 |
| `runtime/daily_service.py`、`web/daily_service.py`、`state/daily_repository.py`、`state/daily_accounting.py` | 单一当前评估器和原子模拟账本 | 复用已验证事务、风险时序、T+1、CORE、幂等和原因记账，不转换真实持仓。 |
| 已核验分钟规范化/聚合及正式日线序列/指标 | 当前条件与恢复 | 保留数据源截止时序、完整性、复权和公式证据。纯日线规则不依赖旧分钟指标。 |
| 旧决策/指数模块和显式读取 DTO | 冻结历史/回测重放及兼容历史解码 | 保留研究解释；移除在线操作路由及旧计划可执行投影。 |
| 真实持仓与人工事件风险仓库/读取服务 | 历史记录读取及隔离研究/恢复证据 | 删除写入界面/API，不抹除或重写历史库存和风险证据。 |
| 保留的限额验收辅助代码 | 行情/恢复假数据源测试及封存的历史预算门禁 | 保留具体依赖，不恢复已退役在线提取，不续签旧授权。 |

冻结语义语料继续通过冻结领域/读取校验验证准确值、单位、组合、未支持含义、遗漏及原文审核权威，不调用退役在线提取。当前 HTTP 适配器及原文/审核检查另行依据当前契约验证。不能把有意义的安全断言替换成伪造成功运行结果。

## V04. 此前单一流程验收（持续有效改动前）

本节保留此前 `plan-extract-v8` 单一流程的历史结果与命令。“最终源代码”指此前验收快照，不证明本次 U08 改动。当前持续有效规则的验证另见 V06，不把重叠结果累加。

| 门禁 | 结果 |
|---|---|
| 当前模拟晚期故障、完整 SQLite dump、重试/幂等 | 2项通过：记账/信号写入后及回执创建后失败，全部数据行保持不变。 |
| 冻结 Schema3 语义原文语料 | 27项通过：保留原始值、组合、遗漏及审核阻断。 |
| Python 单元及契约门禁 | 最终源码上2695项通过，4项实时测试取消选择（`pytest tests/unit tests/contract -q -m 'not live'`，21.68秒）。包含两种 HTTP 监测版本的当前入口检查。 |
| Python 集成门禁 | 最终源码上3289项通过，1项跳过，4项取消选择，耗时1435.31秒，未忽略任何测试文件。既有 `test_cursor_key_rejects_foreign_posix_owner_before_use` 需要 POSIX 文件归属语义，不能在 Windows 运行。取消选择的四项容量场景已单独通过，见下行。包含真实操作系统进程重启、原文/审核绑定、晚期激活、状态证明及原子回滚场景。 |
| 未变化的回测容量门禁 | 四项耗时容量场景已单独全部通过：十股票/252日重放、traced heap、稳定 BUY/T+1 退出字节，以及大查询/100k导出。604800行原始分钟数据及原有固定预算不变。最终集成检查只排除这四项已验证场景。 |
| 前端单元/类型/构建及浏览器流程 | 56个文件中的802项单元测试通过；类型检查及生产构建通过。保留的31项 Playwright 测试全部通过（55.0秒），包括当前提取/审核/激活、完整模拟、风险提醒筛选/确认、原文修改失效及打包进程重启。 |
| 生成 API/类型一致性、lint及文档 | `python scripts/generate_frontend_types.py --check` 在两种监测契约版本下通过。`ruff check src tests scripts` 和 `git diff --check` 通过。15对改动双语文档均有对应版本；新规范/报告的 U/V/H 章节编号、API 路径及数字一致。当前规范 OpenAPI 哈希仍为 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255`；公开传输格式未增加证明元数据。 |
| 独立最终审核 | 已修复提取审计提交、旧记账旁的纯提醒访问，以及此前信号/风险和提醒自身激活日期的保留。发送/缓存/状态现依据原始一分钟源复核事实和全部已消费五分钟桶。完成证明绑定准确的不可变评估 ID、配置、运行代次、激活、日历及适用目标；GET 不生成证明，也不扫描全部评估历史。缺失日线日历或复权基础会阻断依赖证据。到期提醒在状态和取数中均不能继承旧风险；真正已锁存风险可延续。生产与状态共用周期判断，包含纯人工事实确认及仅重置条件需要分钟数据的场景。已发现的限定范围缺口均已修复并独立复查。最终受影响运行和状态组分别160项、28项通过；它们与完整集成门禁重叠，不计入其总数。 |

探索结果不计入最终总数。发现的陈旧截止时序、过宽分钟前缀要求、旧权限需求、提醒建模、旧可执行投影及过时夹具请求类型，均在最终检查前修正。新增回归保留否定技术事实、每个已消费组合风险证据 ID、重启后的提取来源，以及当前提醒旁不变的旧记账记录。

最终 Python 命令，从 `trade-plan-monitor/` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'
.venv/Scripts/python.exe -u -m pytest tests/integration -v -rs -m 'not live' -k 'not ten_symbol_252_day_replays_meet_capacity_budgets and not 252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget and not each_fixture_symbol_has_stable_buy_and_t1_exit_bytes and not large_queries_and_100k_export_meet_fixed_budgets' --maxfail=15
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

前端命令，从 `trade-plan-monitor/web/` 执行：`npm run test -- --run`、`npm run type-check`、`npm run build`、`npm run test:e2e`。

推送前文档维护复核：2696项单元/契约测试通过（排除4项真实服务测试）、37项针对性集成测试通过、前端802项测试及类型检查通过。冻结 T059 发布报告与操作指南现位于 `tests/history/t059`；未改变的验收/双语/密钥断言之前校验准确 Git 源码 SHA-256。新增字节变更拒绝回归，不把历史验收绑定到当前流程。

## V05. 限制

确定性测试使用隔离临时 SQLite 数据库、假 SDK 证据，或通过真实 AI 适配器的 HTTP mock transport。它们不认证实时 Tushare/AI/Webhook 可用性，也不批准用户策略。读取只能校验本地已观察、已准入证据；尚未观察的远端日线修订要在下一次取数后才能发现。历史验收不证明当前行为。不静默升级历史审批，未执行生产数据迁移/重置。本地验证不包含人工 NVDA 和当前真实环境上线证据。


## V06. 当前普通规则持续有效验证（U08）

基线：`86bb448`。本次限定范围改动新增 Schema 5 显式 `PLAN_ACTIVE`，保留原始普通联合类型成员 `DailyValidity`，新提取使用 `plan-extract-v9`。历史 v8 响应仍可读取，候选/映射字节不变。不引入加载/导入/保存兜底或迁移。保存和审核替代版本不会改变活动版本，必须明确启用其新的审核绑定。

| 门禁 | 实际结果 |
|---|---|
| 最终 Python 单元/契约门禁 | 冻结实现上 2728 项通过，4 项 live 测试排除，21.28 秒。 |
| 限范围 API/运行/状态/记账门禁 | 下列 16 个文件中 358 项通过，112.05 秒。覆盖原文/审核及启用、生产混合周期、运行状态、通知、整手模拟、T+1、CORE、容量、幂等及风险锁存/解除边界。 |
| 持续规则生产夹具消费方 | 下列 10 个文件中 154 项通过，249.62 秒。普通规则采用 `PLAN_ACTIVE`，覆盖发送时权限、恢复/停用/替换隔离、数值判定及通道/传输行为。 |
| 最终防护/审核/API 复查 | 独立审核修复后 80 项通过，8.70 秒；与其他门禁重叠，不累加。包含 32 项持续有效回归。 |
| 前端 | 56 个文件中 804 项通过；`npm run type-check` 与 `npm run build` 通过。包含最终历史 v8 响应读取测试。 |
| 真实浏览器 | 使用隔离临时 SQLite/虚拟供应商服务的 1 条 Playwright 流程通过，8.8 秒。提取、修改混合条件、保存、刷新、审核、明确启用、执行一笔完整模拟、确认纯提醒库存隔离及停用。保存的普通有效期准确为 `{"mode":"PLAN_ACTIVE"}`，没有结束日期字段。 |
| API 产物/静态检查 | 两个 monitor 契约的 `generate_frontend_types.py --check`、`ruff check src tests scripts` 和 `git diff --check` 通过。重新生成未产生受版本管理的 OpenAPI/类型差异；U04 已批准快照哈希不变。 |
| 独立最终审核 | 冻结代码获批准，U08 范围内没有剩余可操作问题。独立持续有效/领域/正式 API 检查 50 项通过。审核者另将完整及不完整历史审核快照与基线逐字节比较，并执行内存中的期限检查适用性分支变异检查。 |

兼容断言采用从改动前 Git `86bb448` 独立取得的固定值：规范 JSON SHA-256 `937c7b062a93abb3567f04e074f8eb4d82efc467ea60e04d1e89cd12502bf741`、内容哈希 `832a1d87b3c3bea92b12ef94c621a42790e82aaef030d4cc8d8fa2b2a23f80ee`、审核证据哈希 `5feb96a2bfba4c1bd84bffa2ce85a906c29e3f7a05a47b606fac1f87ac203dcd`、原文哈希 `5ebe3212d9cfcafce2a9b5da7e293d3678bbf92145703fce6e840b95ee86ccff` 及空问题列表。同一日期载荷仍接受省略 `DATE_RANGE` mode。2027-01-04 的直接对照证明持续规则越过旧的 2026-12-31 截止日期仍可确认，而日期兼容对照拒绝确认。旧信号仍到期；仅换日期不能创建信号，经过核验的独立发生可创建，且该发生不能重复使用。

独立审核修复期限作用域：保留的 SELL/计划激活日期不能解除持续 BUY 的期限；开始日期不能解除截止日期；任何语序或语言的单次执行窗口不能隐藏期限；人工停用措辞不能隐藏并存日期/时长。保守扫描只移除明确局部的单次执行窗口和纯生命周期措辞。报告/证据日期保持区别。一个原文条款只产生一个可见期限问题，列明所有受影响有效期路径。人工转换的作用域补充须引用完整原句并写明 `改为持续有效` 或 `convert to PLAN_ACTIVE`，随后重新审核并明确启用。这是完整原文审核之外的有限防护，不是通用语言解析器。

外部中文模板 `D:/Workspace/Projects/ai-quant-pilot/docs/TradingAgents/reports/新提示词.txt` 仅有四处措辞替换：输入有效性、输出有效性、自检有效性及工具衔接有效性。保留单次信号到期、四节输出、1500 字限制、策略/价格/仓位/风险/费用及其他缺参数措辞。该原始 `.txt` 位于本 Git 仓库之外，没有原始 Git 快照；不要求英文副本。

最终单元/静态检查/产物命令，从 `trade-plan-monitor/` 运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'
.venv/Scripts/python.exe -m pytest tests/unit/test_persistent_rule_validity.py tests/unit/test_daily_review.py tests/unit/test_daily_extraction.py tests/unit/test_unified_plan_domain.py tests/integration/test_current_plan_api.py tests/integration/test_source_treatment_review_api.py tests/integration/test_explicit_plan_review_api.py -q -m 'not live'
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

限范围 358 项命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_current_plan_api.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_notification_delivery.py tests/integration/test_runtime_status_official_close.py tests/integration/test_runtime_status_composition.py tests/integration/test_runtime_status_projection.py tests/integration/test_daily_history_regression.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_simulation.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_source_treatment_review_api.py tests/integration/test_source_treatment_legacy_compatibility.py tests/integration/test_ai_provider_contract.py tests/integration/test_explicit_plan_review_api.py tests/integration/test_web_api.py -q -m 'not live'
```

持续规则生产夹具 154 项命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_delivery_admission.py tests/integration/test_explicit_plan_channel_acceptance.py tests/integration/test_explicit_plan_independent_oracle.py tests/integration/test_explicit_runtime_production.py tests/integration/test_explicit_transport.py tests/integration/test_recovered_explicit_rolling_window.py tests/integration/test_recovery_activation_fences.py tests/integration/test_runtime_pipeline_progress.py tests/integration/test_s3_startup_outcome_association.py tests/integration/test_source_treatment_inventory_isolation.py -q -m 'not live'
```

前端命令，从 `trade-plan-monitor/web/` 运行：`npm run test -- --run`、`npm run type-check`、`npm run build`、`npm run test:e2e -- tests/e2e/condition-plan.spec.ts`。早期探索失败已经修复，不计为通过；最终浏览器重跑服务退出干净。Python 门禁保留既有 FastAPI TestClient/httpx 弃用警告。复用 V04 未改变的高成本回测容量门禁，不重新运行。U08 未使用真实供应商、生产数据库/配置、提交、推送或部署。
