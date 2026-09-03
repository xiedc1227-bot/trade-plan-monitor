# 交易计划监控系统（Trade Plan Monitor）

Trade Plan Monitor 是一款本地优先、AI 辅助、面向确定性 A 股交易计划的监控工具。它把经审核的计划和规范化行情转化为可解释提醒，不会自动下单。

[English](README.md)

## 产品状态

`T001`～`T059` 与 `BT001`～`BT050` 已实现并验收。安装式命令可在精确回环地址提供构建后的 Vue SPA、REST API 和 WebSocket 路由。WEBF05 现在使用惰性的真实监控组合：打开并迁移共用 monitor SQLite，暴露后端 `RuntimeHealthSnapshot`，并管理已提交事件流。由于实时分钟 `SourceTimeLabel` 语义和实时板块指数供应商仍未验证，启动会在任何密钥或供应商请求前诚实报告只读 `DEGRADED` 和 `nextPollAt=null`，且不创建调度运行任务。没有权威持久投影的总览、股票和实时板块指数读取继续返回 `SERVICE_UNAVAILABLE`；不再使用通用生命周期占位组合，也不伪造空判断状态。`/plans` 流程已经可用：启动时只加载一次项目 AI 配置，并在 `data/monitor.sqlite3` 上注入一个以后端为权威来源的持久计划服务。计划保存、查询、JSON/YAML 导入、启用和停用因此可跨 Web 进程重启保留；只有用户提交计划原文后才执行提取。成功的 AI 结果只有经用户明确进入审核才会进入共用结构化编辑器；保存只创建未启用草稿，启用仍需用户单独确认并由后端允许。

WEBF06 将 `/` 接到既有以后端为权威来源的总览快照：它展示股票判断和共用板块指数事实，并与计划专属指数进度分开；在快照存在前保持诚实的加载状态。它不增加浏览器交易规则或供应商请求。

WEBF09 把个股详情持仓面板接到既有持仓 REST 契约，以及共用 monitor 数据库上的持久服务。只有后端执行已启用计划最大持仓、已存日历 T+1、剩余数量、整手和 revision 规则；浏览器只做输入形状检查和显式确认，绝不预测持仓命令是否符合资格。

WEBF10 把 `/alerts` 接到既有提醒 REST 契约和共用持久出站箱。筛选、规范证据和确认 revision 均由后端权威判断；确认操作幂等且受审计，但绝不记录成交或变更持仓。

确定性测试套件不调用真实 Tushare、AI、Webhook 或其他外部服务。真实供应商检查仍是需要单独授权的操作。

本地回测实现提供隔离的 `sync`、`verify`、`run`、`list` 和 `prune` 命令，其 BT050 production-fake 验收已完成。另行授权的 T059 性能修复现已在不改变阈值的前提下通过 100k-export、ten-symbol/252-day、内存、存储及完整离线闸门。T059 已于 2026-09-01 完成最终验收，C24 已完成 4/4 项；可选 AI live 探测继续为 `NOT_RUN_UNAUTHORIZED`。详见[双语 T059 证据](docs/verification/release-acceptance.zh-CN.md)。历史同步可用和已验收的 T058 visible-block 结果都不代表当前真实 Tushare readiness。

已批准的板块指数扩展现已在监控与回测中实现。`board-index-map-v1` 根据每个已校验的 A 股代码推导固定板块参考；相同指数和截止时间共用不可变数据快照，每个 Schema v2 计划只独立计算自身指数条件。界面把共用指数事实与计划条件结果分区展示，历史 Schema v1 计划和结果保持不变。

## 安全边界

- 实时系统是监控和提醒软件，不是券商、订单路由或投资顾问。每条可操作提醒都包含“仅提醒，不会自动下单”；只有隔离的离线 `BACKTEST` 模式可以生成明确标注的模拟研究成交。
- 计划必须类型化、经审核、版本化，并在激活后保持不可变。AI 输出在确定性校验和用户审核通过前始终是不可信草稿；提取和草稿保存都不会自动启用它。
- 价格按整数“分”保存，数量按整数“股”保存，A 股时间戳必须是带 `Asia/Shanghai` 时区的值。
- 行情缺失、过期、无权限或来源语义未验证时安全阻断。
- 板块指数数据不会生成统一大盘强弱观点或隐藏交易规则。没有指数条件的计划在参考指数数据缺失时保持原有判断。
- AI 密钥保留在被 Git 忽略的项目密钥文件中，YAML 只选择文件和键名；密钥不能进入受版本控制的 YAML、数据库列、API 响应、日志或导出内容。
- Web 监听只接受字面量 `127.0.0.1`；系统未实现登录鉴权。

## 快速开始

以下 PowerShell 流程从全新的源码检出启动已打包本地界面。依赖安装首次需要访问包注册表；验证和启动步骤不会调用真实 Tushare、AI 或 Webhook。

### 1. 环境要求

