# 规格：单一交易计划流程

> 英文规范文件为 `SPEC-unified-plan.md`，本文件为对应的中文审阅副本。

## U01. 权威来源与边界

用户于 2026-10-02 的纠正恢复原设计中的单一计划能力：粘贴原文 → AI 草稿 → 修改与审核 → 明确启用 → 监测条件 → 提醒和用户明确请求的模拟交易。本规格替代独立日线计划产品和在线旧版/显式规则类型选择。条件的周期是取数需求，不能成为独立计划业务类型。现有指数研究和回测是独立能力；本次不新增指数判断。

基本面由用户在生成计划时审核，不作为监测事实、运行阻断项或模拟门槛。原文排除范围保持可见并绑定审核。不引入券商下单、执行跟踪、部分成交、未知订单、占额或客户分配。

## U02. 当前模型

唯一新建可执行格式为 Schema 5、`CONDITION_PLAN`、`condition-plan-v1`。冻结的 Schema 1–4 字节、哈希和审计记录保持原有解释；格式编号仅用于内部历史信息，不能作为产品选择。新提取只使用一个服务端提示词和审核路径。旧草稿必须重新提取、修改并审核新版本；不得静默转换或重新计算其历史哈希。

每个普通规则包含一个明确的条件树、数量、有效期、独立信号策略、确认方式和执行窗口。保留原文定义的 ALL/ANY 组合。条件可以组合既有已完成日线叶子和已完成五分钟叶子。可选 `alert_rules` 保留原文规定的纯技术提醒条件，具有明确确认方式，不包含交易数量、退出目标或库存变更，不能授权模拟。可选价位、价格区域和技术退出分支仅由原文或明确审核的人工补充支持。缺失含义保留为未解决项；不得编造策略阈值、分支、数量、日期或组合。只有 `position.max_qty` 为必填；可选 CORE/TACTICAL 分配元数据是策略，不会初始化库存。

## U03. 时间与证据

`OFFICIAL_DAILY_CLOSE` 使用正式已完成日线证据确认，普通模拟窗口为 `NEXT_EXCHANGE_SESSION_ONLY`。`COMPLETED_BAR_CLOSE` 且 `timeframe_minutes=5` 使用完整五分钟 K 线确认，窗口为 `CURRENT_SESSION`。这些值必须明确且一致。混合条件树使用同一个评估截止时点：日线叶子不能读取盘中暂定收盘或未来正式日线；分钟叶子不能读取未完成、有缺口或在截止后接收的分钟。固定/动态引用、复权、公式版本和预热保持既有已验证语义。

取数前冻结计划版本、哈希及激活修订，并在提交事务中复核。恢复只获取所需证据和有效分钟报价；只有日线条件的计划不得依赖旧 `ta-v1` 五分钟指标。缺失数据阻断其依赖条件，不能编造通过结果。技术风险锁存保留正式收盘确认、T+1、优先级及审核后的解除。无法量化的技术判断需要计划明确指定范围的人工证据；技术解除证据不要求公告机构、标题或 HTTPS 链接。

有明确范围的技术审核事实显式记录 `satisfied=true` 或 `satisfied=false`；缺失事实仍为未知。使用截止时点前最新的有效审核，同一截止时点存在矛盾断言则阻断评估。技术否定事实不能否定可交易、全日停牌、独立事件或信号失效控制证据。组合风险条件保留每个已消费叶子证据 ID，防止后续风险重审重放已消费证据。

只有持久化来源 K 线、计划/审核/激活、有明确范围的事实、风险及相关库存仍为当前状态时，分钟重放才能复用已有决策。后续来源更正必须重新评估。提醒发送前复核限定范围的事实及当前来源证据；其证据陈旧或不成立后，此前排队的正向提醒不能继续获准发送。

当前运行状态需要已提交的完成证明，绑定运行代次、配置修订、激活计划身份、最新适用的完整目标，以及日历和已消费来源/状态证据。读取时必须复核该证明；依据缺失或变化时，保留的评估只能显示为缓存且只读。状态读取不能取数或改变业务记录。条件仅包含已审核技术事实时，规则的明确确认周期也必须决定其目标。

## U04. 单一操作路径

`/plans` 是唯一当前工作台，展示原文、结构化候选、遗漏、绑定、审核、已保存版本、激活和模拟状态。保存只创建未激活草稿。审核绑定原文/内容/证据/修订。激活使用独立命令。改变原文或内容会使先前审核失效。提取、提醒、已读、审核和刷新均不能改变持仓。

当前正式 API 操作使用 `/api/v1/plan-extractions`、`/api/v1/plan-drafts`、`/api/v1/plan-review-previews`、`/api/v1/plan-review-supplements`、`/api/v1/plan-review-confirmations`、`/api/v1/plan-activations`、`/api/v1/plan-deactivations`、`/api/v1/plan-facts`、`/api/v1/simulation-position-confirmations`、`/api/v1/simulation-position-inventory`、`/api/v1/plan-risk-reassessments`、`/api/v1/simulated-trades` 和 `/api/v1/plan-runtime/{symbol}`。当前路由没有独立 `/daily-*` 操作族。AI 供应商配置在 API 中只读，并从项目文件一次加载。旧 `dailyMapping` 传输字段和内部 `Daily*` 名称作为共用审核/记账兼容细节保留，不能构成第二套当前流程。

