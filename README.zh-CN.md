# 交易计划监控系统（Trade Plan Monitor）

[English README](README.md)

一个独立、仅本机使用的 Web 应用，用于把经过审核的 A 股交易计划转换为确定性监控规则，并生成文字和可视化提醒。系统面向一名用户，最多启用 10 只股票，使用 Tushare 行情、用户可配置的 AI 计划草稿能力和单个 SQLite WAL 数据库。

> 开发状态：任务 `T001`～`T052` 和检查点 `C00`～`C21` 已完成。仓库现已包含经过审核的确定性后端、本地 REST/WebSocket/OpenAPI 边界、完整无障碍 Vue 展示，以及无需 cwd/源码 fallback 即可发现已打包 Vite distribution 的安装式仅回环生产命令。下一项 `T053` 负责编写双语安装与运维指南。

## 产品目标

- 粘贴自然语言交易计划，通过用户配置的 OpenAI-compatible 服务生成结构化草稿。
- 展示提取字段、原文证据、假设、警告、遗漏和版本差异，供用户审核。
- 只有通过确定性校验并由用户明确确认的不可变计划版本才能激活。
- 使用 Tushare 分钟、日线、交易日历和涨跌停数据，最多监控 10 只 A 股股票。
- 只根据完整且新鲜的行情，通过纯确定性决策引擎进行判断。
- 在 SQLite WAL 中持久化策略状态、人工持仓批次、T+1 约束、审计、提醒和回放状态。
- 生成去重、可追溯的文字和可视化提醒，但不执行下单。
- 提供只绑定 `127.0.0.1` 的本地 FastAPI REST/WebSocket 服务和 Vue 3 仪表盘。

## 当前实施状态

最近一次验证环境为 2026-08-24、CPython 3.14.7。

| 领域 | 任务 | 状态 |
|---|---:|---|
| Python 和 Vue 工具链脚手架 | `T001`～`T003` | 已完成 |
| 计划模型、条件 DSL、校验、编解码、哈希和样例计划 | `T004`～`T007` | 已完成 |
| 行情契约、A 股交易时段、规范化和 Tushare 适配器 | `T008`～`T010` | 已完成 |
| SQLite WAL Schema、仓储、策略状态和已验证在线备份 | `T011`～`T014` | 已完成 |
| AI 配置、只写密钥、有界供应商适配器、提示词和提取 | `T015`～`T017` | 已完成 |
| 幂等行情历史、`ta-v1` 指标和临时/官方收盘核对 | `T018`～`T020` | 已完成 |
| 强类型条件、低吸事件、压力/风险判断、优先级、哈希和回放 | `T021`～`T024` | 已完成 |
| 提醒标识、确定性渲染、事务 Outbox 和有界渠道投递 | `T025`～`T027` | 已完成 |
| 注入式行情时钟、感知交易时段的截止点和有界 Tushare/AI 请求控制 | `T028`～`T029` | 已完成 |
| 逐股票编排、恢复、原子判断和已提交发布 | `T030`～`T032` | 已完成 |
| 官方收盘核对、持久待处理状态和启动重试 | `T033` | 已完成 |
| 有归属的生命周期、脱敏健康、优雅关闭和维护 CLI 边界 | `T034` | 已完成 |
| 无副作用 FastAPI 应用、有归属 lifespan、共享 Schema 和错误映射 | `T035` | 已完成 |
| 监控总览、股票、K 线、事件和运行时健康只读 API | `T036` | 已完成 |
| 计划版本、草稿/导入/提取/启停用和只写 AI 供应商操作 API | `T037` | 已完成 |
| 人工持仓、规范提醒中心、确认和诊断 API | `T038` | 已完成 |
| 全局持久监控事件账本与带序号 WebSocket 回放 | `T039` | 已完成 |
| 本地 Origin 安全与显式 Vue 构建 SPA 服务 | `T040` | 已完成 |
| 冻结 OpenAPI、生成 TypeScript 契约和 Vite 文档入口 | `T041` | 已完成 |
| 无障碍响应式 Vue 应用外壳与路由 | `T042` | 已完成 |
| 设计变量、有界 API 客户端和规范化只读 Pinia 状态 | `T043` | 已完成 |
| 可恢复监控 WebSocket 生命周期与外壳连接状态 | `T044` | 已完成 |
| AI 供应商设置与原文提取审核工作台 | `T045` | 已完成 |
| 结构化计划编辑、不可变差异和激活界面 | `T046` | 已完成 |
| 无障碍多股票总览和权威监控列表 | `T047` | 已完成 |
| 个股图表、证据和阶段/风险时间线视图 | `T048` | 已完成 |
| 经显式确认的人工持仓批次操作 | `T049` | 已完成 |
| 文字提醒中心与确认核对 | `T050` | 已完成 |
| 系统健康与完整无障碍检查 | `T051` | 已完成 |
| 安装式生产启动和已打包 Vue 资源 | `T052` | 已完成 |
| 运维、回放、浏览器、安全、稳定性与外部验收 | `T053`～`T059` | 待实施 |