- CPython 3.14.x（`>=3.14,<3.15`）；当前开发验证版本为 Python 3.14.7。
- Node.js `^20.19.0`、`^22.13.0` 或 `>=24.0.0`，以及 npm 11.8.0。
- Windows PowerShell，当前目录为 `trade-plan-monitor/`。

### 2. 从全新检出安装

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Push-Location web
npm install --include=optional --no-package-lock
npm run build
Pop-Location
```

`npm run build` 保留常规 `web/dist/index.html` 输出，并将同一份完整构建复制到被忽略的 Python 包暂存目录。缺少这些资源时，安装式 Web 命令不会回退到当前工作目录或前端源码树。

### 3. 配置本地引用

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

YAML 保存非密钥供应商设置、Tushare 环境变量名称，以及 AI 项目密钥文件和键名。纳入版本控制的示例选择已验证的 Tushare 兼容端点 `https://api.quicksync.cn`，并选择 DeepSeek 的 OpenAI 格式端点 `https://api.deepseek.com` 和模型 `deepseek-v4-flash`。AI profile、显示名称、Base URL、模型、超时、重试次数、输入上限、输出上限、温度、密钥文件路径和键名都可以修改。本地副本 `config/app.yaml` 会被 Git 忽略。Tushare 仍只在使用时设置进程变量：

```powershell
$env:TUSHARE_TOKEN = "replace-with-your-tushare-token"
```

[.env.example](.env.example) 是纳入版本控制的项目密钥模板。使用示例 `api_key_ref` 时，把它复制为项目根目录中被忽略的 `.env`，再只替换所选键的占位值。当前工作区的本地配置使用本项目根目录中被忽略的 `.env`；其中的 `DEEPSEEK_API_KEY` 已从 `TradingAgents/.env` 复制，过程中不会打印密钥值。绝不能把 Token 或 API Key 直接写进 `config/app.yaml`，也不要提交 `config/app.yaml`、`.env`、数据库、备份、密钥或构建输出。

Web 启动时会校验严格 YAML，相对于该 YAML 解析 AI 项目密钥文件，并为本次服务生命周期创建一份不可变 AI 客户端绑定。AI 密钥绝不从进程环境读取。通用监控的 `DEGRADED` 状态与此独立，也不能证明 Tushare 已就绪。

### 4. 启动已打包本地 Web 界面

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

在同一台计算机上打开 `http://127.0.0.1:8765/`。使用 `Ctrl+C` 停止前台进程。当实时分钟 `SourceTimeLabel` 语义或实时板块指数供应商仍未验证时，监控标题会诚实显示 `DEGRADED`、只读状态和没有下次轮询；打开 `/plans` 可使用 AI 草稿与持久计划管理。首次 lifespan 启动会创建或升级 `data/monitor.sqlite3`；之后启动时，计划保存、查询、导入、启用和停用都使用同一 SQLite 文件。数据库及其 WAL/SHM 伴随文件必须保持私密，且不得直接复制正在使用的 WAL 数据库作为备份。修改 `config/app.yaml` 或选中的项目 `.env` 后，必须重启 Web 才能更改 AI 设置。

### 5. 离线验证

```powershell
python -m trade_plan_monitor --help
python -m pytest tests/unit/test_package.py tests/integration/test_packaging.py -q
Push-Location web
npm test -- --run
npm run type-check
npm run build
Pop-Location
```

这些检查会验证安装入口、包内资源、前端测试、类型和生产构建，不会连接真实供应商。

### 浏览器、NVDA 与性能闸门

真实浏览器闸门使用确定性假 REST 契约，运行时不得提供供应商令牌。它在 Chromium 中覆盖
`/backtests`、`/backtests/new`、`/backtests/data` 与
`/backtests/:runId`，且不联系 Tushare、AI、Webhook 或任何其他外部服务。结果链路覆盖后端解析的参考市场覆盖、冻结指数资源、准确计划路径，以及跳转到持久化逐决策证据：

```powershell
Push-Location web
npm run build
npm run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/accessibility.spec.ts
Pop-Location
```

浏览器闸门必须在 320、768、1024 和 1440 CSS 像素下，以纯键盘导航、200% 文本和减少
动态效果运行。只有同时满足以下条件才算通过：无控制台或 API 失败、无 serious 或 critical
级 axe 违规、每个资源最多一个在途请求、每个活动任务只有一个且间隔至少两秒的轮询计时器、
任务终态或视图隐藏/卸载后不再轮询、每个结果表格页最多 100 行、权益点最多 2,000 个，并且
选择权益页签前 ECharts 字节数为零。已批准的验收配置仅包含 Chromium，不声称提供
Gecko/Firefox 兼容性证据。