历史审阅 OpenAPI 快照 SHA-256：`8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`。于 2026-10-07（Asia/Shanghai）依据 [SPEC-unified-replay](../backtesting/SPEC-unified-replay.zh-CN.md) UR01/UR03/UR04/UR05/UR06/UR08 审阅，覆盖已在 `7a92f75` 提交的既有统一研究扩展：增量 `researchInput`、强类型研究决策/操作详情、指标/权益投影及其有界支持结构。路由、操作参数/响应和其他全部既有监测/错误/任务结构不变，生成物与实际路由一致。[MV12](../../verification/monitor-loop-backtest.zh-CN.md#mv12-隔离收尾与契约审阅) 记录全部 37 处 schema 差异及实际检查。原批准 `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255` 保留为 `a0915f7` 的历史身份，不再视为当前批准。此次纠正仅批准当时既有统一研究契约，保留其历史范围；现有监控闭环准备/服务 API 的最终审阅和批准见 U09。

模拟交易必须明确操作，与登记的真实持仓和离线研究成交隔离，一次完整应用正数 100 股整数倍数量。初始模拟库存、持有/可卖数量及计划目标也必须为 100 股整数倍。服务端在单股票事务内复核激活身份、审核、信号/风险依据、库存修订、报价、日历、T+1、CORE 保护、最大持仓和幂等。完整授权数量不可执行时不得替代为部分交易。

当前纯提醒计划只依赖当前计划身份、自身激活窗口及条件证据，不依赖模拟库存权限。既有不兼容记账记录不能阻止提醒，评估也不能修改此前持仓、信号、风险或模拟记录。历史风险不能延长提醒计划的激活窗口；缺少兼容记账权限时模拟仍须阻断。

通知中心展示当前纯提醒事件，并将其纳入 `RISK_ALERT` 筛选。保留的 `REMINDER` 消息标识及 `alertKind=RISK_ALERT` 仅标识审核证据；不包含数量、执行日期、风险范围或模拟权限。已读仍为独立且幂等的阅读标记。

## U05. 删除与保留

删除独立日线路由、页面和提取工作台、当前目标格式选择器及未使用的 AI 配置写入/测试方法。从当前计划流程移除普通真实成交登记及持续基本面/事件风险操作。冻结模型编解码和历史审核读取仅为解释既有字节而保留；旧决策逻辑仅在隔离历史回测重放依赖时保留。单一当前评估器实际依赖的已核验分钟规范化、日线指标、风险时序、模拟记账及恢复继续保留。验证报告必须列明保留理由。历史日线验收不能证明本次完成。

## U06. 验收

1. 一个真实浏览器路径通过正式 API 服务完成提取、修改、审核、保存和明确启用。
2. 一个当前计划包含日线和分钟条件；生产评估证明截止时序隔离及激活竞争保护。
3. 提醒/已读/审核/刷新不改变持仓。明确整手完整模拟保留 T+1、CORE、上限和幂等；拒绝不兼容数量及部分数量。
4. 无第二套提取工作台或在线类型选择器。历史字节及哈希不变；旧格式不能绕过当前基本面边界。
5. 适用 Python、前端、正式 API、生产组合及浏览器检查通过。报告区分本地确定性证据、尚未取得的外部供应商核验和未解决失败。

## U07. 文档一致性

两种语言保持 U01–U12、字段名、格式号、API 路径、时序、边界与验收标准一致。当前索引指向本文。保留有用的冻结兼容约束及必要验收证据；从维护目录删除被替代规格与已完成过程记录。历史 Git 证据不授权当前行为。

## U08. 普通规则持续有效（2026-10-03 限范围方案）

**决策与字段契约。** 新编写的普通规则通常显式使用 `validity: {"mode":"PLAN_ACTIVE"}`，跟随所属计划，直到人工停用或明确启用已审核的新版本替换。此模式没有规则起止日期字段。这是 Schema 5 的增量契约，不是另一套计划类型：保留 `CONDITION_PLAN` 和 `condition-plan-v1`。`UnifiedRule` 与 `UnifiedDraftRule` 在既有 `DailyValidity` 的 `DATE_RANGE` 表达之外接受新值。缺失/null 的 validity 仍不完整；只有新提取/编写选择明确的产品默认值。加载、导入、保存或迁移不得把此默认值填入旧数据。

**计划激活与原文期限。** 原文没有计划激活窗口时，新提取默认 `activation.mode=MANUAL`。既有计划级 `TRADING_DAY` 和 `DATE_RANGE` 仍有效，并约束普通交易权限。原文明示的规则截止日期保留为可见的 `DATE_RANGE` 兼容例外，保持原日期；无法忠实表达时保留为未解决项，绝不丢弃或自动提升为整份计划的期限。编辑器将该例外标为保留的原文/历史约束。改为持续有效必须有可见的原文/候选修改、新证据绑定、人工审核和明确启用。该规则 `validity.mode` 的 `HUMAN_SUPPLEMENT` 理由须引用每个冲突条款的完整原句，并明确写明 `改为持续有效` 或 `convert to PLAN_ACTIVE`；未获该作用域补充的期限仍阻断审核。产品默认绑定只允许精确的新模式/默认值，不能解决与其矛盾的期限条款。日期限制识别是完整条款审核之外的保守检查，不是通用自然语言解析器。报告/证据日期和单次信号窗口不属于普通规则期限。

**生命周期与兼容。** `PLAN_ACTIVE` 仅在确认新信号时取消逐规则日期过滤。日线信号仍在下一交易日收盘过期；五分钟信号保留 `CURRENT_SESSION`。同一信号只授权一笔完整计划数量；仅更换日期不能构成独立信号。既有身份、审核、修订及发送前检查在停用/替换后拒绝旧普通交易权限。保存草稿不替换活动版本。风险记录跨这些操作继续锁存，沿用明确重评/解除规则；不引入新风险生命周期。共用 Schema 4 `DailyValidity`、历史原文/JSON/哈希/审核/审计字节以及既有日期授权保持不变。历史审核重建不能仅因规则含日期而新增问题。

**实现范围与顺序。** (1) 扩展 `domain/unified_plan_models.py` 和 `domain/unified_plan_validation.py`，覆盖旧规范字节和新显式有效性。(2) 更新 `ai/plan_extraction.py`、提示词版本声明/消费方和 `ai/daily_review.py`，支持精确默认绑定与可见原文期限。(3) 在 `decision/unified_lifecycle.py` 区分规则有效性；仅在直接日期依赖需要时修改运行/服务路径。(4) 按需更新 `web/src/components/plans/planSchema.ts` 和当前模式驱动编辑器/说明，重新生成受影响 API 快照/类型，更新当前提示词引用。(5) 限范围修改仓库上级工作区的 `../docs/TradingAgents/reports/新提示词.txt` 措辞。(6) 扩展针对性领域、提取/审核、API、生产运行/状态及浏览器测试，在既有中英验证报告记录实际结果，再独立审核。

**验收。** 无规则日期的原文产生可审核候选，不编造日期，其余参数/证据完整后可启用。后续交易日可发现新独立信号，旧信号仍过期且不可重复使用。停用/替换阻断旧规则/信号/排队普通提醒；仅保存无影响；内容修改必须重新审核。覆盖风险锁存与明确解除、T+1、CORE、最大数量、完整正数 100 股模拟与幂等。旧含日期的规范字节/哈希及授权边界完全不变。明确和含糊期限保持可见，不能被新默认值隐藏。正式 API 与单一 `/plans` 浏览器流程一致。中文生成模板不再把缺截止日期视为遗漏，同时保留单次信号窗口与其他参数缺失语义。

**验证与排除项。** 仅用确定性的临时数据库/虚拟供应商：`.venv/Scripts/python.exe -m pytest <affected tests> -q -m 'not live'`、`.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`、受影响 Ruff 检查、`npm run test -- --run`、`npm run type-check`、`npm run build` 及当前 Playwright 流程。复用未受影响验收，不重复高成本回测容量测试。其他策略、指标、供应商、恢复架构、指数功能、基本面边界、记账设计、券商执行、生产配置/数据库、提交、推送与部署均不在范围。


## U09. 单计划监控闭环最终 API 审阅（2026-10-09）

OpenAPI 快照 SHA-256：`dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0`。本次限范围最终批准依据已实施的[监控闭环提案](../backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md)、[操作指南](../../operations/monitor-loop-backtest.zh-CN.md)及 MV46 证据。用户授权完成剩余 20 项并逐项推送 GitHub；此处在门禁通过后记录具体已审阅实现，不将授权本身当作验证。

当前监测 v2 快照 SHA-256：`d34ffd622021a50127a6f92cbf81be8323884f1f5b2dc36e529a7ca2c0b9c807`。上方批准身份对应兼容监测 v1；两种 profile 的已审阅回测差异一致，各自原监测接口保持精确。

与此前已审阅的 `7a92f75` 统一研究快照相比，挂载契约共有 62 条路径：52 条原路径全部保留，新增下列 10 条。七条准备路径覆盖创建/读取/原文/提取/审核/取消/明确恢复，三条服务路径覆盖惰性状态及明确修复/恢复/停止。不增加第二种计划类型、每日后继、批量运行、同时任务、监测控制或原生导出路径。

| 新增路径 | 已审阅操作 |
|---|---|
| `/api/v1/backtest-preparations` | POST：201 耐久单原文准备 |
| `/api/v1/backtest-preparations/{preparation_id}` | GET：200 耐久进度 |
| `/api/v1/backtest-preparations/{preparation_id}/source` | PUT：200 绑定修订的编辑 |
| `/api/v1/backtest-preparations/{preparation_id}/extractions` | POST：202 明确自有提取 |
| `/api/v1/backtest-preparations/{preparation_id}/reviews` | POST：200 已审核不可变清单 |
| `/api/v1/backtest-preparations/{preparation_id}/cancellations` | POST：200 / 202 已结束或等待排空的取消 |
| `/api/v1/backtest-preparations/{preparation_id}/recoveries` | POST：200 明确确认已结束的恢复 |
| `/api/v1/backtest-service` | GET：200 惰性状态/能力 |
| `/api/v1/backtest-service/recovery-requests` | POST：202 局部修复或恰好一个所选任务恢复 |
| `/api/v1/backtest-service/stop-requests` | POST：202 接受自有停止 |

既有操作差异仅限 `POST /api/v1/backtest-runs` 接受增量 `PreparedBacktestRunCommand`，以及 `/api/v1/backtest-runs/{run_id}` 的 GET/PATCH 接受增量 `BacktestLoopRunView` 响应。原请求参数、收据/状态/错误结构、PATCH 命令及旧分支保持精确一致。三个改动的原模式为 `BacktestDetailView`、`BacktestFillPage` 和 `BacktestRunPage`，仅增加原生事件/成交/汇总分支，其他属性及 100 项上限保持一致。新增 108 个可达模式，涵盖有界准备/原文审核、共用 Schema 5 条件、期初账户/已知未知事实、原生因果报告及封闭服务命令。没有原模式被删除或发生其他修改。两套生成 profile 均对照挂载路由检查。

准备变更沿用本地来源/幂等保护、严格修订绑定、单原文输入、3 次尝试、封闭候选分支及未知/取消调用排空保护。提交冻结一份已审核计划/账户及一次确定的截止，回放消费复制证据，不新增提供方/AI 工作。原生结果保留精确金额、来源、因果收据身份及有序分页。内部成交存储键绑定运行，公开收据标识及精确旧记录验证保持稳定。原生闭环导出继续在流响应前返回 409，既有支持模式冻结导出保持兼容。

服务状态保持惰性，控制绑定启动 `epoch`、`expectedRevision`、原始请求体/键及最多一个所选 `resumeJobIds` 条目。接受 202 控制收据不代表清理完成。READ_READY/READY 均不自动授权待恢复任务。一个未完成任务会阻止新建及互斥操作，直至最终状态或明确有证据的恢复。取消中及未知工作保留槽位，自有晚完成工作实际排空前阻止替换。真实有界 SQLite BUSY/LOCKED 元数据冲突使用既有 503/Retry-After 错误结构，保留原始请求重试，不改变其他 SQL 故障。服务/线程上限及每十分钟五次实验的实测负载边界保持 ML15–ML17/ML-O08/ML-O09 的说明。

U04/MV12 保留历史 `a0915f7` 批准不一致及针对 `7a92f75` 单独审阅的纠正。此 U09 批准仅在 MV46 记录的最终接口检查通过后替代当前契约身份，不抹去先前失败、不认证真实 AI/行情提供方、不批准生产迁移/部署，也不扩展已接受的同进程限制。

## U10. 已授权的指数总览契约扩展（2026-10-09）

OpenAPI 快照 SHA-256：`76a63344e2ff29ed50c44d4ff7a5fa1e5f5f2faf938274991f8b0b6edd194c29`。当前监测 v2 快照 SHA-256：`a2d99ac2c89cca1dd031cf2045251be24524550da80f1012df1e36cb0a4d595f`。用户于 2026-10-09 授权实施并验收 [SPEC-index-close-display-repair](SPEC-index-close-display-repair.zh-CN.md) ICDR01–ICDR10。U09 保留原有监控闭环历史批准及其范围。

相对于 U09 快照的限范围比较证明，两种 profile 的全部既有路径和结构均保持不变。每种 profile 现有 63 条路径：唯一新增操作为只读 `GET /api/v1/market-indexes/overview`，支持结构共五个：`MarketIndexLatestAcquisition`、`MarketIndexOverviewData`、`MarketIndexOverviewItem`、`MarketIndexOverviewResponse`、`MarketSessionView`。不增加计划、记账、供应商或执行操作。生成快照／类型与实际路由一致。已执行的验收和发布结果记录在[配套验收报告](../../verification/2026-10-09-index-close-display-repair.zh-CN.md)。

## U11. 按日连续回测具体 API 审查（2026-10-11）

OpenAPI 快照 SHA-256：`7fc0340a8b2a07414f09dc09f2fd894f4be6aeb3aa4401323cea8c0c691f4a43`。规范监控 v2 快照 SHA-256：`b9d8b1e79b3c0b4637c91095ad34cff671b96c3d6cc39150eefd05218cacbf65`。生成 TypeScript SHA-256：兼容版 `5dccf9683a0def43a65dcee44fcbeddb6b0b212c70b7b0139a0cd5d18461b047`；规范版 `80d3a8e49f490a26f3daee1ed5411caf0f1eae27d281c548a21c7e21a03bb477`。

依据 RP05-A03 持续授权，本审批记录两套实际生成差异相对 U10 的独立审查，实施基于 `05cad3e` 加公开创建格式标识修正。授权与验证相互独立，保留 U09/U10 历史身份。每套配置现有 64 条路径：仅新增只读 `GET /api/v1/backtest-preparations/{preparation_id}/items`。七个既有准备操作和运行 POST/GET/PATCH 增加显式 v2 分支（共 10 个既有操作）；操作 ID 与错误响应精确不变。没有删除路径或旧模型。仅 `PreparationCreateCommand`、`BacktestRunPage`、`BacktestDetailView` 增加联合分支；其余 397/410 个旧模型及全部监控操作保持不变。

36 个新增模型覆盖有界集合创建/进度/分页、条目修正/整链审核、来源绑定候选证据、版本切换与连续结果。创建必须使用 `schema_version: backtest-preparation-v2`；其他集合变更必须使用 `schemaVersion: backtest-preparation-v2`；连续运行提交必须使用 `schemaVersion: prepared-loop-plan-v2`。来源/版本最多 256 项，条目页最多 100 项，精确绑定 expectedRevision，并通过 nextOffset 自适应返回完整条目。修订号仍为 JavaScript 安全整数。继续遵守 4 MiB 请求/结果和 2 MiB 准备投影限制；生成数组类型无法自行约束运行时长度。

`monitor-loop-result-v2` 提供有序版本/来源证据，以及通过 `report_schema_version` 标识的 `backtest-report-v5` 类型化报告摘要。公开摘要不含私有完整计划表和原始来源，不能作为完整私有报告独立重算哈希；后台仍必须验证不可变报告与输入。旧 v1 准备、v4 报告字节/哈希、受支持导出、唯一未完成操作、取消/未知工作排空互斥、同进程唯一工作线程及最近 30 份保留规则不变。循环回测导出仍返回 409。不批准新增全局资源、配额、实时监控控制、生产迁移或部署。

独立审查先在两套配置中复现创建格式标识可省略的问题，再以公开子类型修正，使契约匹配 HTTP 分派，同时保持私有默认值精确不变。两份生成 TypeScript 与各自生成器一致。实际接口门禁及待完成的前端验收记录在 RP-V14；本 API 审批不代表 RP-T15–RP-T20 已完成。

## U12. 每日连续功能操作收尾（2026-10-11）

RP-T01–RP-T20 及 RP-C01–RP-C07 已依据 RP05-A03 完成。原 ML-A07、ML-A11、ML-A13 和 ML-A16–ML-A18 仍是有效验收，并通过已记录离线检查。一个有序原文集合串行提取、整链审核并提交一次；每日替换／延续使用一个连续账户和一份结果。后续账户陈述不能覆盖账本。精确字面原文审核及首日期初时点修复保留已审核证据边界和原服务端权限。

[操作指南](../../operations/monitor-loop-backtest.zh-CN.md)与[验证报告](../../verification/monitor-loop-backtest.zh-CN.md) RP-V19/RP-V20 记录真实 Chrome 业务／重试／编辑／互斥、完整权益、兼容／故障测试及未降低的 600/600 秒负载门槛，并区分合成 AI／行情输入、实测同进程边界与真实供应商或最大容量认证。U09/U10/U11 保留历史范围；U11 四个批准哈希保持精确一致，两套生成契约均通过。本收尾不改变公开 API 形状或批准身份，不进行生产迁移／部署，也不授权新平台范围。修改为本地提交，本轮不推送。

## U13. 已授权的单份计划库契约（2026-10-16）

用户明确要求一次准备一份、组合已审核计划，因此授权两个监控配置中的以下具体路径：`GET /api/v1/backtest-plan-library`、`POST /api/v1/backtest-plan-library/preparations`、`POST /api/v1/backtest-plan-library/compositions`。保留准确路径白名单和现有公开错误结构。不修改监控启用契约。

创建请求为 `SingleSourcePreparationInput`（`preparation_id`、一份 `source`、可选准确 `reviewed_base`）。组合接受 `PreparedPlanCompositionInput`（`preparation_id`、1–256 个不重复 `plans` 引用）。两类写入均要求来源／幂等保护并返回 201。计划库读取使用 `offset`、`limit`（1–100）和 `no-store`，返回已审核身份、哈希、来源 ID、生效日期、代码／名称、前序引用和审核时间。集合进度增加 `workflow`、`editableSourceId` 及可选 `baseAccount`。保存时来源日期仍可选；提取前执行生效日期预检。审核和回测路由保留原有版本契约。

时间顺序、不可变前序证据、审核、组合及连续账户权限均由服务端负责。原始写入回执可准确幂等重放。已确认行为、边界和验证见 ML21、SP01–SP05。中英文版本描述相同字段和路径。

OpenAPI 快照 SHA-256：`dfdf2e1a1d33cc1f7023720c814b03ce8e8b982f6bb42ec8faeb79abfb2957be`

规范监控 v2 OpenAPI 快照 SHA-256：`c436a671a1734240fce9c4c758d366afb50e4e0f16e4b218117ff288a9ce41fb`

## U14. 原文确认契约（2026-10-16）

用户授权修复来源支持的信息并集中确认。新增可选 `confirmationSummary` 投影（`automaticFacts`、`questions`、`processingIssues`）、`CONTEXT` 分类、待审核 `SOURCE_INTERPRETATION`、可为空的停用区间及固定价格引用日期、分笔信号顺序。旧版格式保持原编解码，不推定审核或执行授权。参见 [SC-01–SC-03](../../../tasks/source-confirmations.zh-CN.md) 及验证报告。

OpenAPI 快照 SHA-256：`2d1a16ef1d13d3112abc4c3635f033ee8377c782c0c3679b97f8330b3f0a94e3`

规范监控 v2 OpenAPI 快照 SHA-256：`34d509fab8aa647e3404f74060d721c2cf0a2267bd6fc70738e3fa6e29b9bded`

## U15. 统一准备与规则变更（2026-10-16）

用户授权移除完整／修改类型选项。准备下一份默认关联刚审核的前序；新页面可默认关联单一标的、最新生效日唯一的版本，计划库存在歧义时才需选择。仍可明确开始新计划链。沿用可选的 `reviewed_base` 固定准确的不可变前序，API 路径和模式不变。

审核展示 `RETAIN`、`MODIFY`、`ADD`、`REVOKE` 及前后值和依据。具备来源绑定的重述可以确认变更，无需原文包含内部规则编号。未提及的每个策略字段必须具有明确继承范围，或由当前有效依据重述相同值，或属于相同的固定产品常量，否则继承仍待确认。取消必须唯一对应前序规则，不能从未提及推断。同一 compact-wire 操作重复出现时合并依据，冲突动作仍报错。账户上下文只有在没有事实、依赖和额外键时才能将空对象视为 null。已表达的未核验条件仍保持未核验；描述这些条件或停用区间的提示不会单独阻止审核。

仅现金未知不再使已审核策略失去后续提取资格。来源／候选哈希、原始证据、整体审核和连续账户规则仍为权威。参见 [UP01–UP03](../../../tasks/unified-preparation.zh-CN.md) 和[验证报告](../../verification/2026-10-16-unified-preparation.zh-CN.md)。

## U16. 仅按仓位约束的研究资金模式与日线依据（2026-10-17）

OpenAPI 快照 SHA-256：`de10c595c26c0ae375e3d895f28ba2b2cab8e929dba412de4aa005d1efd0f7fa`

规范监控 v2 OpenAPI 快照 SHA-256：`07d2b38c4eda309f402fa7540b944aaf7c92e08e2953ea082089efcb9e20763d`

用户明确要求取消期初现金要求。新原文审核在原现金判别字段中使用 `PositionLimitFunding`，`kind: POSITION_LIMIT_ONLY`，不增加接口或资金模式选择控件。历史 `KNOWN`、`UNKNOWN` 输入及其来源证据校验仍按原语义读取。新买入仍严格执行计划授权、最大持仓、T+1 和数量规则。费用／成本及成交盈亏连续保留，不计算本金收益率／净值回撤。冻结回放数据集可选嵌入有界复权因子依据；省略时保留旧哈希。参见[操作指南 ML-O14](../../operations/monitor-loop-backtest.zh-CN.md)及[验证记录](../../verification/2026-10-17-daily-basis.zh-CN.md)。

## U17. 原文明确的先行收盘条件（2026-10-17）

用户要求分析零成交并自动处理原文明确信息，授权增量添加 Schema 5 条件 `DailyPriorClose`（`type: DAILY_PRIOR_CLOSE`、`since_date`、`price_fen`、`comparator: GT | GTE`）。不修改接口路径。仅从 `since_date` 当日开始、更早交易日的完整收盘可满足先行条件；最新日线所属交易日用于后续判断，不能同时证明两个阶段。必须有已准入的价格基准和历史依据。历史缺失或截断保持 `MISSING_INPUT`；完整窗口内没有合格先行收盘则为 `UNSATISFIED`，原因 `PRIOR_CLOSE_NOT_SATISFIED`。

自动规范化要求原文明确唯一的收复门槛、先收复再回踩的顺序、尚未收复的现状，以及已确认生效日。该日期作为准备元数据界定新的收复窗口；未修改的继承规则保留原窗口。收复条款和回踩条款均绑定原文证据；不为回踩、蜡烛形态、量能和相对指数描述补造数值阈值。已知不满足的前置条件决定 `ALL` 结果时，未知子条件仍可见。审核把已知前提展示为自动处理事实，业务问题仅保留待明确口径。已审核版本和结果保持不可变，采用新表达需要重新提取、审核和回测。

请求压缩移除重复的 schema 标题和判别注解，保留联合类型约束、原文、字面值及服务器校验。两份生成契约及 TypeScript 类型均包含新条件。验证另见 [ZF-V01–ZF-V04](../../verification/2026-10-17-zero-fill-audit.zh-CN.md)。

OpenAPI 快照 SHA-256：`fb3f08ff3826ae1d07be99c994565bea70d1667344280b966afe5579b9845df5`

规范监控 v2 OpenAPI 快照 SHA-256：`172d21503bca7283c5a6eea6d0279770187c0c16e43317854e0ed0ba828e41ba`

## U18. 逐份计划结果诊断（2026-10-17）

用户的结果页需求授权在已有 `BacktestLoopRunView`、`BacktestScheduledRunView` 中增加可选 `planDiagnostics: LoopDiagnostics | null`；接口路径、冻结报告格式、报告哈希及执行行为不变。诊断内部字段沿用原生 snake_case。`availability` 为 `AVAILABLE | EXPIRED | UNAVAILABLE`；`plans` 按冻结顺序包含 1–256 份身份。每份包含来源／版本／生效日、买入规则及成交／评估数量、根条件结果统计、`review_status: PASSED`、分类、示例和抽样标识。保留的审计明细不可用时，逐份成交数为 null，不补造成零。

示例将审计序号／时间及根条件结果，与要求、实际依据和原因绑定。分类区分 `MARKET_UNMET`、`QUALITATIVE_UNRESOLVED`、`PROCESSING_ERROR`、`DATA_UNAVAILABLE`、`EXECUTION_BLOCKED`、`NO_BUY_RULE`、`NO_EVALUATION`、`CONDITION_MET`。每份最多八条示例，总计最多 256 条；统计所有保留评估，合并按日重复条件，示例排除旧日线的重复延续。十进制价格保留不足一分的精度。先行收盘要求旁的当前行情价明确标注，不得当作合格先行收盘。`ANY` 已有备选满足时，不把未采用分支的未知条件展示成阻断。

在同一只读事务内读取结果持有的不可变输入和保留审计，校验记录／事件身份和已发布完整事件流摘要后返回有界投影；发布阶段的语义校验保持权威。失败／未审核准备记录不属于已完成回测，不能将其缺席诊断为当前提取失败。明细缺失时明确返回可用性。读取诊断不调用 AI、不修改策略、不要求手工确认、不新建回测。原生视图校验版本、来源日期和成交总数绑定；前端也支持合法 `POSITION_LIMIT_ONLY` 及独立审核计划库成员的 null `baseHash`，非空前序关联校验保留。参见 [RD01–RD03](../../../tasks/result-plan-diagnostics.zh-CN.md)。

OpenAPI 快照 SHA-256：`4875f2c9c4404909ea78e285bccb0d92896675e0ad5dc7554acfdf3931f016d2`

规范监控 v2 OpenAPI 快照 SHA-256：`1a38659bbb064a60c9c604089d2b8479d0f51bda1eff8bed36da11662a67786d`

## U19. 通用前序继承与有界纠正（2026-10-17）

用户的通用流程请求授权有版本的 `PREDECESSOR_PATCH` 解释：准确的已审核前序默认提供全部未提及规则和字段。仅对新增量候选替代 U15 的明确保留要求；历史冻结输入保留原解释。引用原文的语义变化按稳定身份表达 `RETAIN`、`MODIFY`、`ADD`、`REVOKE`，不增加接口或自动审核权限。

增量可选元信息包括操作的 `intent`／`rationale`、条款的 `semantic_role`、`SOURCE_SEMANTIC` 绑定及准备解释契约。每次失败的准备调用可保留最多 64 条、每条最多 512 字符的 `repair_feedback`，以及最多 32000 字符的 `repair_context_json`。最多两次自动纠正与原三次调用上限共享预算；每次仍绑定原文、前序和工作进程占用。诊断描述处理错误。真实原文歧义仍是业务问题，未提及的未变规则无需确认。前次未审核候选仍是不可信纠正上下文，不能自行批准。

内部 AI 传输现请求 `monitor-loop-delta-wire-v3`，包含执行授权和时间先后结构检查，不增加公开接口。候选存储使用无损 `source-clause-pool-v2` 证据／路径去重，限制展开体积并兼容历史读取；公开格式及下方哈希不变。明确撤销的规则在最终数量校验及证据索引解析前移除。

两套生成接口及前端契约均反映这些增量内容。此处记录契约范围，不代表真实模型验收通过或已部署。参见 [GI-01–GI-02](../../../tasks/generic-plan-inheritance.zh-CN.md) 和[验证记录](../../verification/2026-10-17-generic-inheritance.zh-CN.md)。

OpenAPI 快照 SHA-256：`f0a049aaacea9bf5d9371bc6402c5954cd8bb4c83097cf9aa18d55e63432d0c8`

规范监控 v2 OpenAPI 快照 SHA-256：`bfeab749334df8adbd2324be09ab2b3e1153d3b8d6928c53928f06a49e9f44b1`


## U20 — 冻结结果规则对照

已完成的连续回测提供只读、单份响应 `GET /api/v1/backtest-runs/{run_id}/rule-changes/{source_id}`。`BacktestRuleChangesView` 绑定 `runId`、`manifestHash`、`sourceId`、`versionId`、`previousSourceId` 和 `previousVersionId`；`relationship` 为 `INITIAL`、`INHERITED` 或 `INDEPENDENT`。`changes` 最多包含 64 项 `PlanChange`，提供完整 `before`／`after` 值及 `RETAIN`／`MODIFY`／`ADD`／`REVOKE` 分类。比较最终冻结的政策区块和稳定规则标识（风险分支使用 kind），忽略计划身份字段及列表重排。不重新解读原文，也不依赖纠正前已过期的变更清单。旧独立版本比较相邻政策，但不宣称审核继承。运行、原文不存在或不支持的单计划运行返回 404。

结果界面一次加载一份，校验运行／清单／版本／前序标识，拒绝过期响应，并提供明确重试。显示所有分类和完整字段，区分修改规则中的未变化字段，将整数分值和固定 FEN 参照换算为元。现有结果汇总大小边界及冻结报告身份不变。不调用 AI、不回放、不迁移数据库、不新增交易授权。验收及双语验证遵循 `tasks/result-rule-comparisons.zh-CN.md`。

OpenAPI 快照 SHA-256：`cbc73be169c2f0a9b2758f8f93655813a6b8d17279a1340457ac30a4a320ae38`

规范监控 v2 OpenAPI 快照 SHA-256：`6dd7e9edf672b427782a9714e86e5bf364d50381a85b1963301914639a2b5f2c`


## U21 — 风险取消的适用范围

本次原文复核授权为 `PlanUpdateOperation` 增加可选 `scope_assessment`：`ENTIRE_RULE | PARTIAL_RULE | CONTEXT_ONLY | UNCLEAR`。旧序列化未提供时继续省略。新的私有 `monitor-loop-delta-wire-v4` 要求逐条判断前序风险分支的适用范围；缺少判断属于次数受限的 AI 自动纠正，不是原文缺失问题。携带适用范围的保留操作不能在背景归一化时丢失。整体取消需要整条规则的授权，排除新仓不等于删除所有持仓的保护。当部分范围无法表达时，在不可执行候选中保留前序风险／价格证据。`UPDATE_PARTIAL_SCOPE_UNSUPPORTED` 表示系统执行能力限制，不是需要手工补填的事实，也不授权不加限制地执行继承退出。

历史冻结读取保留原哈希。新计划库前序／组合使用重新校验，旧范围问题返回 `REVIEWED_RISK_SCOPE_RECHECK_REQUIRED`。仅已审核记录可请求历史校验。本次不增加端点或按持仓范围执行的引擎。参见 [RW-01–RW-03](../../../tasks/risk-withdrawal-scope.zh-CN.md) 和[原文核对](../../verification/2026-10-17-risk-scope-audit.zh-CN.md)。

OpenAPI 快照 SHA-256：`ddeb1af3aec464d7ac62410df7b3fba991994626555c12b8eb104897d474fe28`

规范监控 v2 OpenAPI 快照 SHA-256：`dff005b984e4c76406c7529306f7fbb88f3bd75a17036cbf2966dc1f6725c891`

## U22. 按持仓批次执行风险退出（2026-10-18）

用户授权补齐 U21 记录的范围执行边界。Schema 5 风险分支增加可选 `holding_scope`（`mode: BEFORE_TRADE_DATE | FROM_TRADE_DATE`、`trade_date`、可选且不包含该日的 `end_trade_date`）、稳定 `rule_id`，以及普通风险成对的 `risk_line_fen` / `risk_comparison`。最多支持 64 个不同风险标识。Schema 4 契约不变；可选字段缺省时保留历史序列化。后续限制取持仓日期窗口的交集，不能悄悄扩大继承保护的范围。

原文明示排除新仓时，转换为有原文证据的适用范围修改，保留前序价格、目标、确认及停牌政策。未提到旧仓指令时继承已审核前序。`scope_change: EXISTING_POSITIONS_ONLY | NEW_POSITIONS_ONLY` 为可选操作元数据。私有 `monitor-loop-delta-wire-v5` 和次数受限的专项范围纠正区分新旧仓适用性与整条规则取消。缺少方向属于自动处理的提取纠正；真正的原文歧义单独保留。不要求用户手工确认以弥补引擎限制。不为新仓编造止损。

风险判断、买入阻断及义务完成只针对适用持仓。初始持仓可以通过更早的期初观察时间归类，不编造买入日期。新模拟批次及回测批次可选记录 `plan_version_id`。风险动作、模拟状态及回执可选保留 `lot_allocations`（`id`、`bucket`、`quantity`），沿用最多 500 批次的边界。执行时原子重算授权分配，遵守 T+1 和已知可卖数量，扣减准确批次并释放对应实际成本。旧批次不可卖时不能改卖被排除的新仓。计划切换保留已锁定确认；适用持仓退出后，即使还有其他持仓，该义务也正常完成。

既有 API 路径提供这些增量字段；不增加端点或交易审批。结果页在完整规则对照旁展示适用范围及实际退出批次。完整对照边界为 192 项，覆盖最多 64 个风险分支中新旧标识互不相同及政策区块的情况；变更提案仍最多 64 个操作。历史冻结结果保持原样；修改后的已审核政策产生新的输入／运行身份。参见 [CR-01–CR-03](../../../tasks/cohort-risk-execution.zh-CN.md) 和[实际验证](../../verification/2026-10-18-cohort-risk-execution.zh-CN.md)。

OpenAPI 快照 SHA-256：`5d6dff24961ae06dafe422211775851ff1fc55cbb91267e9d5b79f8a58261404`

规范监控 v2 OpenAPI 快照 SHA-256：`4c033709abf001c88e6a1ae9ee667b90359b51a3f34b6d34ad63edc9ef3b73d9`

## U23. 运行记录覆盖日期筛选（2026-10-18）

用户授权简化运行记录筛选，并区分回放截止与实际执行完成。所有结果类型的常用日期均指包含边界当天的覆盖结束日 `eventEnd`。`GET /api/v1/backtest-runs` 增加可选 `eventEndFrom` / `eventEndTo`，分别为有效 `YYYY-MM-DD`；逆序区间、无效日期、重复键和未知查询键仍拒绝。与既有条件使用 AND 组合，在 SQL 分页前参与签名游标上下文。存储比较规范摘要的 `event_end`，不比较 `completed_at`、任务完成时间或今天日期。

既有筛选响应增加可选可空日期字段，未使用时省略，因此旧无日期筛选响应和游标上下文不变。前端核对回显日期条件及每项返回结果的覆盖日期。旧 API 客户端／链接的 `completedFrom` / `completedTo` 保持原结果时间语义，不重新定义为实际任务完成时间。历史连续回测的 `completedAt` 是证据截止时间。冻结报告、哈希、存储时间戳、保留规则和固定 `completedAt:desc,runId:desc` 顺序不变。表格将该值标为结果时间，静态文字说明排序；实际任务完成仍是独立任务事实。

界面包含股票、覆盖截止日期及固定状态。根据用户进一步简化要求，数据集哈希和单版本 ID 不再提供筛选控件或折叠入口。页面 URL 在首次列表读取前清除 `datasetHash` / `planVersionId` 及其游标，保留其他条件并返回第 1 页；内部 API 筛选和存储标识不变。旧时间链接条件仅在已有条件时明确标为“旧链接时间条件”，不静默转换为覆盖日期。参见 [RF-01–RF-03](../../../tasks/run-record-filters.zh-CN.md)及[验证记录](../../verification/2026-10-18-run-record-filters.zh-CN.md)。

OpenAPI 快照 SHA-256：`a94974a7d4b7ec26239b72574d87b4a97fd3dbda353833b5a7eb7056e398d67b`

规范监控 v2 OpenAPI 快照 SHA-256：`a3833f1fac7735528866dd2ab3a6989ce519657c45c9e044871a626d51784e7d`

## U24. 历史读取与准备进度可靠性（2026-10-18）

只读元数据调用可等待既有归属线程：最多 8 个等待读取，每个准入等待最多 5 秒。每个元数据归属者仍最多执行一个物理调用。写操作继续在占用时立即拒绝；重任务准入、线程数量、控制响应、初始化看门狗及物理排空规则不变。等待中取消／超时不会事后提交工作，取消正在执行的 HTTP 等待者也不释放物理线程。完成／清理在获取元数据槽位前会观察已准入的读取。SQL BUSY/LOCKED、过载及停止服务保留既有 503 契约。

回测历史及计划库 GET 传输仅重试明确的 `SERVICE_UNAVAILABLE` / 503，最多 3 次总尝试，间隔 1 秒，等待可取消。不重试 POST/PUT、其他错误或无效成功响应。计划准备轮询独立保留：已有工作进行时每 2 秒读取；首次读取或终态详情不完整时，对临时 503／修订 409 最多增加 3 次刷新。只有摘要和详情完整读取成功才重置恢复次数。导航／卸载会中止计时器及过期读取。GET 不重发提取、审核、取消或执行。

前端准备校验接收既有可选 `confirmationSummary`、`repair_feedback` 和 `repair_context_json`，保留封闭字段、原文／修订绑定及诊断上限（64 条反馈，每条 512 字符；上下文 32000 字符）。准备投影在 2 MiB 之外同时执行前端既有的 50000 节点／32 深度预算；详情自适应分页通过 `nextOffset` 返回剩余完整条目，不截断原文证据或提高上限。不补造原文事实或跳过语义审核。旧候选存在必需补充项时，即使有确认汇总也继续展示对应控件；仅供展示的汇总不能隐藏未完成审核要求。准备初始化日志区分看门狗超时和失败类型，不记录原文正文或凭据。

公开模式、OpenAPI 快照、哈希、存储候选和冻结报告均不变。参见 [BR-01–BR-03](../../../tasks/backtest-read-reliability.zh-CN.md)和[验证记录](../../verification/2026-10-18-backtest-read-reliability.zh-CN.md)。

## U25. 开始时自动准备数据（2026-10-18）

用户已授权移除四个人工准备入口。已审核原文回测在开始后检查本地证据、补齐已结束日期的历史数据、重新验证，再提交冻结计划回测命令。开始操作授权本次有界数据准备；访问页面、读取 URL 不下载数据或授权 AI。现有同步、验证 API 保持兼容。旧版本与数据集回放继续使用其已冻结的数据集。

增量只读契约为 `GET /api/v1/backtest-run-data?preparationId=...&manifestHash=...&endDate=YYYY-MM-DD`。可选 `endDate` 保留既有上海提交日期默认值。`PreparedBacktestDataView` 返回 `preparationId`、`manifestHash`、`endDate`、`ready`、`syncScope` 和 `blockers`，设置 `Cache-Control: no-store`。必须绑定准确的已审核清单；无效、重复、未知查询和过期绑定失败。股票、开始日期、预热和可同步结束日期由服务端规则与日历推导。最终提交重新校验执行依据、边界和证据后复制输入。不增加工作线程、任务种类、数据库迁移或 AI 调用。

只有明确开始且数据缺失时才串联现有持久化 `DATA_SYNC`，使用 `allowNetwork: true` 和 `refresh: false`。权威进度采用既有串行 2 秒轮询。验证失败阻止 `BACKTEST_RUN`。变更回执丢失时保留原请求体和键，结果不明时不得替换为新操作。明确重试会重新检查缓存，保留已完成下载。即使同步迟到成功，取消也阻止后续执行。卸载页面中止读取并阻止后续命令；已接收的服务端任务仍可通过记录查看和取消。刷新页面不静默续接流程或恢复历史任务。

可变缓存缺失时，准备流程可复用结果自带且校验通过的事实。最多检查 20 个首份计划匹配的输入。计划日历与审核依据、期初账户、数据要求、股票日期口径和准确证据截止时间必须一致；保留预热可以更长，不能更短。每个复制日和 artifact 哈希均须校验。新提交单独绑定自己的边界、输入和数据集标识，复制相同事实字节，不修改旧输入、复制日或报告。不同截止时间、不同规则依据或损坏证据不得复用。现有保留与维护机制不变。

历史数据管理改为只读：移除 `应用到当前 URL`、`同步历史数据`、`本地验证数据集` 和 `刷新已缓存表面`，保留筛选、分页和任务查看、取消。见 [AD-01–AD-03](../../../tasks/automatic-backtest-data.zh-CN.md)。用户已批准该具体行为，下方哈希标识增量数据检查契约，不代表交易规则或历史报告发生变化。

OpenAPI 快照 SHA-256：`6de1b8500f2b6bb217e419c191861579bb27cdaa8ee40078c1b6e566ddee2228`

规范监控 v2 OpenAPI 快照 SHA-256：`6a49893bef934394a1034eed225711cc152fb47684322878b2c84b6e08f9ad95`

## U26. 隔离已验证结果读取（2026-10-18）

剩余已完成结果 503 是已测量确认的元数据队头等待超时。汇总投影必须在同一保留一致快照中，只读取校验一次复制输入、原生报告与诊断。保留复制日规范字节及哈希检查、报告输入汇总绑定、类型化保留事件及其完整已发布摘要、诊断预算与过期状态。不改写证据、规则、历史输入、报告或 SQL 投影。

区别于 U24 的短元数据重叠修复，本次跟进增加一个惰性有所有者的结果读取线程，不增加重执行工作线程。汇总、规则对照和权益投影使用该通道，最多一个物理调用、8 个观察者及 8 个不同进行中键，不同排队工作准入等待 60 秒。元数据保留 8 个等待读取及 5 秒；写操作准入与重任务槽位不变。相同并发结果读取按操作、运行、来源键共享活动工作，汇总键还包含固定状态。完成后移除共享工作，后续请求重新校验当前存储证据，不得用持久响应缓存隐藏保留或损坏变化。

取消观察者绝不取消其他观察者或释放物理工作。停服、排空统计纳入新所有者，保留脱敏 SQL BUSY/LOCKED、停止及过载 503/Retry-After 行为。公开路由和 schema、OpenAPI、依赖、数据库 schema 及 AI/联网权限不变。实际验证对比新旧报告完整响应及保存哈希的全部 50 份自有文件；[RR-01–RR-03](../../../tasks/result-read-isolation.zh-CN.md) 及[验证记录](../../verification/2026-10-18-result-read-isolation.zh-CN.md) 记录本次范围内结果，不保证永无 503，也不代表负载认证。

## U27. 已审核计划统一复用，2026-10-19

OpenAPI 快照 SHA-256：`2b5963fcb0b5445fac66a4e701b608b22f0a441949da81956345a2c33a1c3985`。Canonical monitor v2 snapshot SHA-256: `ed664052450bd40c9978571c855ee4ed704d369d4853a667877277bbc8ed262f`。用户批准 PRU01–PRU11 的有界实施，并明确授权删除 JSON/YAML 导入接口。参见[规格](../backtesting/SPEC-plan-reuse-unification.zh-CN.md)及[验证记录](../../verification/2026-10-19-plan-reuse-unification.zh-CN.md)。

新增 `POST /api/v1/backtest-plan-selections` 和 `GET /api/v1/backtest-plan-selections/{selection_id}`，在现有数据检查／运行命令及结果联合类型增加绑定选择的工作台分支。冻结原审核计划身份与单独确认的历史研究上下文，无需重新提取或实时启用。新增复制输入使用 `monitor-loop-stored-input-v3` 和 `workbench-loop-input-v1`；旧编解码、哈希、结果字节及准备多计划执行保持权威。仅带标记准备存储增加一张不可变选择表（schema 1 → 2），旧程序会拒绝升级后的存储。

删除 `POST /api/v1/plan-imports`、`PlanImportCommand`、`PlanDocumentFormat` 及直接前端客户端／表单。已删除端点返回现有 404 信封。内部 JSON/YAML 编解码、原文准备、已有计划和结果继续可用。其他全部 API 路径、监控／供应商／错误／安全语义保持不变。生成产物与两套挂载契约一致；审批仅覆盖本次增加／删除，不代表真实供应商或部署认证。
