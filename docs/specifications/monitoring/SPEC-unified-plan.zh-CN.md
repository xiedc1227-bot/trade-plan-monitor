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

当前正式 API 操作使用 `/api/v1/plan-extractions`、`/api/v1/plan-drafts`、`/api/v1/plan-imports`、`/api/v1/plan-review-previews`、`/api/v1/plan-review-supplements`、`/api/v1/plan-review-confirmations`、`/api/v1/plan-activations`、`/api/v1/plan-deactivations`、`/api/v1/plan-facts`、`/api/v1/simulation-position-confirmations`、`/api/v1/simulation-position-inventory`、`/api/v1/plan-risk-reassessments`、`/api/v1/simulated-trades` 和 `/api/v1/plan-runtime/{symbol}`。当前路由没有独立 `/daily-*` 操作族。AI 供应商配置在 API 中只读，并从项目文件一次加载。旧 `dailyMapping` 传输字段和内部 `Daily*` 名称作为共用审核/记账兼容细节保留，不能构成第二套当前流程。

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

两种语言保持 U01–U09、字段名、格式号、API 路径、时序、边界与验收标准一致。当前索引指向本文。保留有用的冻结兼容约束及必要验收证据；从维护目录删除被替代规格与已完成过程记录。历史 Git 证据不授权当前行为。

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