在 Windows 上，对相同四条路由完成一次 NVDA 纯键盘检查。确认页面标题与标题层级、地标与
导航名称、字段标签与获得焦点的错误摘要链接、有标签的表格滚动、模态框焦点约束与恢复、页签
和分页状态、导出控件，以及作为图表精确替代的权益表格。轮询状态发生变化时只能播报一次，
不得抢夺焦点或重复播报未变化状态。把日期、浏览器/NVDA 版本、路由/清单结果及审核人记录在
Git 外；截图、追踪、下载、性能 profile 及其他原始证据也必须留在仓库外。

性能必须从生产构建开始测量：仅在精确回环地址提供服务，使用干净 Chromium profile、
1440×900 视口、4× CPU 降速和 20 ms 回环延迟。四条路由各执行 5 次预热导航和 20 次测量
导航。固定 p75 上限为 LCP ≤ 2.5 秒、INP ≤ 200 毫秒、CLS ≤ 0.10；交互延迟还必须满足
p95 ≤ 200 毫秒。排除 ECharts 的入口/共享包必须 ≤ 150 KiB gzip，每条非图表路由必须
≤ 100 KiB gzip，异步 ECharts 分块必须 ≤ 450 KiB gzip。性能 profile 与测量输出必须存放
在 Git 外；测量环境不可用或不稳定时应阻断闸门，不能降低阈值。

生产回测流程仍为 `sync` → `verify` → 离线 `run`。`sync` 是唯一可联网的回测命令，并且
仍需另行人工授权和字面量 `--allow-network` 标志。假浏览器闸门通过绝不授权真实同步，也不
证明 Tushare 的可用性或语义。

## 命令

除非命令本身切换目录，后端命令从 `trade-plan-monitor/` 运行，前端命令从 `web/` 运行。

| 命令 | 用途 | 当前可用性 |
|---|---|---|
| `trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765` | 提供已打包 SPA、API、WebSocket、配置文件驱动的 AI 草稿和持久计划管理 | 可用；WEBF05 惰性组合监控，并在实时前置条件验证前诚实报告只读 `DEGRADED`；缺失权威投影时保持不可用 |
| `python -m trade_plan_monitor --help` | 显示稳定的安装式命令面 | 可用 |
| `python -m pytest -q` | 运行完整后端测试 | 可用；离线 |
| `python -m ruff check --no-cache src tests` | 运行后端代码检查 | 可用；离线 |
| `python -m compileall -q src/trade_plan_monitor` | 编译检查后端模块 | 可用；离线 |
| `python scripts/generate_frontend_types.py --check` | 检测 OpenAPI/生成 TypeScript 漂移 | 可用；离线 |
| `npm test -- --run` | 运行前端单元测试 | 在 `web/` 中可用；离线 |
| `npm run type-check` | 检查 Vue 和 TypeScript | 在 `web/` 中可用；离线 |
| `npm run build` | 构建并暂存生产 SPA 资源 | 在 `web/` 中可用；安装依赖后离线 |
| `python -m trade_plan_monitor validate` | 分派配置/计划校验 | 注入式边界；独立控制台要求显式服务工厂 |
| `python -m trade_plan_monitor monitor --once` | 分派一次无界面监控周期 | 注入式边界；独立控制台要求显式服务工厂 |
| `python -m trade_plan_monitor replay` | 分派确定性回放 | 注入式边界；独立控制台要求显式服务工厂 |
| `python -m trade_plan_monitor backup` | 分派已验证在线备份 | 注入式边界；独立控制台要求显式服务工厂 |

当前独立控制台调用注入式边界命令时会抛出 `runtime service factory is not configured`。这是明确的组合未完成信号，不是成功的空操作。

## 架构

```text
经审核文本 ─→ AI 草稿 ─→ 类型化计划校验 ─→ 不可变活动计划
                                │                    │
Tushare ─→ 规范化完整 K 线 ─────┴──→ 确定性决策引擎
                                            │
                                            ▼
                                      事务 Outbox
                                            │
                                            ▼
                                        监控运行时
                                            │
                                            ▼
                       FastAPI REST/WebSocket + 已打包 Vue SPA
                                            │
                                            ▼
                                 仅 127.0.0.1:8765
```

目标运行时由一个 Python 进程统一管理 FastAPI 生命周期、监控运行时、确定性决策引擎、SQLite WAL 状态和本地 Vue SPA。同步 Tushare 工作和异步 AI 工作使用彼此独立的有界执行路径，避免 AI 延迟行情监控。仓储层绝不执行网络 I/O。

## Tushare 能力

适配器提供一项独立能力探测和五项规范化操作：

| 规范化操作 | Tushare 接口 | 用途 |
|---|---|---|
| `realtime_minutes` | `rt_min` | 请求股票的实时分钟行 |
| `current_day_minutes` | `rt_min_daily` | 当前交易日的一分钟行 |
| `trading_calendar` | `trade_cal` | 交易日/交易时段判断 |
| `daily_limits` | `stk_limit` | 官方每日涨跌停价格 |
| `daily_bars` | `daily` | 官方不复权日 K 线 |

