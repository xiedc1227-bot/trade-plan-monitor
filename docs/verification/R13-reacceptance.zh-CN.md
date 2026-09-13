# R13 独立离线复验

日期：2026-09-13，Asia/Shanghai。任务 `01a098d6-b8b2-7953-80de-942d4ea78fdd`；协调任务 `01a093fc-f8d3-73d1-b759-ad76c7451697`。无后缀英文稿为规范输入，本文件为语义等价的中文审阅稿。

## 1. 结论与范围

**完整离线验收 NOT PASSED；暂不建议批准 C6。** N01–N04 和已测原始监控要求具有本次直接离线闭合证据，包括四种真实 OS 进程重启场景。强制完整浏览器门禁仍有一个新复现的 P2 布局失败。R14 真实供应商／用户可见闭环仍为 **NOT_RUN**。最终检查点结论由协调任务决定。

| 核心问题 | 独立结论 |
| --- | --- |
| 目标是否一致，计划是否忠实转换？ | 对于未改写的完整原文、有限支持语法及独立补充的测试政策，是。字段、原文区间、单位、逻辑结构、审核身份和数值独立预期一致。这不证明任意中文或真实模型的准确率。 |
| 当前已审核版本是否进入实际监控链路？ | 在隔离离线执行中，是：普通浏览器创建／审核／公开激活 → 真实组合／调度器／供应商适配器 → 显式求值 → SQLite 结果／状态／事件／outbox 原子提交 → IN_APP 及浏览器可见提醒。供应商边界为合成输入。 |
| 该提醒时是否可见，不该提醒时是否避免误报？ | 已测 BUY／SELL／纯风险、边界、未完成数据、重放、版本、停用、到期、浏览器恢复及进程重启均符合有限场景预期。完整浏览器门禁未绿，故仍不通过完整产品验收；真实交易时段送达未测。 |

产品用于监控已有计划，不是策略生成、选股、券商、下单系统或盈利评估。阅读／ACK 从不代表成交；只有独立库存操作改变持仓。

起始工作树：`main/cc328adb4f79b9673705cb67e67520da2dfd667b`，另有12个受保护用户修改和4个 R00 未跟踪文件。未切分支、reset、stash、暂存用户 hunk、安装依赖、请求真实 AI／行情、向外部渠道投递、交易、操作生产库／真实持仓、push 或发布。唯一获授权的跨任务消息是最终协调交接。历史 `R13-business-acceptance`／`R13-matrix`／`handoffs/R13` 及原 NOT PASSED 证据保持不变。

## 2. 不变原文与独立预期

`tests/fixtures/ai/explicit-plan-literal-source-v3.json` 未改动。完整原文仅有已授权的 `测试股票` → `003043.SZ` 替换，包含此前持有且可卖100、上限300；完成5m收盘处于两端包含的[9.80,10.00] AND 当前量≥前五根完成5m算术均量的1.5倍 → BUY100；两端包含[10.80,11.00] → SELL100；收盘<9.50 → quantity=null 的 RISK_ALERT。原文库存描述从不写入账本。

原始完整原文流程独立填写八项 USER_SUPPLEMENT：TRADING_DAY、2026-09-14、CONTIGUOUS_TRADING_BARS、三项 ONCE_PER_ACTIVATION、BLOCK_BOTH 和 RISK_ONLY。缺少政策或未确认原文处理仍阻断。这些是测试输入，不归入用户原始计划文字。

独立生产管线预期使用[100,100,100,100,600]：算术均量200、中位数100、阈值300。当前量200／299不买，300／301仅在价格条件也成立时买。六个买入价格邻点与四个量值交叉，另九个卖出／风险邻点验证包含性和严格风险不等式。原 ALL 流程与修订流程刻意改成 ANY／BUY200、再改成 ALL／BUY100 的独立新意图分开验收。

契约输入为 R08 SPEC-executable-plan-extension／ADR0005 和 R11 SPEC-source-treatment-review／ADR0006。保留 Schema1/2、历史 mapping／evidence 哈希、prompts v1–v4 及旧版研究成交语义。显式模式仍有有限边界：本验收不推导任意运算符、树结构重排、时序、策略生成或 Schema3 组合回测能力。UNKNOWN 库存／可卖量保持 null，仅阻断依赖它们的交易；已知持仓、可卖、上限和适用规则约束定量输出。纯风险不要求无关成交量或库存。

## 3. 本次生产与浏览器证据

