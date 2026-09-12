# R13 独立离线业务验收

日期：2026-09-13，Asia/Shanghai。任务：`01a096d2-805d-7761-92e1-c773709c4b6b`。英文版本为规范输入，配对 `.zh-CN.md` 为中文审阅副本。

## 1. 结论与范围

**完整离线业务验收不通过。** 逐字原文现在能够经过真实提取解析、审核后的公开激活、生产调度、确定性判断、SQLite，最终在真实浏览器显示提醒。但仍有两个 P1 缺口：必选 IN_APP 通道拒绝所有明确规则事件，普通 ALL/ANY 修订不能完成审核。已修订字段还会从编辑器消失。既有浏览器门禁另有失败。本任务没有修改业务实现来掩盖结果。

| 问题 | 回答 |
| --- | --- |
| 目标是否一致？ | 基本一致。Schema3 已表达原始买入、卖出和五分钟风险计划，无需加入旧版 episode、CORE/TACTICAL 或日收盘条件。能力边界仍是有限支持语义与明确人工补充。 |
| 链路是否完整？ | 已测原文正常路径产生可见、可追溯提醒，但完整可用性和投递消费端兼容尚未闭合。IN_APP 存在缺口时，公开激活已经开放。 |
| 验证到什么层级？ | 独立 OFFLINE 执行，使用真实 Chromium、解析器、公开业务 API、SQLite 和生产调度器，并有独立数值、生命周期与故障注入复现。真实 AI 语义正确率、新鲜供应商数据及真实盘中用户可见闭环均为 NOT_RUN。 |

R13 是业务验收，不是盈利评估。完成本报告不等于完成 C6，也不将 R13-A 标为验收通过。R14 实际调用未启动，仍需独立且有边界的授权。

基线：`main/fa316833e8c5d4b427acef4f8500d1e9714a2dd1`，包含既有 12 个用户修改和 4 个 R00 未跟踪文件。验证针对共享工作区，不是干净检出。`remediation/evidence/R13/workspace-before.json` 保存了起始文件精确 hash，最终保护检查另行记录。未 reset、stash、切换分支、暂存用户文件、安装依赖、推送或发布。

## 2. 原文、独立判据与隔离

不可改写的输入是 `tests/fixtures/ai/explicit-plan-literal-source-v3.json`。提交了包含换行的完整 `sourceText`，仅存在已授权的 `测试股票` → `003043.SZ` 替换。原文包含已持有且当日可卖100、最大300；已完成五分钟买入区间[9.80,10.00]包含两端，AND 本根成交量>=前五根已完成K线算术均量的1.5倍，BUY100；卖出区间[10.80,11.00]包含两端，SELL100；收盘<9.50为纯 RISK_ALERT。提醒及确认都不是成交。

八项独立 USER_SUPPLEMENT 为 `activation.mode=TRADING_DAY`、`activation.trading_day=2026-09-14`、`rules[0].condition.conditions[1].history_scope=CONTIGUOUS_TRADING_BARS`、三项 `repeat_policy.mode=ONCE_PER_ACTIVATION`、`conflict_policy.trade_conflict=BLOCK_BOTH`、`conflict_policy.risk_conflict=RISK_ONLY`。这些值经普通控件明确填写，未放入原文。仅原文缺政策时不可激活。原文库存声明只作为来源审核处理；库存保持 UNKNOWN，直到单独按日期登记。

独立数值判据使用[100,100,100,100,600]：总量1000、算术均值200、中位数100、阈值300。本根200/299不买；价格满足时300/301买入。六个价格邻值[979,980,981,999,1000,1001]分与四个成交量交叉组合。另测卖出边界邻值、风险949/950/951、未完成时暂时满足而最终1001不满足，以及替换/停用/到期后的历史提醒状态。这些生产管线测试明确使用可信测试计划和库存准备，不能替代从空库开始的公开浏览器流程。

主浏览器运行使用 `tests/browser/explicit_server.py` 与 `web/tests/e2e/explicit-sqlite.spec.ts`、空临时 SQLite 和空闲 loopback 端口。只预置日历及行情历史，不预置计划、审核、ACTIVE 或库存。只 fake AI HTTP 与行情 SDK，不 route mock 浏览器业务 API。控制路由仅推进时间，真实调度器持有截止任务。合成 READY 认证只是测试前提，不是真实认证。未操作实际 `127.0.0.1:8765`；部分进程内 TestClient URL 使用该字符串，但不会建立网络连接。

其他既有前端流程明确模拟业务 API，归为浏览器组件级证据。安装入口进程测试使用隔离空库且没有供应商凭据。live 标记用例在凭据/配置 fixture 执行前被排除。未调用收费 AI、真实行情额度、外部 Webhook/消息、券商、下单或真实成交，未访问或修改生产库和真实持仓。