非密钥示例配置选择 `https://api.quicksync.cn`。`create_tushare_client` 工厂仅在运行时解析 `TUSHARE_TOKEN`，并把端点设置到单个官方 `tushare==1.4.29` `DataApi` 实例，不修改 SDK 的进程级全局端点。系统拒绝明文 HTTP、内嵌账号密码、查询字符串和片段。

2026-08-25 经明确授权的检查已通过 HTTPS 和官方 SDK 验证 `stk_mins`：`600000.SH` 在 2026-08-24 的一个完整交易日返回 241 条一分钟记录，覆盖 09:30:00 至 15:00:00，包含预期的 8 个字段，且不存在重复行、必要字段空值、非法 OHLC、负成交量或错误股票代码行。该观察本身不能证明上游标签语义，因此适配器仍默认使用 `UNVERIFIED`；经审核的回测组合必须显式选择下文所述项目策略 `TUSHARE_STK_MINS_241_END_V1`。该观察和历史策略都不能替代另行要求的实时 `rt_min` 和 `rt_min_daily` 能力。

只在另行授权的真实能力探测中设置 `TUSHARE_TOKEN`。能力、账号权限、限流和分钟标签语义均独立发现；配置不代表能力可用。必要能力被拒绝或未验证时会阻断可操作输出。默认契约测试使用确定性假 DataFrame：

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## 历史回测

已批准的回测设计采用混合流程：经明确授权的 `backtest sync` 把 `stk_mins`、`trade_cal`、`stk_limit` 和不复权 `daily` 事实增量下载到 `backtest-market.sqlite3`；本地校验冻结精确 `dataset_hash`；每次正式运行随后完全离线读取该冻结数据集，并且只把结果资产写入 `backtest-results.sqlite3`。

`/backtests/new` 页面会列出后端当前标记为 `canActivate=true` 的真实不可变计划版本，包括合格但未启用的草稿。用户选择一个准确版本；提交时后端会重新校验，并在返回已接受回执前持久化其规范计划快照。之后保存更新版本不能改变已排队任务、旧结果或其既有哈希。

行情库和结果库路径必须解析为不同文件。创建数据表前，每个存储都会拒绝既有实时监控数据库或另一个回测存储域，防止错误路径配置修改无关状态。

历史行按内容去重并由多次运行复用。供应商修订生成不可变修订和新数据集哈希，不能改变旧结果。历史适配器默认使用 `UNVERIFIED`；CLI 组合显式选择版本化配置 `TUSHARE_STK_MINS_241_END_V1`，把 09:30 来源行保留为不参与策略的 `opening_special`，并把其余结束标签行映射为恰好 240 个规范交易分钟。该证据绝不能完成实时任务 `T058`。

一个数据集接受 1–10 只不重复股票、最多 5 个日历年的回测日期和最多 2 个日历年的预热。历史日历同步必须对每个所需 `SSE`/`SZSE` 交易所分别显式调用一次 `trade_cal`。Tushare 官方日历契约未列出 BSE，因此 `.BJ` 历史范围当前会在联网前以 `UNSUPPORTED_HISTORICAL_CALENDAR:BSE` 被拒绝；实时 `.BJ` 计划支持不受影响。真实历史适配器会拒绝无法解析/重复原始行，以及错误日历交易所/范围、日线股票/范围或涨跌停日期。由于 `stk_limit(trade_date)` 是市场全量响应，该日期的其他有效股票仍合法；同步层选择请求股票后，要求每个规范参考集合即使在 `--refresh` 时也必须精确匹配，否则会在持久化前以 `INVALID_RESPONSE:<surface>` 失败。每次读取冻结 artifact 都会重新计算内容哈希，因此本地 payload 被修改后不能继续冒用旧 `artifact_hash` 回放。

冻结校验还会报告稳定阻断原因 `INVALID_<KIND>:<identity>:<date>`、`INVALID_CALENDAR_CHAIN:<exchange>:<date>` 和 `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>`，绝不会猜测或修复损坏事实。它在一个 WAL 读取快照下逐日校验分钟批次，然后仅用短 `BEGIN IMMEDIATE` 重新检查每个已选 head 并发布；并发修订会中止冻结。通过校验的 manifest 使用 O(1) 缓存 `natural_key` 索引执行后续成员查询，之后仍正常重算 artifact 哈希。

