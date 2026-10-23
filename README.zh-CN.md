# 交易计划监控系统（Trade Plan Monitor）

当前本地验证：[单一计划流程验收](docs/verification/2026-10-03-unified-plan.zh-CN.md)。真实供应商就绪度与部署是单独验证工作。

> 当前计划流程：[单一交易计划流程](docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md)。在 /plans 粘贴原文、提取单一草稿、修改/审核、明确启用、按条件周期监测并明确模拟完整交易。不存在独立日线计划产品。基本面只在生成计划时审核；提醒和已读绝不改变持仓。已执行证据与范围限制见当前验证报告。

Trade Plan Monitor 是一款本地优先、AI 辅助、面向确定性 A 股交易计划的监控工具。它把经审核的计划和规范化行情转化为可解释提醒，不会自动下单。

[English](README.md)

## 交易计划

当前 Schema 5 计划也可通过既有隔离回测入口使用明确的冻结研究输入。无需真实激活，服务器审核仍是权威。空操作脚本只产生证据，不改变库存。参见[回放指南与合成分钟/日线示例](docs/operations/unified-replay.zh-CN.md)及[回放验证](docs/verification/2026-10-03-unified-replay.zh-CN.md)。

在本地 Web 界面打开 `/plans`，提取单一 `plan-extract-v9` 候选，修改原文定义的条件和参数，登记明确的人工补充，保存、审核并启用。缺失的策略定义保持可见并阻止启用。修改原文或参数后，必须重新审核并绑定准确的保存版本。没有计划类型选择器或独立日线计划工作台。

各条件声明所需证据周期。正式日线收盘确认的规则使用下一个交易所交易日，完整五分钟确认使用当前交易日；同一条件树可以组合两个周期，并使用同一个证据截止时间。可选价格区间、仓位分配元数据和技术风险分支依据原文，不强制补齐模板字段。先初始化独立 CORE/TACTICAL 模拟持仓，再明确确认当前提供的完整交易，数量固定为100股整数倍。服务端在同一事务中重新校验当前报价、日历、T+1、CORE保护、最大持仓、审核、原因和版本。提醒和已阅绝不交易。已确认技术风险义务保留原文规定的时序和经审核的解除方式。模拟库存与历史登记真实持仓及回测组合隔离；券商报告、部分成交和未知订单不属于此流程。

基本面由用户在生成计划时审核，不进入运行或模拟门禁。基本面与公告原文作为绑定审核的背景保留展示；混合句保留技术剩余片段及参数绑定。这种有限原文处理不能证明任意自然语言分类正确。Schema 1–4 原始字节、哈希和历史证据仍可读取，不进行转换；旧启用计划必须创建重新审核的当前版本。历史指数研究与回测保持隔离。

详见[当前规格](docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md)及[最新本地验收](docs/verification/2026-10-03-unified-plan.zh-CN.md)。确定性离线检查不认证当前实时供应商，也不批准用户的来源计划。

## 运行恢复修订