## 3. 实际生产链路与新运行证据

| 阶段 | 基线下检查的实现 | 本次执行证据 |
| --- | --- | --- |
| 组合与后台生命周期 | `web/monitor_composition.py:91,544,671,696,715`；`RuntimeLifecycleService` 与 `MarketSessionScheduler` | 隔离浏览器服务使用真实组合，记录22个时钟截止任务。 |
| 当前活动快照与采集 | `runtime/production.py:214,242,290,514`；`runtime/service.py:2290` 的 `RuntimeDeadlineCoordinator`；`runtime/symbol_service.py:141` 的 `SymbolService` | 真实活动版本2、认证测试 SDK 分钟采集、冻结截止时间；没有从浏览器直接触发判断。 |
| 明确规则分派与确定性判断 | `runtime/service.py:2440`；`runtime/explicit_service.py:85,115`；`decision/explicit_conditions.py:198`；`decision/explicit_rules.py:269` | 精确均值/区间判据，BUY/SELL/数量为 null 的 RISK_ALERT。 |
| 原子结果/状态/事件/outbox | `runtime/explicit_service.py:167`；SQLite `explicit_evaluation_ledger`、`explicit_rule_occurrence_state` 及提醒/outbox 行 | 四个结果 hash 通过验证，三个事件保留。独立回滚/重试/重建服务测试覆盖持久去重。 |
| 必选投递消费端 | `web/monitor_composition.py:698`；`notifications/channels.py:182,343`；`notifications/dispatcher.py:220` | **失败**：IN_APP 拒绝 ExplicitAlertEvent，记录 CHANNEL_FAILURE 及有界重试。 |
| API 与浏览器展示 | `web/alert_service.py`；明确规则运行 API；`useMonitorStream.ts:117,154`；真实计划/总览/提醒页面 | 已视觉检查持久化条件值及全部三种提醒。确认提醒后库存仍为100。 |

除标明的前端文件外，上表路径相对于 `src/trade_plan_monitor/`。[需求与场景矩阵](../../remediation/R13-matrix.zh-CN.md)列出测试对象和 F01–F09 结论。

本次独立主浏览器证据在 `remediation/evidence/R13/`。服务创建的目录为 `C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-v9bgfe21`；已持久复制 `browser-evidence.json`、`browser-checkpoints.json`、七张 PNG 与 `lineage.json`。该 JSON 记录浏览器 warning/error 为0、外部请求为0、fake AI 请求为1。这不代表其他测试也没有控制台错误。

| 合成2026-09-14时间 | 实际结果 | 累计提醒 | 库存 |
| --- | --- | --- | --- |
| 10:05 | 299 / 均值200 / 阈值300：无 BUY | 0 | 100/100 |
| 10:10 | 300 / 均值200 / 阈值300：BUY100 | 1 | 100/100 |
| 10:15 | 已完成收盘1080：SELL100 | 2 | 100/100 |
| 10:20 | 已完成收盘949：RISK_ALERT，quantity=null | 3 | 100/100 |
| 确认全部提醒 | 三次独立确认 | 3 | 100/100 |
| 单独登记实际库存减记，再停用并推进10:25 | 无新事件；历史事件 currentActionable=false | 3 | 仅在独立减记后成为0/0 |

三个事件都绑定计划版本2、activationRevision1 与 planHash `cbb71570023277674140a16ea0ea772827a4371a08f7e7f8b4b2706fc30d2e06`。`lineage.json` 仅以 `mode=ro` 读取该临时库，将各截止时间/事件关联到账本 resultHash，并通过规范领域校验器验证持久化结果 JSON。BUY eventId `e5928068-29c4-5554-9469-80e72628afdf` 对应 resultHash `dd42449e7c5586bbed1f5b95ea950677ca0e26824b456d0f9492a2ebdaddbd99`。该文件保存 SELL、风险事件身份及全部四个结果 hash。API/页面可见、通道 DELIVERED 和人工确认是三个不同结论；页面可见不能消除投递失败。

独立的 `r13-live-stream.spec.ts` 真实浏览器流程也通过：持续停留提醒页、不手动刷新，收到BUY；浏览器断线期间产生SELL，重连后收到SELL；随后收到RISK_ALERT。全部确认后库存仍100。`stream-evidence.json` 与 `stream.png` 保存了第二次无预置的普通/公开/生产组合运行。浏览器离线模拟不是真实供应商故障；IN_APP失败仍独立于页面自动刷新存在。

## 4. 已确认残余问题及最小重验

### N01 · P1 · 必选 IN_APP 拒绝 Schema3 事件