所有回测哈希共享精确 Decimal 规范化：`0.0003` 与 `0.00030` 这类数值相等的 scale 变体具有相同规范文本和 identity，二进制浮点及定点展开超过 10,000 个字符的值则失败关闭。CLI 元转分同样不依赖全局 context：最多接受两位小数及其后的尾零，超大指数会在展开前失败，结果不能超过 signed 64-bit 分上限 `9,223,372,036,854,775,807`。回测复用经审核的计划哈希、规范 K 线、指标、收盘核对和纯决策引擎。`execution-model-v1` 仅用于回测：`signalAt` 等于产生该信号的判断 `snapshot.evaluatedAt` 以及来源事实的 `receivedAt`；只有后续满足 `openAt >= signalAt` 的候选 K 线才能成交。离散回放可以先完成产生事件，再处理同一边界的下一分钟 K 线，因此允许相等并不意味着能在产生信号的 K 线/桶内成交；生产历史分钟事实通常使用 `receivedAt == barEnd + 12s`，所以常规路径仍在之后的分钟成交，不会前视。成交把 `filledAt` 记录为执行分钟的 `openAt`。零成交量分钟会让订单沿连续规范候选继续等待之后第一根正成交量分钟；只有回放结束仍未出现时才变为 `SUSPENDED`。若缺少必需交易时段分钟，之后 K 线暴露缺口时会以 `MISSING_NEXT_MINUTE` 失败。每个 `ExecutionOutcome` 都包含不可变 `resolvedAt`，存在解决 K 线时还包含其 `sourceBarId`；只有 `NO_NEXT_MINUTE` 在结束时解决且没有来源 K 线。费用、滑点和部分持仓成本分摊使用带显式分取整的精确整数有理数算法，不依赖进程全局 Decimal context。系统确定性应用实际每日涨跌停、T+1、100 股整手、现金/仓位限制、费用和滑点。它绝不调用实时调度器、通知 Outbox、Webhook、WebSocket 或券商。

每次判断最多使用 512 根完整五分钟 K 线、当前日前 499 根官方日线和 512 个日历日事实。这些边界进入 `run_id`，并以 `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR` 展示；它们属于公开研究限制，本身不能证明多年资源验收。该独立闸门已由 BT050/BT008 证据完成。

报告还会公开以下限制：零成交量分钟作为不可交易代理（`ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`）、成交数量不受分钟成交量上限约束（`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`）、涨跌停锁定保守使用开盘价或滑点后价格（`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`）、回撤按每日权益采样（`DAILY_EQUITY_DRAWDOWN_SAMPLING`）、胜率按卖出成交而非往返交易统计（`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`），以及指标除法固定使用 Decimal precision 28 和 `ROUND_HALF_EVEN`（`METRIC_DECIMAL_PRECISION_28_HALF_EVEN`）。

下面的完整示例使用默认隔离路径 `data/backtest-market.sqlite3`、`data/backtest-results.sqlite3` 和 `backtest-reports/`。`sync` 是唯一允许联网的命令；缺少 `--allow-network` 时会拒绝运行。默认预热边界是 `--start` 之前 400 个日历日；如需覆盖，必须对 `sync` 和 `verify` 传入相同的 `--warmup-start`。

以下费用/滑点数值只是显式示例假设，不是产品默认值，使用时应按研究口径填写。`--no-event-risk` 会记录一项明确假设；存在重大事件风险阻断时，应改用与其互斥的 `--manual-event-risk`。

```powershell
# 1. 经明确授权，增量同步缺失历史事实。
$env:TUSHARE_TOKEN = "<set-in-this-shell-only>"
python -m trade_plan_monitor backtest sync `
  --symbols 003043.SZ `
  --start 2025-01-02 `
  --end 2025-12-31 `
  --allow-network
Remove-Item Env:TUSHARE_TOKEN

# 2. 在本地冻结相同范围，并从 JSON 结果复制 dataset_hash。
python -m trade_plan_monitor backtest verify `
  --symbols 003043.SZ `
  --start 2025-01-02 `
  --end 2025-12-31

# 3. 完全离线运行，并显式填写全部成交与事件风险假设。
python -m trade_plan_monitor backtest run `
  --dataset <dataset_hash_from_verify> `
  --plan config/plans/003043.SZ.sample.yaml `
  --initial-cash-yuan 100000 `
  --commission-rate 0.0003 `
  --minimum-commission-yuan 5 `
  --stamp-duty-rate 0.0005 `
  --transfer-fee-rate 0.00001 `
  --buy-slippage-bps 2 `
  --sell-slippage-bps 2 `
  --no-event-risk

# 4. 查看摘要，并且最多清理一个有界批次的过期详情。
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