| 阶段 | 当前实现对象／位置 | 本次证据 |
| --- | --- | --- |
| 组合与生命周期 | `web/monitor_composition.py:671` `create_monitor_composition`；`runtime/service.py:2507` `RuntimeLifecycleService`；`runtime/scheduler.py:73` `MarketSessionScheduler` | 普通无业务预置浏览器流程及进程重启运行后台生命周期。 |
| 当前计划及取数 | `runtime/production.py:214,242,514` `ProductionMonitorPipeline`；`runtime/service.py:2290` `RuntimeDeadlineCoordinator`；`runtime/symbol_service.py:141` `SymbolService` | 真实活动版本／哈希／revision 选择、SDK 归一化、完成 cutoff 和调度期限；没有浏览器直接求值捷径。 |
| 求值与提交 | `runtime/explicit_service.py:85,115,167` `ExplicitRuntimeEvaluationService`；`decision/explicit_conditions.py:198`；`decision/explicit_rules.py:269` | 独立算术预期、规范 decision-result-v2 哈希校验、账本／出现状态／事件原子提交、事务回滚及重复／revision 防护。 |
| 投递与当前有效性 | `notifications/channels.py:178,348` `InAppChannel`／`_require_event`；`notifications/dispatcher.py:220`；`notifications/outbox.py:290,307,331` | 严格 AlertEvent／ExplicitAlertEvent 联合；本次 SQLite 首次 IN_APP DELIVERED；替换／停用／到期后旧事件仍为历史。 |
| 审核与展示 | `web/plan_service.py:653`；`web/alert_service.py`；`web/src/components/plans/ExplicitPlanSupplementForm.vue`；`web/src/composables/useMonitorStream.ts` | 当前 review／hash／revision 各自阻断旧激活409；普通反复编辑；可见提醒及断线自动恢复；ACK 后库存仍100。 |

后端位置相对于 `src/trade_plan_monitor/`。[场景矩阵](../../remediation/R13-reacceptance-matrix.zh-CN.md)逐项记录 S01–S09、F01–F09、N01–N05 的输入／预期／实际／测试／证据层级。

所有普通显式浏览器流程均从空临时 SQLite 和空闲 loopback 端口开始，只 seed 日历／历史。计划、审核、ACTIVE 和库存通过普通控件及真实业务 API 创建，不 route mock 业务接口。只 fake AI HTTP 和市场 SDK；受控时间释放真实调度器。合成 READY 认证是测试前置条件，不是本次真实供应商认证。其他既有 UI fixture 测试明确属于浏览器组件层证据。

未改原文流程观测10:05量299／不买、10:10量300／BUY100、10:15 SELL100、10:20 RISK_ALERT／null。三类提醒均可见并确认；直到测试显式执行独立减仓，库存始终100。修订流程重新审核版本3–8，分别拒绝旧 reviewId／contentHash／revision，执行版本5 ANY／BUY200 与版本8 ALL／BUY100，并保留原文。六种 AI 边界失败保持旧活动版本；浏览器断线重连无需手动刷新即显示已提交 SELL 和后续风险。

`remediation/evidence/R13-reacceptance/final-sqlite-lineage.json` 独立关联每条保留事件与已审核版本、planHash、activationRevision、cutoff 及规范校验的 resultHash。原 ALL、修订及四种 OS 重启数据库共有13条已核验事件，每条均只有一次 IN_APP 尝试且 DELIVERED。浏览器可见、数据库持久化、渠道投递及 ACK 分别断言，不互相替代。原始记录／截图位于 `final-journeys/`；`verify_evidence.py` 仅以只读方式复查这些测试自有数据库。

## 4. 活动计划真实进程重启

新增 `r13-active-process-restart.spec.ts` 使用相同原文，但明确为三规则补充 EACH_QUALIFYING_BAR。其独立合成行情在10:30追加量301的合法 BUY bar，因此不能用“一次性策略已耗尽”解释去重通过。正常原文行情／fixture 未改写。

每例均普通输入原文、完整当前审核／公开激活、独立登记100／100；在10:10生成并可见确认 BUY；关闭浏览器；终止测试端点报告的精确服务 PID；核实服务和启动器退出及 ECONNREFUSED；再以不同 OS PID 和同一临时 SQLite 启动。恢复模式不重 seed 历史、计划、审核、ACTIVE 或库存，不把服务对象别名描述为进程重启。

| 场景 | 预期与实际 |
| --- | --- |
| ACTIVE | 相同完成行情／启动恢复及10:11不重复；原已确认事件身份保留。10:15 SELL、10:20风险出现，同一 BUY 规则在10:30产生不同事件。四条均可见确认，所有持久库存字段和 revision 不变。 |
| REPLACE | 退出前普通价格修订9.80→9.81保存／审核／激活为版本3。revision／指针保留；版本2 BUY 为非当前历史；后续 SELL 属于版本3。 |
| DISABLE | 公开停用状态保留；旧 BUY 保持历史及已确认；推进至10:15无新事件。无活动计划的 explicit-runtime API 正确返回404。 |
| EXPIRE | 第二进程在已审核 TRADING_DAY 之后的2026-09-15启动。旧事件非当前；继续推进调度至10:15无提醒。原登记日期库存不变。 |