完成 `T052` 后，全部 1256 项后端测试通过；精确打包门禁包含 11 项，完整前端门禁包含 179 项，真实 Chromium/axe 无障碍门禁包含 3 项，未改动的 REST/WebSocket/OpenAPI 传输门禁包含 156 项，未改动的判断/回放门禁仍为 273 项。Ruff、`compileall`、`pip check`、双语对齐、生成契约漂移检查、`git diff --check`、前端类型检查、基于文档入口的生产构建和本地 wheel 内容检查均通过。这些测试均为确定性测试，不需要真实调用 Tushare、AI、Webhook、数据库或外部网络监听。固定的 FastAPI/Starlette TestClient 当前会产生一条建议改用 `httpx2` 的上游弃用警告；它不影响生产行为。检查点 `C21` 保持完成，下一项为 `T053`。

## 安全边界

- 仅作提醒：系统不提交、撤销、推断、模拟或对账券商订单。
- AI 输出是不可信草稿数据。AI 不能激活计划、执行代码、写 SQL、调用行情工具，也不参与盘中决策链路。
- 实际成交和持仓批次由用户人工录入；确认提醒绝不会修改持仓。
- 非回环 AI 地址必须使用 HTTPS。系统拒绝重定向、URL 内嵌账号密码、无界重试、压缩服务响应和超大响应。
- Tushare 与 AI 凭据通过受保护的运行时输入引用；原始值不得进入计划、SQLite、日志、审计、导出、夹具或普通 DTO。
- 通用 Webhook 默认关闭，只接受精确 HTTPS 主机白名单，拒绝重定向和内嵌账号密码，并且从不保留响应体。
- 目标 Web 服务只接受精确的 `127.0.0.1` 监听字面量和精确配置的 HTTP Origin。禁止端口转发、反向代理、主机别名以及公开/局域网暴露；系统未实现登录鉴权。
- HTTP 响应携带 CSP、frame、内容类型、referrer 和 permissions 防护；生产环境关闭 CORS，原始请求体先受 4 MiB 上限限制，再应用更严格的字段/导入限制。
- 静态 SPA 服务不能覆盖 `/api/v1` 或 `/ws/v1`。生产环境只发现打包在 `trade_plan_monitor.web` 下的完整 Vite distribution；资源缺失或不完整时使用固定且不含路径的诊断失败，不存在 cwd 或源码树 fallback。

每条可操作提醒都将包含等效免责声明：

```text
仅提醒，不会自动下单。
```

## 架构

```text
自然语言计划
     │
     ▼
ai-plan-drafting ──→ 审核后草稿 ──→ plan-domain ──→ 不可变活动计划
                                                     │
Tushare ──→ market-data ──→ 规范化完整 K 线           │
                    │                                │
                    └────────→ strategy-state ←──────┘
                                      │
                                      ▼
                               decision-engine
                                      │
                                      ▼
                            notification-outbox
                                      │
                                      ▼
                               monitor-runtime
                                      │
                                      ▼
                local-web（FastAPI REST/WebSocket + Vue 3）
```

一个 Python 进程将统一管理 FastAPI 生命周期、监控运行时、确定性决策引擎和 SQLite WAL 数据库。Vue 3 单页应用构建为静态资源，并由同一个回环地址 Origin 提供。同步 Tushare 调用与异步 AI 调用使用彼此独立的有界执行路径，避免 AI 延迟行情监控。

## 技术栈

| 层次 | 技术 |
|---|---|
| 后端 | Python 3.14.x（`>=3.14,<3.15`）、FastAPI、Uvicorn、Pydantic 2 |
| 持久化 | SQLAlchemy 2、Alembic、SQLite WAL |
| 行情数据 | Tushare Pro SDK、pandas |
| AI 集成 | 基于 `httpx` 的 OpenAI-compatible Chat Completions 契约 |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Vue Router、ECharts |
| 质量保障 | pytest、Ruff、Vitest、Vue Test Utils、Playwright、axe-core |