运行摘要、假设、最终指标和成交账本长期保留。成功运行的判断/信号/每日权益详情只保留最新 100 次且最多 90 天；失败、取消及按需调试详情保留 14 天；置顶运行豁免。结果发布先把规范行 staged 到 `backtest-results.sqlite3`；普通读取和统计看不到任何 staged 行。只有完整 `reportHash`、预期成交/详情数量和规范 identity/内容集合哈希都匹配时，一个事务才会设置内部 `materialized` 可见性标记。首次发布会持久化这些数量和集合哈希，已发布运行的每次重试都必须精确匹配；普通摘要/成交/详情读取还会在应用任何 detail-kind 过滤前，根据已哈希 payload 校验每个 SQL identity。随后 CLI 原子写入 `backtest-report-summary-v1` JSON 和成交 CSV。`materialized` 是唯一发布闸门，但不是公开运行状态；公开状态仍为 `COMPLETED`、`FAILED` 或 `CANCELLED`。有界 `prune` 维护会在 14 天后移除未置顶的废弃 staged 摘要/成交/详情，近期 stage 仍可恢复。文件缺失或损坏时，可以根据长期摘要/成交行重建，不联网、不重放、也不重复成交；已清理的判断/信号/结果/权益详情按设计不可重建。`reportHash` 继续作为原始完整运行的审计 identity，并不是文件字节哈希。底层回测契约支持置顶元数据和初始持仓批次，但当前 CLI 尚未暴露置顶/取消置顶或初始持仓输入，因此每次 CLI 运行都只从现金开始。不保存完整逐分钟账户快照，也不重复保存行情行。隔离、禁止未来数据、报告及保留契约详见 [SPEC-backtest.zh-CN.md](docs/specifications/backtesting/SPEC-backtest.zh-CN.md)。

## AI 配置与密钥

仅在启用 AI 辅助草稿时才需要 `DEEPSEEK_API_KEY`。YAML 只保存 `api_key_ref.file` 和 `api_key_ref.key`，真实值保留在被 Git 忽略的项目密钥文件中；相对路径以 `app.yaml` 所在目录为基准。默认 `DEEPSEEK` profile 按 DeepSeek 当前接口发送 `max_tokens`、`thinking={"type":"disabled"}` 和 JSON 输出字段。若要使用其他兼容服务，可把 `profile` 改为 `OPENAI_COMPATIBLE`，并配置经过审核的 Base URL、模型、文件和键名。运行时供应商配置保存非密钥引用、模型、有界超时/重试/Token 限制和 HTTPS 基础 URL（仅显式回环主机允许明文 HTTP）。

API Key 只由后端加载，公共契约无法返回。Web 页面只显示供应商名称、模型、安全 Base URL、限制、启用状态和密钥是否已加载；没有供应商修改、Token 输入、密钥替换或连接测试控件。系统拒绝重定向、URL 内嵌账号密码、带查询参数的基础 URL、执行原始模型内容以及包含密钥的校验错误。AI 输出绝不会直接激活。

Web 是主要 AI 使用方式：打开 `/plans`，粘贴原文，提交后审核经过校验的结果。后端最多同时执行一个提取，页面只轮询精确任务 ID。修改 `config/app.yaml` 或 `.env` 后必须重启 Web。CLI 保留为维护工具；下面两个命令都会向真实服务发送请求，并可能产生 Token 费用：

```powershell
# 使用 config/app.yaml 发送一次最小连通性请求。
python -m trade_plan_monitor ai test

# 读取一个 UTF-8 文本文件，返回仅供审核的结构化草稿。
python -m trade_plan_monitor ai extract --source .\plan-source.txt
```

如需选择其他配置文件，在 `test` 或 `extract` 后增加 `--config <路径>`。命令会拒绝不存在的来源文件、目录、非法 UTF-8、超过配置字符上限的文本，以及缺失、超大、格式非法、键重复或值为空的项目密钥文件，不会把不合格结果当成有效草稿。密钥文件最大 65,536 字节，必须是严格 UTF-8，并且不会通过进程环境读取。Web 与 CLI 使用同一套文件配置和密钥读取器；两者都不提供 Web 设置编辑器，也都不使用 AI 环境变量后备。

T059 增加了可选、fail-closed 的连通性探测。它不属于普通测试，未单独批准真实供应商联网操作时不得运行。先审核一个规范 lowercase HTTPS base URL 和精确 model，再把授权绑定到操作、规范化目标和 model。digest context 是 `trade-plan-monitor:t059:ai-live:test-connection:v1`，并包含下方所示的 3 个换行分隔符，包括最后一个换行：