这证明 fake 供应商输入下本地强制 OS 进程退出恢复，不证明生产优雅关闭、掉电耐久、外部收件人 exactly-once 或真实供应商重连。首次探针失败已保留：测试关闭路由停止监听，但启动器未在15s内退出；下一版探针错误点击已禁用的已确认按钮、把变化的查询 cutoff 当账本字段比较，并对正确不存在的 runtime 期待200。最终探针核对完整账本，仅允许查询 cutoff 推进。这些属于 harness／预期修正，不是业务修复或削弱业务预期。四个早期已记录进程在获授权清理时被独立确认已退出。

## 5. 实际门禁与残留问题

| 命令范围 | 实际结果 |
| --- | --- |
| 完整后端 `-m "not live"`，含原 R13 新增文件 | 2634 passed /1 POSIX-ownership skip on Windows /4 live deselected /1 existing warning;2572.52s |
| 完整前端单元 | 644 passed／45文件；5.10s |
| 初次及新增测试后的前端类型检查／构建 | 通过 |
| 初次完整浏览器 | 29 passed／1 failed；2.7m |
| 未改窄屏回测门禁，有界复跑 | 0 passed／5 failed；同类320px／200%边界违反 |
| 新增布局测量探针 | 已执行；记录四页在字体／渲染稳定前后状态。探针成功运行不等于布局门禁通过。 |
| harness 修正后的活动 OS 重启专项 | 4 passed；1.8m；随后最终完整套件额外推进到期后的次日调度。 |
| 新增测试后的最终完整浏览器 | 34 passed /1 failed;4.5m (35 total, including the diagnostic probe) |
| 本次规范 SQLite 血缘／生成类型／限定 lint／保护 | Passed;13 event lineages; generated types current; scoped lint clean;16 protected files unchanged |
| 真实 AI、真实行情、实际时段用户可见闭环、R14 | NOT_RUN；本步未授权 |

命令 JSON／日志／XML 位于 `remediation/evidence/R13-reacceptance/`。重叠运行不累加。后端收集2639项，在凭证／客户端 fixture 执行前排除4个 live 用例，选择2635项。已完成运行有一个skip，位于 `tests/integration/test_backtest_production_composition.py:492`：本Windows主机不具备所需POSIX归属语义。一个警告为既有Starlette TestClient／httpx弃用提示。容量／内存门禁不被中断或削弱。新增浏览器用例与首次30项收集分开记录。

**N05 · P2 · 已确认 · 回测页面在320px／200%文字下溢出。** 未改门禁在完整套件及5／5专项复跑中失败。独立测量等待 `document.fonts.ready` 及两个动画帧后，`/backtests`、`/backtests/new`、`/backtests/data` 和结果页的页面 scrollWidth 稳定为338、476、617、411，而 clientWidth 为320。旧测试诊断最先列出的五个元素属于有意可滚动导航；完整检查还发现未被滚动容器约束的 hero／表单／结果内容。不能据此归因于 AppShell 用户 hunk。相关位置包括 `BacktestRunsView.vue:110`、`BacktestNewView.vue` hero／grid 布局、`DatasetScopeForm.vue:411,418,444` 及结果后代元素。截图印证测量溢出。

最小后续整改：约束相关回测视图／组件的 grid、flex、控件固有宽度，保留有标签的表格／导航内部滚动及受保护 AppShell 修改。复跑未改四宽度／200%门禁、控件操作、axe 和完整浏览器套件。不得裁切整个文档、降低文字倍率／宽度、删除断言或用重试掩盖。本次独立验收未修业务／CSS。

N01–N04 在各自本次复查的离线范围内闭合；N05 阻断完整浏览器门禁及 C6 完整通过建议。真实模型语义和新鲜供应商／用户送达是未验证边界，不是额外已复现缺陷。

## 6. 保护、产物与交接

`workspace-before.json` 和 `workspace-before.diff` 记录精确起始工作树。最终保护将16个文件与本任务起始字节比较；其中15个也匹配原 R13 manifest，dashboard 整文件变化来自已授权 N04 提交。其唯一用户 diff 仍是原09:35／10:35两根 bar 及第二根 openPoints1231.25。另核验不变原文及历史报告哈希。仅暂存本任务新增测试 harness／探针、证据及三组双语报告／矩阵／交接。

准确本地提交和最终门禁见[交接](../../remediation/handoffs/R13-reacceptance.zh-CN.md)。未创建后继或启动 R14。未来 R14 提案必须先明确实际所选供应商／模型、含重试的物理请求数、费用／额度上限、symbol／endpoints、交易时段／持续时间、临时库、用户复核计划及通知渠道，再另行获授权；本报告不猜凭证或无依据参数。

大型原始trace保留于 `C:/Users/xiedc/.codex/visualizations/2026/09/13/01a098d6-b8b2-7953-80de-942d4ea78fdd/r13-reacceptance-traces/`；`trace-archive.json`记录原路径、新路径、字节数和SHA-256。清理错误传播加强后另跑四种OS用例：4 passed／1.8m，类型检查通过；未再修改业务或门禁阈值。

自编源码／文档／JSON采用限定范围空白检查；原始运行日志保留录制时空白。