依赖版本固定在 [pyproject.toml](pyproject.toml) 和 [web/package.json](web/package.json) 中。

## 环境要求

- CPython 3.14.x；当前开发验证版本为 Python 3.14.7。
- 前端开发需要 Node.js `^20.19.0`、`^22.13.0` 或 `>=24.0.0`。
- npm 11.8.0，与前端包声明一致。
- 未来接入真实监控时，需要具有对应接口权限的 Tushare 账号。
- 使用 AI 辅助计划草稿时，可选配置 OpenAI-compatible 地址和 API Key。

实际 Tushare 权限、限流和实时分钟时间戳语义必须通过能力探测及单独授权的真实契约测试确认，不能仅根据配置进行假设。

## 开发环境快速开始

在 PowerShell 中进入 `trade-plan-monitor/` 后执行以下命令。

### 后端

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/generate_frontend_types.py --check
python -m trade_plan_monitor --help
```

### 前端工具链

```powershell
Set-Location web
npm install
npm test -- --run
npm run type-check
npm run build
Set-Location ..
```

前端现已包含完整的 T045～T051 展示。T052 保留 `web/dist/index.html` 作为正常 Vite 输出，并把同一份完整构建复制到被忽略的 Python 包暂存目录供 wheel 纳入。生产资源发现会在整个服务生命周期内使用 `importlib.resources`，要求同时存在 `index.html` 和实际本地资源，绝不从 cwd 或开发源码目录猜测。打包命令继续只允许精确回环；未明确组合业务服务时会诚实保持 `DEGRADED`/只读，既有 API 依赖返回 `SERVICE_UNAVAILABLE`，不会伪造状态。

### 本地配置

```powershell
Copy-Item config\app.example.yaml config\app.yaml
$env:TUSHARE_TOKEN = "replace-with-your-token"
$env:AI_API_KEY = "replace-with-your-api-key"
```

[config/app.example.yaml](config/app.example.yaml) 只保存环境变量引用，不保存密钥值。在配置 AI 草稿能力之前，`AI_API_KEY` 可以不设置。绝不能把密钥值写入 `config/app.yaml`，也不要提交 `.env` 文件、数据库、备份、密钥或 `web/dist` 构建产物。生成的 `openapi.json` 和 `web/src/api/generated.ts` 契约会有意纳入版本控制。

## 命令

| 命令 | 用途 | 可用性 |
|---|---|---|
| `python -m pytest -q` | 运行完整的 1256 项后端门禁 | 可用 |
| `python -m pytest tests/unit/test_package.py -q` | 运行稳定的包级冒烟测试 | 可用 |
| `python -m pytest tests/integration/test_ai_provider_contract.py -q` | 验证 AI 供应商和提取契约 | 可用 |
| `python -m pytest tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q` | 运行确定性判断与回放门禁 | 可用 |
| `python -m pytest tests/integration/test_tushare_contract.py -q` | 验证确定性 Tushare 夹具 | 可用 |
| `python -m ruff check --no-cache src tests` | 运行后端代码检查 | 可用 |
| `python -m compileall -q src/trade_plan_monitor` | 编译检查后端模块 | 可用 |
| `npm test -- --run` | 运行前端单元测试 | 在 `web/` 中可用 |
| `npm run type-check` | 运行 Vue 和 TypeScript 检查 | 在 `web/` 中可用 |
| `npm run build` | 构建前端静态资源 | 在 `web/` 中可用 |
| `python -m trade_plan_monitor validate` | 通过注入的运行时服务分派配置/计划校验 | 服务边界；生产组合在 `T052`～`T054` |
| `python -m trade_plan_monitor monitor --once` | 通过注入的运行时服务分派一次无界面监控周期 | 服务边界；生产组合在 `T052`～`T054` |
| `python -m trade_plan_monitor web --host 127.0.0.1 --port 8765` | 在精确回环地址提供已打包 SPA 和既有 API/WebSocket 路由 | 可用；未注入业务服务时以只读/不可用封闭失败 |
| `python -m trade_plan_monitor replay` | 通过注入的运行时服务分派确定性回放 | 服务边界；生产组合在 `T052`～`T054` |
| `python -m trade_plan_monitor backup` | 通过注入的运行时服务分派已验证备份 | 服务边界；生产组合在 `T052`～`T054` |

真实服务测试或调用必须经过明确授权，且不得在夹具或命令输出中使用生产凭据。

## 项目结构

```text
trade-plan-monitor/
├── config/
│   ├── app.example.yaml
│   └── plans/003043.SZ.sample.yaml
├── src/trade_plan_monitor/
│   ├── ai/             # AI 配置、密钥、供应商协议和 HTTP 适配器
│   ├── decision/       # 纯条件、事件、压力/风险、优先级和哈希
│   ├── domain/         # 计划模型、校验、编解码和稳定哈希
│   ├── market_data/    # 规范化、历史、聚合、指标和收盘核对
│   ├── notifications/  # 确定性提醒、事务 Outbox、渠道与投递
│   ├── state/          # SQLite 模型、迁移、仓储、UoW 和备份
│   ├── web/            # FastAPI 路由与本地 Origin、请求体大小及 SPA 安全
│   ├── cli.py          # 无副作用命令与注入式服务分派
│   └── config.py       # 严格的非敏感应用配置
├── tests/
│   ├── fixtures/
│   ├── integration/
│   ├── replay/
│   └── unit/
├── web/                # Vue/TypeScript 工具链脚手架
├── CAPABILITY-MAP.md
├── SPEC-*.md
├── pyproject.toml
├── README.md
└── README.zh-CN.md
```

本项目保持独立，不得从 `TradingAgents/` 或工作区其他项目导入，也不得修改这些项目。

## 领域约定

- 股票代码采用标准 Tushare 格式，例如 `003043.SZ`。
- 价格按整数“分”持久化，数量按整数“股”持久化；只在输入输出边界转换。
- A 股时间戳必须带时区，并规范化为 `Asia/Shanghai`。
- 买入数量遵守 100 股整手规则；可卖批次按交易日遵守 T+1。
- 价格区间边界只有一个明确归属，避免 64.50、68.80 等边界值触发互相冲突的动作。
- 数据不完整、过期、权限阻断或来源语义未验证时必须安全阻断，不能生成可操作信号。
- 15:00 盘中结果在与官方日线收盘核对前均为临时状态。
- 活动计划版本不可变；修改必须创建新的审核版本。

仓库内的[华亚智能样例计划](config/plans/003043.SZ.sample.yaml)是 `003043.SZ` 的黄金样例。

## 文档

无语言后缀的文档是供智能体和实施流程使用的英文权威版；同名 `.zh-CN.md` 文件是中文审阅副本，两者必须在同一次变更中同步更新。

| 文档 | 英文 | 中文 |
|---|---|---|
| 能力地图 | [CAPABILITY-MAP.md](CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](CAPABILITY-MAP.zh-CN.md) |
| 计划领域 | [SPEC-plan-domain.md](SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](SPEC-plan-domain.zh-CN.md) |
| AI 计划草稿 | [SPEC-ai-plan-drafting.md](SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](SPEC-ai-plan-drafting.zh-CN.md) |
| 行情数据 | [SPEC-market-data.md](SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](SPEC-market-data.zh-CN.md) |
| 策略状态 | [SPEC-strategy-state.md](SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](SPEC-strategy-state.zh-CN.md) |
| 决策引擎 | [SPEC-decision-engine.md](SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](SPEC-decision-engine.zh-CN.md) |
| 通知 Outbox | [SPEC-notification-outbox.md](SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](SPEC-notification-outbox.zh-CN.md) |
| 监控运行时 | [SPEC-monitor-runtime.md](SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](SPEC-monitor-runtime.zh-CN.md) |
| 本地 Web | [SPEC-local-web.md](SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](SPEC-local-web.zh-CN.md) |

工作区级实施计划和执行任务清单维护在这个独立 Git 仓库之外。文档发生冲突时，已批准的模块规格优先。在恢复双语一致性之前，不能继续实施。

## 开发流程

1. 每次只实施一个已批准的工作区任务。
2. 开始前核对任务、模块规格和现有代码。
3. 修改行为之前先添加失败测试。
4. 实现让测试通过所需的最小有界变更。
5. 运行专项测试、全量测试、Ruff、格式、编译、依赖、安全和文档一致性检查。
6. 行为、公共契约、命令或架构发生变化时，同步更新英文和中文文档。

## 金融免责声明

本项目是个人监控与提醒工具，不构成投资建议、券商服务或订单执行系统。行情数据、AI 输出、技术指标和提醒都可能延迟、不完整或不正确。用户必须自行审核每份计划，并对所有交易决策承担全部责任。