```powershell
$env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL = "https://api.deepseek.com"
$env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL = "deepseek-v4-flash"
$target = "trade-plan-monitor:t059:ai-live:test-connection:v1`n$($env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL.TrimEnd('/'))`n$($env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL)`n"
$targetBytes = [Text.Encoding]::UTF8.GetBytes($target)
$env:TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($targetBytes)).ToLowerInvariant()
python -m pytest tests/contract/test_ai_live.py -q -m live
Remove-Item Env:TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256, Env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL, Env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL
```

精确 selector 是 `python -m pytest tests/contract/test_ai_live.py -q -m live`。它使用默认 TLS 校验、忽略 proxy 环境变量、禁止 redirect 和 retry，并且只输出稳定 error code。通过只能证明有界 Chat Completions envelope 连通性；不能证明 model identity、计划质量、激活安全或交易正确性。

## 备份与恢复

### 创建与验证

备份服务在 WAL 仍可能写入时使用 SQLite 在线备份 API。它先写临时候选文件，运行 `PRAGMA integrity_check`，只原子发布验证通过的 `monitor-backup-*.sqlite3`，然后应用保留策略。绝不能直接复制正在使用的 `.sqlite3`、`-wal` 或 `-shm` 文件作为备份。

当前独立 `backup` 命令尚未完成组合，因此不要假定它已经创建文件。当运行时集成提供数据库和备份目录路径后，每次恢复前都要验证结果。以下只读命令是支持的验证边界；请把占位符替换为一个候选文件路径：

```powershell
$env:TPM_BACKUP_PATH = "backups\<verified-backup>.sqlite3"
python -c "import os; from trade_plan_monitor.state.backup import verify_sqlite_backup; result = verify_sqlite_backup(os.environ['TPM_BACKUP_PATH']); print(result.integrity_check, result.schema_object_count)"
```

只有第一个值严格等于 `ok` 时才能继续。

### 恢复

1. 停止前台 Web/监控进程；绝不能恢复到已打开的数据库。
2. 将目标数据库和备份解析为精确本地路径，不要使用 glob。
3. 按上文运行 `verify_sqlite_backup`。
4. 把现有数据库**及其同名 `-wal`/`-shm` 旁文件**一起移动到带日期的恢复位置，不能删除它们，也不能把它们留在恢复目标旁。
5. 把单个已验证备份复制到现在为空的配置数据库路径，启动应用并确认健康后，再移除恢复副本。

应用配置模式尚未公开数据库或备份路径；它们属于运行时组合输入。未知 YAML 字段会被拒绝，因此不要在 `config/app.yaml` 中自行添加 `database` 或 `backup` 节。

## 保留策略

- 已验证在线备份保留最新 **30 个成功备份**。清理只考虑配置备份目录内自有的 `monitor-backup-*.sqlite3` 文件，会再次验证每个候选，并忽略无关、无效或符号链接文件。
- 提醒回放和持久监控事件回放默认使用 **7 天**回放窗口。游标早于已保留历史时会显式失败，不会静默跳过事件。
- 计划、审计、持仓、行情 K 线或主 SQLite 数据库没有通用自动删除策略。只能通过未来获批的操作管理这些数据，不能使用文件系统通配符。

## Webhook 默认值

通用 Webhook 渠道默认配置如下：

| 设置 | 默认值 |
|---|---|
| `enabled` | `false` |
| `endpoint` | `null` |
| `allowlisted_hosts` | 空 |
| `timeout_seconds` | `5` |
| `allow_redirects` | `false` 且不能启用 |

`config/app.example.yaml` 有意不包含 `webhook` 节；严格应用模式会拒绝该字段。启用 Webhook 投递需要显式运行时组合，并配置一个主机被精确列入白名单的 HTTPS 端点。系统拒绝通配符、内嵌账号密码、查询字符串、片段、重定向和响应体持久化。除非已有获批的接收端和密钥处理流程，否则保持关闭。

## 故障排除

| 现象 | 含义与处理 |
|---|---|
| `WEB_ASSETS_UNAVAILABLE` | 安装分发缺少完整 Vite 构建。构建/重装 Python 包前运行 `npm install --include=optional --no-package-lock` 和 `npm run build`；不要增加 cwd fallback。 |
| Rolldown 报告 `Cannot find native binding` | npm 遗漏了 Vite 的平台专用可选包。运行 `npm install --include=optional --no-package-lock`，再重试 `npm run build`。 |
| 界面显示 `DEGRADED` 或通用监控 API 返回 `SERVICE_UNAVAILABLE` | 当实时分钟 `SourceTimeLabel` 语义或实时板块指数供应商未验证，或缺少权威投影时，这是预期行为。后端会保持只读健康状态，不调度可操作监控；独立的计划与持久持仓流程在已存计划/日历前置条件存在时仍可使用。 |
| `runtime service factory is not configured` | 在应用服务组合接通前调用了 `validate`、`monitor`、`replay` 或 `backup`。 |
| 监听主机校验失败 | 使用精确字面量 `127.0.0.1`；系统有意拒绝 `localhost`、`::1`、`0.0.0.0`、主机名和局域网地址。 |
| 8765 端口占用 | 停止另一个本地进程，或选择 1～65535 中未占用的其他端口，同时保持主机为 `127.0.0.1`。 |
| YAML 报告未知字段 | 重新从 `config/app.example.yaml` 开始；模式会有意拒绝不支持的节和明文密钥。 |
| Tushare 能力为 `DENIED`/`UNVERIFIED` | 检查进程环境和账号权限，然后只运行获批的真实探测；绝不能绕过阻断。 |
| AI 返回配置/鉴权错误 | 检查 `api_key_ref.file`、`api_key_ref.key`、profile、Base URL 和模型；真实密钥只放在被忽略的项目密钥文件中，不要放进 URL 或 YAML。 |
| 前端生成类型漂移 | 运行 `python scripts/generate_frontend_types.py --check`；只在获批 API 契约变更中重新生成。 |

## 禁止端口转发

应用只能在运行进程的同一台桌面计算机上使用。**不要**绑定 `0.0.0.0`、局域网地址、`localhost` 或 `::1`；不要使用 SSH/IDE 端口转发、反向代理、隧道、容器端口发布、主机别名或路由器暴露。精确 Origin 防护和回环监听是安全边界，不是部署上的不便。

由于系统没有登录或远程用户授权，转发 `127.0.0.1:8765` 会在支持的威胁模型之外暴露敏感计划、持仓、健康数据和变更端点。远程访问需要另行设计并审查鉴权和部署模型。

## 项目结构

```text
trade-plan-monitor/
├── config/                   # 非密钥应用引用和样例计划
├── docs/                     # 架构、规格、决策、指南和验证证据
├── src/trade_plan_monitor/
│   ├── ai/                   # AI 配置、密钥、适配器和提取
│   ├── decision/             # 确定性条件、风险、优先级和哈希
│   ├── domain/               # 类型化计划、校验、编解码和稳定哈希
│   ├── market_data/          # Tushare 规范化、时段、K 线和指标
│   ├── notifications/        # 提醒模型、Outbox、渠道和投递
│   ├── runtime/              # 监控、恢复、生命周期和健康
│   ├── state/                # SQLite WAL、迁移、仓储和备份
│   └── web/                  # FastAPI 路由、安全和打包 SPA 资源
├── tests/                    # 单元、集成、回放和夹具
├── web/                      # Vue 3 / TypeScript 源码与工具链
├── pyproject.toml
├── README.md
└── README.zh-CN.md
```

本项目保持独立，不能从工作区上游 `TradingAgents/` 检出导入，也不能修改它。

## 领域约定

- 股票代码采用标准 Tushare 格式，例如 `003043.SZ`。
- 买入数量遵守 100 股整手规则；可卖批次按交易日遵守 A 股 T+1。
- 价格区间边界只有一个归属，精确边界值不能触发冲突动作。
- 15:00 盘中结果在与官方日 K 线核对前保持临时状态。
- 活动计划版本不可变；修改会创建新的审核版本。

仓库内的[华亚智能样例计划](config/plans/003043.SZ.sample.yaml)是黄金样例。

## 文档

无语言后缀的文档是供智能体和实施流程使用的英文权威输入；同名 `.zh-CN.md` 文件是中文审阅副本，必须在同一次变更中保持语义等价。完整分类清单见 [docs/README.zh-CN.md](docs/README.zh-CN.md)，其[英文索引](docs/README.md)位于同一目录。

| 契约 | 英文 | 中文 |
|---|---|---|
| 能力地图 | [CAPABILITY-MAP.md](docs/architecture/CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](docs/architecture/CAPABILITY-MAP.zh-CN.md) |
| 计划领域 | [SPEC-plan-domain.md](docs/specifications/monitoring/SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](docs/specifications/monitoring/SPEC-plan-domain.zh-CN.md) |
| AI 草稿 | [SPEC-ai-plan-drafting.md](docs/specifications/monitoring/SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](docs/specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md) |
| 行情数据 | [SPEC-market-data.md](docs/specifications/monitoring/SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](docs/specifications/monitoring/SPEC-market-data.zh-CN.md) |
| 历史回测 | [SPEC-backtest.md](docs/specifications/backtesting/SPEC-backtest.md) | [SPEC-backtest.zh-CN.md](docs/specifications/backtesting/SPEC-backtest.zh-CN.md) |
| 策略状态 | [SPEC-strategy-state.md](docs/specifications/monitoring/SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](docs/specifications/monitoring/SPEC-strategy-state.zh-CN.md) |
| 决策引擎 | [SPEC-decision-engine.md](docs/specifications/monitoring/SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](docs/specifications/monitoring/SPEC-decision-engine.zh-CN.md) |
| 通知 Outbox | [SPEC-notification-outbox.md](docs/specifications/monitoring/SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](docs/specifications/monitoring/SPEC-notification-outbox.zh-CN.md) |
| 监控运行时 | [SPEC-monitor-runtime.md](docs/specifications/monitoring/SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](docs/specifications/monitoring/SPEC-monitor-runtime.zh-CN.md) |
| 本地 Web | [SPEC-local-web.md](docs/specifications/monitoring/SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](docs/specifications/monitoring/SPEC-local-web.zh-CN.md) |

## 开发流程

1. 每次只实施一个获批的工作区任务。
2. 修改前阅读任务、模块契约和当前代码。
3. 行为或文档修改前先增加失败测试或契约检查。
4. 运行受影响测试、全量回归、Ruff、格式、编译、依赖、安全和双语一致性门禁。
5. 行为、命令、架构或公共契约变化时，同步更新英文和中文文档。

## 金融免责声明

本项目是个人监控与提醒工具，不构成投资建议、券商服务或订单执行系统。行情数据、AI 输出、技术指标和提醒都可能延迟、不完整或不正确。用户必须自行审核每份计划，并对所有交易决策承担全部责任。