正常安装式 Web 入口及打包前端现使用监控协议 `2`。兼容的行情源语义不因时间经过而失效；当前依赖可用性、恢复进展及逐计划数据资格分别核验。安全停止后，重启接续持久工作，不重放已完成判断，也不将提醒视为成交。配置变更采用安全停止 → 编辑 → 新进程。准确证据和限制见[操作指南](docs/operations/live-certification.zh-CN.md#运行恢复与正常重启)及[最终验收记录](docs/verification/2026-10-03-unified-plan.zh-CN.md)。当前计划操作使用独立库存上的明确整单模拟；当前 API 和界面不再提供真实成交登记。



## 产品状态

安装式命令在回环地址提供 Vue SPA、REST 和 WebSocket。后端负责持久计划/审核状态、监测证据、恢复进展和原子隔离模拟；浏览器展示后端投影。`/plans` 提供当前原文到启用流程，`/alerts` 提供受审计幂等已读，`/system` 解释运行进展与不可用依赖。缺少投影是类型化不可用响应；真实存储/服务故障仍是错误。

总览保留共用指数图表与成交额事实，并与计划判断分离。冻结指数条件计划与隔离回测保留原有研究解释；当前计划统一不新增指数判断。历史供应商观察不等于当前就绪度。`899050.BJ` 保留为已知 `DEFERRED` 身份，不属于当前交易范围。

回测 `sync`、`verify`、`run`、`list` 和 `prune` 使用隔离行情/结果库。[回测验收契约](docs/verification/backtest-acceptance.zh-CN.md) 保留固定回归预算。默认自动测试使用确定性供应商；真实 Tushare、AI 和 Webhook 操作需要各自授权。配置、认证及安全重启见[操作指南](docs/operations/live-certification.zh-CN.md)。

## 安全边界

- 实时系统是监控和提醒软件，不是券商、订单路由或投资顾问。每条可操作提醒都包含“仅提醒，不会自动下单”；隔离的离线 `BACKTEST` 生成明确标注的研究成交；当前计划流程只在隔离模拟库存中记录用户明确确认的整单模拟交易（保留已有 `daily-simulation-v1` 回执格式）。
- 计划必须类型化、经审核、版本化，并在激活后保持不可变。AI 输出在确定性校验和用户审核通过前始终是不可信草稿；提取和草稿保存都不会自动启用它。
- 价格按整数“分”保存，数量按整数“股”保存，A 股时间戳必须是带 `Asia/Shanghai` 时区的值。
- 行情缺失、过期、无权限或来源语义未验证时安全阻断。
- 板块指数数据不会生成统一大盘强弱观点或隐藏交易规则。没有指数条件的计划在参考指数数据缺失时保持原有判断。
- 这款个人工具的所有供应商凭证都直接保存在被 Git 忽略的 `config/app.yaml`；不读取环境变量或独立凭证文件。
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

### 3. 配置本地凭证

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

YAML 保存供应商设置以及直接配置的 Tushare/AI 凭证。纳入版本控制的示例使用可替换占位值，
选择已验证的 Tushare 兼容端点 `https://api.quicksync.cn`，并选择 DeepSeek 的 OpenAI 格式端点
`https://api.deepseek.com`、主模型 `deepseek-v4-flash` 和附加模型 `deepseek-v4-pro`。AI profile、
显示名称、Base URL、主模型和附加模型、超时、重试次数、输入上限、输出上限、温度和凭证都可以
修改。同一 `ai` 配置段下的所有模型共享该段的传输设置和凭证。本地副本 `config/app.yaml` 会被
Git 忽略。直接替换以下字段：

```yaml
tushare:
  token: replace-with-your-tushare-token
ai:
  api_key: replace-with-your-deepseek-api-key
```

`config/app.yaml` 是唯一凭证来源。不要提交它、数据库、备份或构建输出。

Web 启动时会校验严格 YAML，并为本次服务生命周期创建不可变的 AI 模型绑定。计划工作台会在
供应商下拉中列出每个已配置模型。通用监控的 `DEGRADED` 状态与此独立，也不能证明 Tushare
已就绪。

### 4. 启动已打包本地 Web 界面

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

在同一台计算机上打开 `http://127.0.0.1:8765/`。使用 `Ctrl+C` 停止前台进程。必需的已认证 profile 缺失、过期、被篡改、端点/schema/范围不匹配或未就绪时，监控标题会诚实显示 `DEGRADED`、只读状态和没有下次轮询；打开 `/plans` 可使用 AI 草稿与持久计划管理。首次 lifespan 启动会创建或升级 `data/monitor.sqlite3`；之后启动时，计划保存、查询、导入、启用和停用都使用同一 SQLite 文件。数据库及其 WAL/SHM 伴随文件必须保持私密，且不得直接复制正在使用的 WAL 数据库作为备份。修改 `config/app.yaml` 时，先停止前台 Web/监控进程并等待其退出，再编辑文件并启动新进程。运行时不要编辑行情配置。启动因配置无效而拒绝时，在停止状态修正文件后重新启动。停止失败时，必须先解决故障，才能让另一实例使用同一数据库。仅刷新语义文件元数据无需重启。

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

已审核原文回测自动检查数据，仅在需要时执行 `DATA_SYNC`，验证后离线执行 `BACKTEST_RUN`。点击开始授权本次数据准备；只读访问页面不授权。同步仍使用 `allowNetwork: true`、有界任务和取消机制。合成供应商与浏览器测试通过，不证明真实 Tushare 可用性或语义。

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

示例配置选择 `https://api.quicksync.cn`。`create_tushare_client` 工厂从 `config/app.yaml`
读取 `tushare.token`，并把端点设置到单个官方 `tushare==1.4.29` `DataApi` 实例，不修改 SDK 的
进程级全局端点。系统拒绝明文 HTTP、内嵌账号密码、查询字符串和片段。

2026-08-25 经明确授权的检查已通过 HTTPS 和官方 SDK 验证 `stk_mins`：`600000.SH` 在 2026-08-24 的一个完整交易日返回 241 条一分钟记录，覆盖 09:30:00 至 15:00:00，包含预期的 8 个字段，且不存在重复行、必要字段空值、非法 OHLC、负成交量或错误股票代码行。该观察本身不能证明上游标签语义，因此适配器仍默认使用 `UNVERIFIED`；经审核的回测组合必须显式选择下文所述项目策略 `TUSHARE_STK_MINS_241_END_V1`。该观察和历史策略都不能替代另行要求的实时 `rt_min` 和 `rt_min_daily` 能力。

在另行授权的真实能力探测前，于 `config/app.yaml` 设置 `tushare.token`。能力、账号权限、限流和
分钟标签语义均独立发现；配置不代表能力可用。必要能力被拒绝或未验证时会阻断可操作输出。默认
契约测试使用确定性假 DataFrame：

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## 历史回测

历史读取对短暂竞争进行有界只读重试。准备进度接收已发布的确认／纠正详情，完成后临时读取详情失败也可恢复，不自动重发提取或审核。参见[读取可靠性验证](docs/verification/2026-10-18-backtest-read-reliability.zh-CN.md)。

运行记录筛选保留股票代码、包含边界当天的回测截止日期和固定状态。筛选界面已移除数据集哈希和计划版本 ID；旧页面链接先清除这两个条件及其游标，再读取记录。内部 API 和存储标识继续用于排查。日期比较覆盖截止日，固定的结果时间排序以文字说明；回放截止时间不是程序实际完成时间。参见[筛选操作说明](docs/operations/monitor-loop-backtest.zh-CN.md#ml-o21-运行记录筛选与时间含义)和[验证记录](docs/verification/2026-10-18-run-record-filters.zh-CN.md)。

正常回测页面只显示简短状态及 `服务管理`，刷新和待恢复任务查询收进面板。停止服务位于高级管理中，且需要确认。运行工作区区分结果与已接受任务记录；打开任务不会恢复执行。任务进度、取消及不确定请求重试保留既有语义。参见[服务操作及验证](docs/verification/2026-10-18-compact-backtest-service.zh-CN.md)。

工作区现已提供紧凑结果行、已访问页面导航、返回时定位原行、明确标注的已验证数据目录、生效版本选择和可键盘操作的权益图控制。读取在 10 秒提示等待、30 秒允许重试，刷新失败时标明保留的旧摘要。结果读取去除了重复模型构造，仍保留证据校验。详见[工作区契约](docs/specifications/backtesting/SPEC-backtest-workspace-ux.zh-CN.md)、[实施任务](tasks/backtest-workspace-ux.zh-CN.md)及[验证与性能限制](docs/verification/2026-10-21-backtest-workspace-ux.zh-CN.md)。

`main` 中基线 `7046d2e` 已完成约定范围内功能验收。[当前验收记录](docs/verification/2026-10-18-backtest-functional-acceptance.zh-CN.md)汇总已完成能力、纠正后的四份原文连续回测及测试依据。原文未量化条件保持未知，实际样本为零成交，不宣称新一轮全量集成／容量认证。历史验证记录保留当时日期和限制。

已批准的回测设计采用混合流程：经明确授权的 `DATA_SYNC` 把 `stk_mins`、`trade_cal`、`stk_limit` 和不复权 `daily` 事实增量下载到 `backtest-market.sqlite3`；本地校验冻结精确 `dataset_hash`；每次正式运行随后完全离线读取该冻结数据集，并且只把结果资产写入 `backtest-results.sqlite3`。

`/backtests/new` 页面会列出后端当前标记为 `canActivate=true` 的真实不可变计划版本，包括合格但未启用的草稿。用户选择一个准确版本；提交时后端会重新校验，并在返回已接受回执前持久化其规范计划快照。之后保存更新版本不能改变已排队任务、旧结果或其既有哈希。

行情库和结果库路径必须解析为不同文件。创建数据表前，每个存储都会拒绝既有实时监控数据库或另一个回测存储域，防止错误路径配置修改无关状态。

历史行按内容去重并由多次运行复用。供应商修订生成不可变修订和新数据集哈希，不能改变旧结果。历史适配器默认使用 `UNVERIFIED`；工作者组合显式选择版本化配置 `TUSHARE_STK_MINS_241_END_V1`，把 09:30 来源行保留为不参与策略的 `opening_special`，并把其余结束标签行映射为恰好 240 个规范交易分钟。该证据绝不能完成实时任务 `T058`。

一个数据集接受 1–10 只不重复股票、最多 5 个日历年的回测日期和最多 2 个日历年的预热。历史日历同步必须对每个所需 `SSE`/`SZSE` 交易所分别显式调用一次 `trade_cal`。Tushare 官方日历契约未列出 BSE，因此 `.BJ` 历史范围当前会在联网前以 `UNSUPPORTED_HISTORICAL_CALENDAR:BSE` 被拒绝；实时 `.BJ` 计划支持不受影响。真实历史适配器会拒绝无法解析/重复原始行，以及错误日历交易所/范围、日线股票/范围或涨跌停日期。由于 `stk_limit(trade_date)` 是市场全量响应，该日期的其他有效股票仍合法；同步层选择请求股票后，要求每个规范参考集合即使在 `refresh` 时也必须精确匹配，否则会在持久化前以 `INVALID_RESPONSE:<surface>` 失败。每次读取冻结 artifact 都会重新计算内容哈希，因此本地 payload 被修改后不能继续冒用旧 `artifact_hash` 回放。

冻结校验还会报告稳定阻断原因 `INVALID_<KIND>:<identity>:<date>`、`INVALID_CALENDAR_CHAIN:<exchange>:<date>` 和 `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>`，绝不会猜测或修复损坏事实。它在一个 WAL 读取快照下逐日校验分钟批次，然后仅用短 `BEGIN IMMEDIATE` 重新检查每个已选 head 并发布；并发修订会中止冻结。通过校验的 manifest 使用 O(1) 缓存 `natural_key` 索引执行后续成员查询，之后仍正常重算 artifact 哈希。

所有回测哈希共享精确 Decimal 规范化：`0.0003` 与 `0.00030` 这类数值相等的 scale 变体具有相同规范文本和 identity，二进制浮点及定点展开超过 10,000 个字符的值则失败关闭。回测复用经审核的计划哈希、规范 K 线、指标、收盘核对和纯决策引擎。`execution-model-v1` 仅用于回测：`signalAt` 等于产生该信号的判断 `snapshot.evaluatedAt` 以及来源事实的 `receivedAt`；只有后续满足 `openAt >= signalAt` 的候选 K 线才能成交。离散回放可以先完成产生事件，再处理同一边界的下一分钟 K 线，因此允许相等并不意味着能在产生信号的 K 线/桶内成交；生产历史分钟事实通常使用 `receivedAt == barEnd + 12s`，所以常规路径仍在之后的分钟成交，不会前视。成交把 `filledAt` 记录为执行分钟的 `openAt`。零成交量分钟会让订单沿连续规范候选继续等待之后第一根正成交量分钟；只有回放结束仍未出现时才变为 `SUSPENDED`。若缺少必需交易时段分钟，之后 K 线暴露缺口时会以 `MISSING_NEXT_MINUTE` 失败。每个 `ExecutionOutcome` 都包含不可变 `resolvedAt`，存在解决 K 线时还包含其 `sourceBarId`；只有 `NO_NEXT_MINUTE` 在结束时解决且没有来源 K 线。费用、滑点和部分持仓成本分摊使用带显式分取整的精确整数有理数算法，不依赖进程全局 Decimal context。系统确定性应用实际每日涨跌停、T+1、100 股整手、现金/仓位限制、费用和滑点。它绝不调用实时调度器、通知 Outbox、Webhook、WebSocket 或券商。

每次判断最多使用 512 根完整五分钟 K 线、当前日前 499 根官方日线和 512 个日历日事实。这些边界进入 `run_id`，并以 `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR` 展示；它们属于公开研究限制，本身不能证明多年资源验收。该独立闸门已由 BT050/BT008 证据完成。

报告还会公开以下限制：零成交量分钟作为不可交易代理（`ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`）、成交数量不受分钟成交量上限约束（`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`）、涨跌停锁定保守使用开盘价或滑点后价格（`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`）、回撤按每日权益采样（`DAILY_EQUITY_DRAWDOWN_SAMPLING`）、胜率按卖出成交而非往返交易统计（`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`），以及指标除法固定使用 Decimal precision 28 和 `ROUND_HALF_EVEN`（`METRIC_DECIMAL_PRECISION_28_HALF_EVEN`）。

在 `/backtests/new` 选择已审核计划、回放结束日期和成交假设后点击开始。程序检查本地证据，存在准确匹配的已验证冻结副本时自动复用，再补齐缺失的已结束日期历史数据、重新验证并启动回放。无需手动应用 URL、同步、验证或刷新缓存。历史数据管理仅查看数据集和任务记录。保留进度、取消、同一请求安全重试及失败后明确重试；不覆盖已有报告和冻结输入。旧版本与数据集回放继续使用既有冻结数据集。见[自动准备](docs/operations/monitor-loop-backtest.zh-CN.md#ml-o23-自动准备数据)。回测 CLI 命令及兼容适配器继续保持移除；应用启动命令仍启动网页服务。

“从原文准备新计划”每次准备一份原文。后续计划关联准确的已审核前序；逐份明确审核保存后，勾选 1–256 份已审核计划组合为一次连续回测。组合不调用 AI。保存时从正文提取明确的生效交易日，仅在日期缺失或有歧义时要求确认。成文时间和历史可用时间为可选信息。未声明可用时间的预置计划从生效日上海时间 09:30 开盘起执行，保留既有计划/账户审核及行情检查。详见[原文准备](docs/operations/monitor-loop-backtest.zh-CN.md#ml-o02-准备并审核有序原文)。

新后续提取默认保留未提及的已审核规则和字段，仅提出有原文依据的变更。审核展示保留、修改、新增和取消；提取／校验错误与真正的原文歧义分开呈现。有界自动纠正不能自行审核候选。通用机制通过回归检查及四份实际原文、八个不同措辞案例的有复核真实验证；新连续回测完成1468次评估、0成交，仍必须审核语义，详见[当前验证记录](docs/verification/2026-10-17-generic-inheritance.zh-CN.md)。

风险退出现已按新旧持仓批次执行。明确排除新仓时，旧批次继续保留继承退出规则；新批次按新计划处理，准确扣减对应批次并遵守 T+1、核算对应成本。结果页在规则变更和价格诊断旁展示适用范围及退出批次。修正后的四份实际原文继承链另行完成 1468 次评估的连续回测、0 成交；实际价格未满足买入前提，未量化条件仍明确展示。参见[持仓批次验证](docs/verification/2026-10-18-cohort-risk-execution.zh-CN.md)，它替代先前的执行限制和第四份错误取消结论。

结果页顶部现展示收益汇总：总盈亏、已实现盈亏、浮动盈亏及已确定的回测截止日期。金额保留报告的成本／费用口径，区分零与数据不可用。切换结果标签页仍可查看汇总，不新增本金收益率。参见[收益汇总操作说明](docs/operations/monitor-loop-backtest.zh-CN.md#ml-o20-顶部收益汇总)。

运行摘要、假设、最终指标和成交账本长期保留。成功运行的判断/信号/每日权益详情只保留最新 100 次且最多 90 天；失败、取消及按需调试详情保留 14 天；置顶运行豁免。结果发布先把规范行 staged 到 `backtest-results.sqlite3`；普通读取和统计看不到任何 staged 行。只有完整 `reportHash`、预期成交/详情数量和规范 identity/内容集合哈希都匹配时，一个事务才会设置内部 `materialized` 可见性标记。首次发布会持久化这些数量和集合哈希，已发布运行的每次重试都必须精确匹配；普通摘要/成交/详情读取还会在应用任何 detail-kind 过滤前，根据已哈希 payload 校验每个 SQL identity。Web/API 从已持久化结果导出经过校验的 JSON 和 CSV。`materialized` 是唯一发布闸门，但不是公开运行状态；公开状态仍为 `COMPLETED`、`FAILED` 或 `CANCELLED`。有界 `prune` 维护会在 14 天后移除未置顶的废弃 staged 摘要/成交/详情，近期 stage 仍可恢复。文件缺失或损坏时，可以根据长期摘要/成交行重建，不联网、不重放、也不重复成交；已清理的判断/信号/结果/权益详情按设计不可重建。`reportHash` 继续作为原始完整运行的审计 identity，并不是文件字节哈希。Web/API 支持置顶和初始持仓批次。不保存完整逐分钟账户快照，也不重复保存行情行。隔离、禁止未来数据、报告及保留契约详见 [SPEC-backtest.zh-CN.md](docs/specifications/backtesting/SPEC-backtest.zh-CN.md)。

## AI 配置与凭证

仅在启用 AI 辅助草稿时才需要 `ai.api_key`，它可直接保存在被 Git 忽略的
`config/app.yaml`。默认 `DEEPSEEK` profile 按 DeepSeek 当前接口发送 `max_tokens`、
`thinking={"type":"disabled"}` 和 JSON 输出字段。若要使用其他兼容服务，可把 `profile` 改为
`OPENAI_COMPATIBLE`，并配置 Base URL、模型和 API Key。运行时供应商配置保存内部引用、模型、
有界超时/重试/Token 限制和 HTTPS 基础 URL（仅显式回环主机允许明文 HTTP）。

API Key 只由后端加载，公共契约无法返回。Web 页面只显示供应商名称、模型、安全 Base URL、限制、启用状态和密钥是否已加载；没有供应商修改、Token 输入、密钥替换或连接测试控件。系统拒绝重定向、URL 内嵌账号密码、带查询参数的基础 URL、执行原始模型内容以及包含密钥的校验错误。AI 输出绝不会直接激活。

Web 是主要 AI 使用方式：打开 `/plans`，粘贴原文，提交后审核经过校验的结果。后端最多同时执行一个提取，页面只轮询精确任务 ID。修改 `config/app.yaml` 后必须重启 Web。CLI 保留为维护工具；下面两个命令都会向真实服务发送请求，并可能产生 Token 费用：

```powershell
# 使用 config/app.yaml 发送一次最小连通性请求。
python -m trade_plan_monitor ai test

# 读取一个 UTF-8 文本文件，返回仅供审核的结构化草稿。
python -m trade_plan_monitor ai extract --source .\plan-source.txt
```

如需选择其他配置文件，在 `test` 或 `extract` 后增加 `--config <路径>`。命令会拒绝不存在的
来源文件、目录、非法 UTF-8、超过配置字符上限的文本，以及缺失或为空的已配置 API Key，不会
把不合格结果当成有效草稿。Web 与 CLI 使用同一应用配置，不存在环境变量或独立文件凭证后备。

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
| 界面显示 `DEGRADED` 或类型化 `UNAVAILABLE` | 当实时分钟 `SourceTimeLabel` 语义或实时板块指数供应商未验证，或权威投影尚未完成时，这是预期行为。后端会保持只读健康状态，不调度可操作监控；真正的服务、存储或组合故障仍返回 `SERVICE_UNAVAILABLE`。独立的计划与持久持仓流程在已存计划/日历前置条件存在时仍可使用。 |
| `runtime service factory is not configured` | 在应用服务组合接通前调用了 `validate`、`monitor`、`replay` 或 `backup`。 |
| 监听主机校验失败 | 使用精确字面量 `127.0.0.1`；系统有意拒绝 `localhost`、`::1`、`0.0.0.0`、主机名和局域网地址。 |
| 8765 端口占用 | 停止另一个本地进程，或选择 1～65535 中未占用的其他端口，同时保持主机为 `127.0.0.1`。 |
| `SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT` / `SQLITE_EMPTY_WAL_RECOVERY_BUSY` / `SQLITE_EMPTY_WAL_RECOVERY_FAILED` | 回测存储启动只在不可变只读检查确认结构为完整当前版本、没有待迁移项或元数据修正后，恢复空 `-wal`（可伴随 `-shm`）。SQLite 执行 checkpoint 并关闭恢复连接，随后启动重新执行严格预检，要求所有伴随文件均已消失。若恢复被占用阻断或伴随文件仍存在，关闭其他应用/IDE 的数据库连接。有内容的 WAL、回滚日志、孤立文件、未知/旧结构及待扩展结构仍需在停止状态下进行已验证维护；不要手动删除伴随文件。迁移预检本身保持只读，拒绝所有伴随文件。 |
| `SQLITE_SOURCE_BUSY_OR_UNREADABLE` | Windows 上的 SQLite 字节范围锁或文件系统权限阻止了预检读取源文件。关闭其他数据库连接并检查文件权限后重试。预检保留源文件。 |
| YAML 报告未知字段 | 重新从 `config/app.example.yaml` 开始；schema 会有意拒绝不支持的节。 |
| Tushare 能力为 `DENIED`/`UNVERIFIED` | 检查 `tushare.token` 和账号权限，然后运行获批的真实探测。 |
| AI 返回配置/鉴权错误 | 检查 `config/app.yaml` 中的 `ai.api_key`、profile、Base URL 和模型。 |
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

英文文档是实施流程的权威输入，同名 `.zh-CN.md` 是中文审阅副本。两种语言须在同一次变更中保持语义等价。

从[文档索引](docs/README.zh-CN.md)（[English](docs/README.md)）、[当前计划规格](docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md)、[能力地图](docs/architecture/CAPABILITY-MAP.zh-CN.md) 和[操作指南](docs/operations/live-certification.zh-CN.md) 开始。冻结计划/重放契约明确限定兼容用途；已完成过程报告及旧附件不作为开发入口保留。

## 开发流程

1. 每次只实施一个获批的工作区任务。
2. 修改前阅读任务、模块契约和当前代码。
3. 行为或文档修改前先增加失败测试或契约检查。
4. 运行受影响测试、全量回归、Ruff、格式、编译、依赖、安全和双语一致性门禁。
5. 行为、命令、架构或公共契约变化时，同步更新英文和中文文档。

## 金融免责声明

本项目是个人监控与提醒工具，不构成投资建议、券商服务或订单执行系统。行情数据、AI 输出、技术指标和提醒都可能延迟、不完整或不正确。用户必须自行审核每份计划，并对所有交易决策承担全部责任。

计划准备现已集中展示真正需要确认的事项，并自动处理原文明示事实、停用区间及分笔顺序。参见[原文确认验证](docs/verification/2026-10-16-source-confirmations.zh-CN.md)。

回测统一使用“准备计划”入口，默认衔接上一份已审核计划，并按保留、修改、新增和取消审核规则。不再选择完整／修改文档类型。参见[统一准备验证](docs/verification/2026-10-16-unified-preparation.zh-CN.md)。

从原文新准备的监测循环回测采用 `POSITION_LIMIT_ONLY`：无需期初现金，仍遵守交易授权数量及当前最大持仓。日线回放使用已冻结且有时点约束的复权因子依据。输入已知时保留成交盈亏和费用，不计算本金收益率和净值回撤。可用[计划生成模板](docs/templates/trading-plan.zh-CN.md)在审核前明确量化条件。参见[验证记录](docs/verification/2026-10-17-daily-basis.zh-CN.md)。

已完成结果摘要提供逐份计划成交诊断：实际／要求价格、行情未满足、定性口径待明确、处理问题，以及独立的执行／数据限制。已知条件自动解释，不新增确认字段。更新后刷新仍保留明细的旧结果即可查看投影；过期审计明确显示不可用。参见[结果诊断说明](docs/operations/monitor-loop-backtest.zh-CN.md#ml-o16-结果页逐份诊断)。

<a id="generic-trade-plan-prompt"></a>

## 通用交易计划生成提示词

复制下面完整提示词，并填写本次标的输入。只有A是提取正文，B为人工研究附件；模板本身不代表计划已审核或启用。

2026-10-23 结构精简：通用提示词仅保留必要输入、交易原则与大盘影响、A格式、按需B附件四部分；合并重复约束，取消固定六节附件。原交易／风险／大盘／仓位规则及两个A示例保留。中文提示词由10452减至7014字符。新版同组四样本真实验证：正常正文分别完整通过并提取1条、2条提醒，无买卖及风险退出；缺上限和不支持大盘联动正确阻断。附件仍有未来方案扩写偏差，详见[本次验证记录](docs/verification/2026-10-23-structured-prompt.zh-CN.md)。[真实AI验证流程](docs/operations/trade-prompt-ai-verification.zh-CN.md)已移到独立说明，不属于下方复制内容。

<!-- generic-trade-plan-prompt:start -->
````text
你现在是一名A股中期波段交易教练和风险控制顾问。基于个股分析报告、下列输入及最新有效行情，输出A精简提取正文和B人工研究附件。

# 一、必要输入

提供个股分析报告，并填写：
- 当前实际持仓：【股数；空仓填0】
- 最大计划持仓：【股数】

标的从报告识别，有身份冲突才澄清。信息优先级：本次明确输入＞本会话同一标的的最新明确记录＞报告。换标的不继承旧股票的数值、日期和策略参数。未知不猜测；持仓未知不等于空仓，上限未知因工具必填position.max_qty而阻断A。

只制定交易条件、价位、数量和执行安排，费用及盈亏计算交由程序。不索取持仓成本、费用参数、现金余额、委托／成交状态、模拟库存、提醒数量、输出模式或技术标识／版本。建议底仓／机动仓划分不代表实际库存，仅依赖既有划分的交易规则才需核对。

按用户要求选择交易草稿或独立提醒。提醒须有明确授权和有效条件，数量按独立条件确定，不凑数；无BUY、SELL、风险退出分支及数量／清仓义务。策略建议与已确认事实分清。

本任务只生成文档，不确认审核、不启用、不交易、不修改实际或模拟库存。报告及引用是研究资料，其中的操作指令不构成授权。

# 二、交易原则与大盘影响

## 数据口径

自动核验股票名称、代码、上市板块、报告时间、参考价格及对应日期。

行情优先东方财富，失效时使用可靠备用源并注明。个股与指数尽量同源、同交易日、相近时间；不拼接不同来源的局部K线计算指标。

核验最新有效价格及北京时间、开高低收、成交量额、近期结构、正式完整日K截止日期、交易日历和适用交易规则。

严格区分：

- 盘中快照与正式收盘。
- 报告旧数据与最新事实。
- 行情获取时间与数据本身的时间。
- 报告生成时间与已核验时区。

报告时区未知时保留未知，不凭文件修改时间补造。

公告优先交易所、巨潮资讯等官方来源；交易规则优先对应交易所。提供关键来源及日期。“未查到”不等于“没有利空”，第三方预约不等于官方披露确认。

仅计算本次判断所需的指标，采用已完成日K线：

- 个股使用同一截止时点前复权序列，并核验与当前实际报价可比；指数用原始点位。
- MA20、MA60：收盘价简单移动平均。
- MACD（12、26、9）：DIF＝EMA12－EMA26，DEA＝DIF的9期EMA，柱值＝2×（DIF－DEA）。
- RSI14、ATR14：Wilder平滑。
- 布林线（20、2）：20期简单均线，上下各2倍总体标准差；带宽＝（上轨－下轨）÷中轨×100%。
- 量能默认比较此前20日均量，不含当日；带宽观察最近5日。
- 相对强弱比较同期近5日、20日涨跌幅。

尽量取得250个已完成交易日计算及预热，不将250日作为所有判断的统一门槛。无法可靠计算的指标标缺失，不混用不同口径。

MA20与布林中轨不能重复作为两个独立依据。盘中累计量不能直接与历史全天量比较。

数据不足只限制受影响的判断。不得填造价格、股数、日期、指标或公告结论；数据不足也不代表已有持仓安全。

## 交易原则

## 1．基本原则

底仓跟踪中期趋势，机动仓在低吸区企稳后买入、压力区受阻后卖出，可以跨日完成，不强求日内做T。

底仓不参加普通高抛低吸；机动仓不因被套改称底仓。机动仓为0时，不为凑减仓动作卖出有效底仓。

卖后不回落不追买，买后下跌不因浮亏自动补仓。突破当天不追买，接近跌停不视为普通低吸机会。

冲突处理优先级：

已确认风险＞最新价格及量价结构＞官方事件与基本面变化＞中期趋势及风险收益＞辅助指标＞报告观点。

报告中的BUY、HOLD、SELL和“主力吸筹”等只是观点。区分讨论方案与最终结论，不拼接互相冲突的方案。

当前主动作只选一个：

等待、低吸一笔、继续持有、反弹减仓、风险退出。

动作必须与真实持仓和权限一致。没有持仓不选择持有或卖出；新增买点未确认不自动否定仍有效的底仓。

### 2．三个核心研究位置

只设置：

- 主要压力区。
- 低吸观察区。
- 核心风险位置。

分别说明用途、端点、截止日期、固定或动态性质。

交易计划中新研究的每处价位至少两个不同维度的个股依据，其中至少一个来自前高前低、平台等价格结构；指数不充当个股价位依据。

同一低吸方案原则上满足：

风险位置＜低吸区下沿，低吸区上沿＜压力区下沿。

缺依据时留空，不为产生买点重画价位。观察区不等于可买区。空仓结构提醒线不能默认作为未来新仓止损。

已有持仓的明确退出线单独保留其用途和优先级，不能下移到另一个更低的观察位置。

突破、破位、新高新低、权息变化或重大公告后重新评估。原持仓风险线不得仅因下跌或亏损下移，也不得重画价位取消已确认风控。权息变动只作保持经济风险不扩大的等效换算。

### 3．普通买卖确认

普通买卖须结合价格结构、量价或K线、至少一项技术辅助证据。单独触轨、金叉、死叉、超买或超卖不触发交易。

低吸须有明确企稳证据、量能不再异常恶化及技术辅助改善；不断创新低、连续放量下跌或沿下轨走弱时不低吸。

反弹减仓须进入压力区并有受阻及技术辅助转弱。缩量上涨或布林带扩张不能单独触发卖出。

“企稳、放量、受阻、高波动、严重破位”必须定义比较对象、窗口和依据，注明ALL／ANY。无法可靠定义时列为待人工确认，不能视为已成立。

普通日线交易统一遵守：

- 正式收盘确认，最早下一交易日执行，窗口截至该日收盘。
- 执行时价格仍在区域内，原信号、数量、额度及风险前提仍有效。
- 已确认且仍在窗口内的信号，不因更新计划额外等待一天。
- 离开区域不追价；过期信号重新核验。
- 一信号对应一笔计划数量。
- 新增交易须有独立信号，不能仅换日期复用旧信号。
- 写明具体日期或“收盘确认后、下一交易日”，并核对交易日历。

### 4．风险处理

普通技术性跌破：
首次正式收盘跌破停止加仓；下一交易日收盘仍未收回才确认退出，最早再下一交易日执行。收回后只观察，不直接恢复买入。

严重技术性破位：
首次收盘已同时确认实质结构破坏及明显量价恶化，可下一交易日退出。列出真实证据，不临时拼凑统一跌幅、量比或收盘分位门槛，也不为量化延误已确认风控。

重大基本面逻辑失效：
官方信息核实并明确推翻持有理由后，由人工决定，在可交易时优先处理，不等待技术价位或第二个收盘。传闻和普通业绩波动不自动等同逻辑失效。

原报告或已确认方案有更明确、更及时的退出条件时，保留其适用范围和优先级，不能用通用流程延后。

有仓风险方案须明确是否涉及底仓、机动仓、目标保留数量及可卖约束。机动仓优先最近新增部分；中期结构失效涉及底仓。受限余量注明下一次可执行条件，不为形式上的分步额外拆天。

已确认风控不因未回本、辅助指标未恶化或盘中反抽取消。风险线不保证成交价格。

### 5．期限

计划可持续至人工停用或审核启用新版替换，但必须保留原文明确期限，不自动延长。

不能将某只股票的“三季报前退出”“财报后1—3个月重评”等要求套用到其他股票。原文未规定时，不补造相同期限。

## 大盘影响

有低吸研究时适用本节；独立提醒不因此增加大盘门槛。本节属于研究约定，不是市场通用定律，也不代表trade-plan-monitor已经支持自动指数联动。

### 1．参考指数及状态

按实际上市板块选择上证指数、深证成指、创业板指数、科创50或北证50，核验名称、代码及工具表示方式。不用行业或概念指数替代。

使用正式完整指数日K：

- I：当日收盘。
- M20、M60：当日MA20、MA60。
- M20_5：5个交易日前的MA20。
- L20：此前20日最低点，不含当日。

按优先级判断：

1. 明显结构破坏：I＜L20且I＜M60。
2. 走弱：未满足上述破坏，且I＜M20、M20＜M20_5。
3. 常态／过渡：必要数据完整且上述两类均不成立。
4. 未知：必要数据无法核验，或无法排除更高优先级状态。

展示实际数值及条件真假，不以盘中跌破代替正式收盘确认，不冻结动态指标。

### 2．相对强势

同时满足：

- 近5日个股收益高于参考指数。
- 近20日个股收益高于参考指数。
- 个股正式收盘不低于当日MA20。

缺项或任一不满足，不能使用相对强势豁免。

### 3．确认与数量

S0：本标的完整基础低吸条件，须明确区域、量价或K线、技术辅助、ALL／ANY、确认及独立信号。

S1至少同时要求：

- 相邻两个有效交易日收盘均在低吸区。
- 后收盘不低于前收盘。
- 最终日满足完整S0。
- 最终日量不超过此前20日均量。
- 最终日RSI14高于前日。
- 无更高优先级风险。

S2：S1全部成立，且两日收盘分别不低于各自当日MA20。

S0不完整时，S1／S2不能被判为完整通过。不能继承其他股票的S0。

缺失或未定义项写“未确定”，不得伪装为已核验的真或假；已有明确不满足项时可以写“不满足”，并列出该项。

Q0为先依据本标的结构、波动及额度确定的研究单笔数量；L为适用的合法数量单位。不能先看折减结果，再提高Q0。

| 大盘状态 | 数量及确认影响 |
| --- | --- |
| 常态／过渡 | S0及其余前提满足后，研究不超过Q0的数量 |
| 走弱 | 按合法申报数量向下取整至不超过0.5×Q0，同时提高至S1 |
| 走弱且不足最低买入量 | 暂停低吸；相对强势、S1及其余前提成立后，才可人工研究最低合法数量例外 |
| 明显破坏且个股不强势 | 新增0股，暂停低吸 |
| 明显破坏但个股强势 | S2成立后人工复评，例外数量未确认前仍为0股 |
| 必要数据或参数未知 | 不假定常态，暂停依赖这些信息的低吸 |

对最小申报量和递增单位不相同的板块，按实际规则向下选择合法数量，不统一套用100股倍数公式。

不得向上凑整、突破Q0或剩余额度。指数改善不自动恢复买入，也不单独触发卖出有效底仓。

如果买入数量或成立条件必须依赖上述大盘状态，而工具没有原生支持，不能删除大盘约束后导入残余买入规则。须保留为人工方案；或由用户明确选定当期静态分支、数量和条件，再另拟完整版本。

## 仓位与交易约束

实际底仓＋机动仓不得超过持仓上限。

计划可加仓数量＝max(0, 持仓上限－当前实际持仓)。这是计划数量，不是券商实时可买额度。实际持仓或上限未知时不计算；上限不是必须买满的目标。

核验适用的T+1、涨跌幅、特殊交易状态、最低申报量、递增单位及零股规则。买入不假定当日可卖，卖出不得超过实际可卖量。

## 工具能力边界

依据实际项目核对能力；无法访问时注明仅依据已有记录。当前基线：Schema 5支持已注册且参数完整的个股条件；普通规则最多2条、作用于TACTICAL，同向分批须有先后关联，首次普通买入形成CORE不能假定支持；无原生自动指数联动、动态数量及S1／S2切换能力；基本面与公告由人工核验；无券商下单能力。仅提醒不依赖模拟库存。

必要条件不支持时阻断整条规则，不删除依赖、改数量或底仓归属、伪装人工事实来通过，也不擅自改成提醒。独立提醒不附加无关研究门槛。

# 三、A：精简提取正文

A只含本次可完整承载的政策；原因与研究放B。规则无法完整承载、身份未核验或缺必填参数时，A必须精确等于“暂不提供可导入正文。”，不附加任何原因、字段或示例。

使用已验证的根字段和父路径作用域格式：

```text
计划根字段语义值
schema_version=5 execution_mode=CONDITION_PLAN execution_version=condition-plan-v1
plan_id=<本次标识> version=<本次版本> symbol=<本标的代码> name=<本标的名称> market=<对应市场>
metadata.report_at=<已核验时间或null> metadata.reference_price_fen=<对应日期参考价或允许的null>
activation.mode=MANUAL
position.max_qty=<本标的明确上限>
```

- 根路径不加draft.。symbol保留6位代码及.SH／.SZ／.BJ（含前导零），market对应SSE／SZSE／BSE。
- 新计划标识由生成过程拟定并在B注明未保存，版本遵守已核验新建契约；续接准确读取原标识／版本。
- 元数据使用对应日期事实，未知时间为null，不造时区；固定引用保留实际来源日期和原文，不替换为生成日期。
- 每条规则完整保留类型、比较对象、参数、单位、引用、确认，以及适用的数量、分桶、窗口、期限和关联。ALL／ANY写明全部子条件。
- 空组独占一行：“无普通规则”“无风险分支”“无提醒规则”，对应真正空数组；非空组按ordinary_rules[i]、risk_branches[i]、alert_rules[i]展开。
- 按契约保持整数分、Decimal字符串、null和数组的类型。levels按实际用途填写，独立提醒不使用区域时为null。
- 仅已核验、未被原文覆盖的PRODUCT_CONTRACT固定默认值可省略；策略数量、价格、确认、期限、分组不能按默认猜补。原文未设期限时沿用已核验的PLAN_ACTIVE／MANUAL约定，不另设到期日。

仅提醒采用下列排列：

```text
计划根字段语义值
schema_version=5 execution_mode=CONDITION_PLAN execution_version=condition-plan-v1
plan_id=<PLAN_ID> version=<VERSION> symbol=<SYMBOL_WITH_EXCHANGE> name=<NAME> market=<MARKET>
metadata.report_at=<VERIFIED_TIME_OR_NULL> metadata.reference_price_fen=<REFERENCE_FEN_OR_NULL>
activation.mode=MANUAL levels=null position.max_qty=<MAX_QTY>
无普通规则
无风险分支
alert_rules[<i>]: kind=RISK_ALERT rule_id=<RULE_ID> condition.type=<CONDITION_TYPE> <ALL_OTHER_CONDITION_FIELDS> confirmation.kind=<CONFIRMATION_KIND> <OTHER_CONFIRMATION_FIELDS_IF_REQUIRED>
alert_rules[<i>].condition.reference: mode=<REFERENCE_MODE> value="<EXACT_VALUE>" unit=<UNIT> as_of=<SOURCE_DATE_OR_NULL> source="<SOURCE_LABEL>"
<SOFTWARE_FIELDS_NOT_COVERED_BY_VERIFIED_PRODUCT_DEFAULTS_IF_ANY>
```

索引从0连续。冒号前为完整父路径，后面是相对字段，用空格分隔，不用JSON对象或逗号枚举。日线价格比较首行含condition.field、condition.offset、condition.comparator，第二行完整保留reference并给Decimal值加引号。无reference则省第二行；五分钟确认保留周期，复杂条件用完整子作用域。每行最多512字符，超长拆为明确父路径行。规则ID用A1、A2等简短中性编号，不嵌入股价。占位符换成实际值，未用行省略。不生成clauses、bindings或来源结构，交由提取器严格处理。

# 四、B：按需人工研究附件

只解释本次结论、实际规则依据、相关大盘影响及工具限制，按内容自然组织，不规定章节数或要求填满表格。仅提醒说明真实阈值、来源及确认，不补齐三类交易价位、低吸分支或无关分桶；用户明确阈值无需再次确认研究含义，也不套用新研究交易价位的双重依据要求。

只列当前方案真正缺失的必要参数和不支持的必要能力，无则写“无”。数据缺口说明影响即可；不把已知值、默认期限、未选替代方案或未来策略参数列为待确认。A阻断时简述已知事实与阻断原因即可，上限缺失只需确认上限，必要能力已不支持时，B只写这一阻断与已知事实，不再泛列其他参数或期限缺失，也不展开用户未选的替代方案。

用简短“如果……那么……”解释当前操作，区分已确认信号与待触发条件。文档中的候选规则不代表已审核或启用。

只输出A和B，常规文本用两个标题；调用端要求JSON时仅返回A、B两个字符串，A不加围栏。只有A用于后续提取。
````
<!-- generic-trade-plan-prompt:end -->