实际浏览器 SQLite 有八次 IN_APP 尝试，全部 CHANNEL_FAILURE；BUY 第4次最终 FAILED，SELL 和风险在关闭服务时仍为 RETRY_PENDING。`InAppChannel.deliver` 调用 `_require_event`，后者检查 `type(event) is AlertEvent`，拒绝 `ExplicitAlertEvent`。调度器将异常转成可重试失败。独立生产管线分别复现 BUY、SELL、RISK_ALERT：要求 DELIVERED 的三个测试全部失败。

影响：API 和直接已提交事件发布使持久提醒可读，但必选投递消费端始终不能成功。`publicActivationAvailable=true`、`isolatedTrustedReviewOnly=false`、`pendingRequirements=[]` 是当前 API 的实际响应，并不证明所有消费端已就绪。这违反 R08 E06/E09/E10 能力就绪合同。

最小修复：必选通道校验及载荷处理明确支持版本化事件联合，保留旧版校验及纯风险 quantity=null，并按实际消费端支持状态确定能力开放。不能仅将失败改标成功。重跑 `test_r13_channel_acceptance.py`、既有投递/传输回归和完整浏览器流程，独立检查 IN_APP 尝试及事件身份。

### N02 · P1 · 普通逻辑修订无法完成复核（F08 仍未闭合）

新增真实浏览器修订测试从逐字原文和公开审核激活的版本2开始。价格980→981、BUY 数量100→200保存成版本3/4，原文保留，contentHash 改变，reviewId/canActivate 重置，并可完成新审核。对每个后继版本复用原审核均返回409，版本2仍保持活动。

将 `rules[0].condition` 从 ALL 改为 ANY 后生成版本5，但 `rules[0].condition.type` 出现 `UNMAPPED_PLAN_FIELD`，只允许 `REPLACED_BY_REVIEWED_CONTENT`。复核框禁用，普通表单无法完成审核。`ExplicitPlanSupplementForm.vue:148,161,200` 修改了所选 STRUCTURE 绑定，却未同步相应 `.type` 标量绑定；服务端协调删除了已失效的旧绑定。这是安全拒绝下的能力缺陷，不是激活绕过。

此外，line48 的 `editableBindings` 只接受 SOURCE。修订后字段变为 USER_SUPPLEMENT 并从普通可编辑选项消失，因此无法再次修正该价格/数量/逻辑。最终浏览器测试保留四个失败断言（一项逻辑修订不可复核，三项字段不可再次编辑）。证据：`corrections.log`、`corrections-evidence.json`、`corrections.png`、`web/tests/e2e/r13-corrections.spec.ts`。

最小修复：将逻辑运算符及必需的值/结构绑定作为一次人工补充编辑原子更新，保留原文及变更来源；允许再次编辑当前受支持的 USER_SUPPLEMENT 字段。重跑连续价格/数量/逻辑修订、各字段第二次编辑、旧审核拒绝、当前复核与公开激活。用户确认的 ANY 计划是刻意变更范围，绝不能计作原始 ALL 判据通过。

### N03 · P2 · 个股详情响应式回归

视口320、文字200%时，既有个股详情测试测得 scrollWidth412 > clientWidth320。独立重跑复现，截图可见日期控件被裁切。该用例后续宽度及末尾 axe 断言未执行。影响是已测布局下普通审核操作的可用性，不是交易规则缺陷。最小修复：限制相关详情控件/布局尺寸，保留阈值重跑四个宽度及无障碍检查。

### N04 · P2 · 既有浏览器门禁夹具/生命周期审计需修复

四项仪表盘用例未模拟新增 `/api/v1/plan-versions?offset=0&limit=100&status=ACTIVE`，Vite/API 夹具返回404。持仓命令用例的库存/人工风险夹具覆盖已过时，全局 `role=alert` 选择器匹配两个无关错误。真实隔离原文页面没有这些模拟 API404。应保持断言，补齐夹具合同并缩小相关元素定位，不能屏蔽控制台错误。

安装入口进程重启用例已读取重启后的类型化空库响应，随后因页面在刻意停服期间仍有请求而出现 ERR_CONNECTION_REFUSED，控制台审计失败；临时目录清理还报 Windows EPERM。重复运行同时复现两项。它既不证明活动计划重启失败，也不能算安装入口门禁通过。需区分预期离线过渡与意外请求，并修正测试目录清理。EPERM 是实际操作系统错误；没有提供自动审批拒绝原因，本任务未尝试清理提权或绕过。

## 5. 验证台账

精确命令、退出码、耗时和证据文件记录在 `remediation/evidence/R13/commands.json`。后端全量最终状态由 `backend-result.json` 与 `backend.xml` 记录。全量用 `-m 'not live'` 选择全部既有离线后端用例，包括容量与 traced-memory 门禁，最终2591通过、1跳过、4排除、1项既有 Starlette 弃用警告，测试耗时2328.09s（命令总耗时2330.0623207s）。唯一跳过项要求 POSIX 文件所有权语义，当前主机为 Windows；四项排除均为标记的真实供应商用例。没有降低阈值、删除断言、改变默认行为或增加 skip。

前端基线门禁：45文件/642测试通过，类型检查和构建通过。既有26项完整浏览器门禁为19通过/7失败，其中逐字原文 SQLite 流程通过。新增 AI 故障浏览器流程在真实普通激活后覆盖六种故障并通过。新增修订流程按 N02 失败。R13 数值/生命周期测试与三项未满足的投递回归与原全量集合分开报告；这些文件是在原全量收集后新增的。

| 最终验证范围 | 结果 | 命令耗时（秒） |
| --- | --- | --- |
| 原有完整离线后端 | 2591通过 / 1平台跳过 / 4真实调用排除；退出码0 | 2330.0623207 |
| 原有前端单元测试 | 45文件 / 642通过；退出码0 | 6.6407936 |
| 前端类型检查 / 生产构建 | 均通过；退出码0 | 4.2594451 / 1.3590101 |
| 原有完整浏览器测试 | 19通过 / 7失败；退出码1 | 83.1434259 |
| 新增 R13 数值、未完成K线、生命周期和投递回归 | 37通过 / 3失败（N01）；退出码1 | 111.4283168 |
| 新增普通修订浏览器探针 | 1失败、四项断言（N02）；退出码1 | 10.3746759 |
| 新增 AI 故障浏览器探针 | 1通过、六种故障；退出码0 | 7.0887846 |
| 新增提醒自动刷新/重连浏览器探针 | 1通过；退出码0 | 37.7905102 |
| 独立重复三项原有浏览器失败 | 3失败（N03/N04）；退出码1 | 10.2742269 |
| 包含全部新增浏览器文件的最终类型检查 | 通过；退出码0 | 3.8381399 |
| 三个新增 Python 文件的 Ruff 检查 | 通过；退出码0 | 未独立记录 |

最终类型检查起初发现新增提醒刷新探针有一个未使用的局部变量；删除该无用读取未改变行为，上表所列重跑通过。最终保护核验确认原有16个文件哈希全部一致。原有浏览器与新增验收失败均保持可见，本报告不声称仓库全绿。

复现夹具开发中的失败不是产品问题：最初修订测试精确标签定位/超时，已按实际 select 控件修正；一项新增等待误以为政策字段在审核前就会消失；AI 故障测试起初用了错误响应属性，后改用已定义的 `draftPlanJson`；最初 S03 附带重建恢复时使用可变历史行情假数据，恢复正确拒绝。现将 S03 与重启分开，按其本身判据重跑；既有重建服务去重测试仍保留重启要求。不受支持的截图 CLI 参数改为独立诊断 Playwright 配置。这些尝试未改变业务或降低验收阈值。保留可用日志，以最终可复现探针及结果形成结论。

OpenAPI 期待仍为50 paths=35 live+15 backtest，SHA-256 `1aed810d751d7c1dee623b1eb6afb7f2538928c8ea091bdf79027dd34e58951a`。未改写期待快照或规格值。Schema1/2 和历史提取 prompts v1–v4 未改变。20项 semantic-v2 语料是分案例模拟供应商证据，不是真实 AI 正确率；不恢复已撤销的关键词20/20说法。

编写的文档与测试源码空白检查通过。包含全部证据的差异检查会报告测试运行器在原始日志、JUnit 失败内容和错误上下文快照中输出的空白；这些原始证据保持不变。`format-check.json` 同时记录两个范围及原始证据检查的非零结果。

## 6. 现实链路边界与交接

NOT_RUN：真实/收费 AI 对明确、歧义、不支持原文的转换；本版本真实行情 SDK 认证/权限/额度/时间标签验证；实际交易时段的新鲜已完成K线监控；自然出现的买入/卖出/风险分支；真实断线恢复及上述条件下用户可见收取。未调用外部通知通道或交易。历史供应商证据不是本次 R13 新证据。

修复 N01/N02 及必需门禁失败后，重跑其独立回归与适用离线门禁。未来 R14 提案必须明确供应商/模型、含重试的物理请求数、费用/额度上限、股票/端点、持续时间/盘中窗口、临时库、已审核测试计划及允许通知通道。未观察分支保留 NOT_RUN。后续仅由协调任务安排；本任务不创建后继任务，在全部写入、提交和读回完成后发送一次已授权交接。
