# 交易计划监控系统（Trade Plan Monitor）

Trade Plan Monitor 是一款本地优先、AI 辅助、面向确定性 A 股交易计划的监控工具。它把经审核的计划和规范化行情转化为可解释提醒，不会自动下单。

[English](README.md)

## 产品状态

`T001`～`T053` 已完成。安装式命令可在精确回环地址提供构建后的 Vue SPA、REST API 和 WebSocket 路由。在应用服务组合接通之前，该安装入口会有意以只读 `DEGRADED` 模式启动：界面可以访问，但业务 API 依赖会返回 `SERVICE_UNAVAILABLE`，不会虚构实时状态。

确定性测试套件不调用真实 Tushare、AI、Webhook 或其他外部服务。真实供应商检查仍是需要单独授权的操作。

## 安全边界

- 本系统是监控和提醒软件，不是券商、订单路由或投资顾问。每条可操作提醒都包含“仅提醒，不会自动下单”。
- 计划必须类型化、经审核、版本化，并在激活后保持不可变。AI 输出在确定性校验和用户审核通过前始终是不可信草稿。
- 价格按整数“分”保存，数量按整数“股”保存，A 股时间戳必须是带 `Asia/Shanghai` 时区的值。
- 行情缺失、过期、无权限或来源语义未验证时安全阻断。
- 密钥只能是环境变量引用或只写密钥存储材料，不能成为 YAML 值、数据库列、API 响应、日志或导出内容。
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

YAML 只保存非密钥供应商设置和环境变量名称。纳入版本控制的示例选择已验证的 Tushare 兼容端点 `https://api.quicksync.cn`；本地副本 `config/app.yaml` 会被 Git 忽略。仅离线启动界面时，可以不设置这两个变量。在另行授权的真实供应商运行之前，在当前进程或操作系统密钥管理器中设置占位值：

```powershell
$env:TUSHARE_TOKEN = "replace-with-your-tushare-token"
$env:AI_API_KEY = "replace-with-your-openai-compatible-api-key"
```

[.env.example](.env.example) 是纳入版本控制的名称/模板参考；应用**不会**自动加载 `.env` 文件。绝不能把 Token 或 API Key 写入 `config/app.yaml`，也不要提交 `config/app.yaml`、`.env`、数据库、备份、密钥或构建输出。

当前只读打包 fallback 会接受配置路径，但不会解析这些供应商引用。未来注入的应用组合必须加载严格 YAML 后才能使用它们；`DEGRADED` 启动绝不证明供应商配置有效或已启用。

### 4. 启动已打包本地 Web 界面

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

在同一台计算机上打开 `http://127.0.0.1:8765/`。使用 `Ctrl+C` 停止前台进程。在当前组合检查点，应看到上文说明的只读 `DEGRADED` 状态。

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

## 命令

除非命令本身切换目录，后端命令从 `trade-plan-monitor/` 运行，前端命令从 `web/` 运行。

| 命令 | 用途 | 当前可用性 |
|---|---|---|
| `trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765` | 提供已打包 SPA、API 和 WebSocket 路由 | 可用；完成组合前业务服务保持只读/不可用 |
| `python -m trade_plan_monitor --help` | 显示稳定的安装式命令面 | 可用 |
| `python -m pytest -q` | 运行完整后端测试 | 可用；离线 |
| `python -m ruff check --no-cache src tests` | 运行后端代码检查 | 可用；离线 |
| `python -m compileall -q src/trade_plan_monitor` | 编译检查后端模块 | 可用；离线 |
| `python scripts/generate_frontend_types.py --check` | 检测 OpenAPI/生成 TypeScript 漂移 | 可用；离线 |
| `npm test -- --run` | 运行前端单元测试 | 在 `web/` 中可用；离线 |
| `npm run type-check` | 检查 Vue 和 TypeScript | 在 `web/` 中可用；离线 |
| `npm run build` | 构建并暂存生产 SPA 资源 | 在 `web/` 中可用；安装依赖后离线 |
| `python -m trade_plan_monitor validate` | 分派配置/计划校验 | 注入式边界；安装式 fallback 尚未接通 |
| `python -m trade_plan_monitor monitor --once` | 分派一次无界面监控周期 | 注入式边界；安装式 fallback 尚未接通 |
| `python -m trade_plan_monitor replay` | 分派确定性回放 | 注入式边界；安装式 fallback 尚未接通 |
| `python -m trade_plan_monitor backup` | 分派已验证在线备份 | 注入式边界；安装式 fallback 尚未接通 |

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

2026-08-25 经明确授权的检查已通过 HTTPS 和官方 SDK 验证 `stk_mins`：`600000.SH` 在 2026-08-24 的一个完整交易日返回 241 条一分钟记录，覆盖 09:30:00 至 15:00:00，包含预期的 8 个字段，且不存在重复行、必要字段空值、非法 OHLC、负成交量或错误股票代码行。该端点因此可以作为未来历史分钟回测数据源；它不能替代另行要求的实时 `rt_min` 和 `rt_min_daily` 能力，当前打包只读 fallback 也仍未组合回测运行时。

只在另行授权的真实能力探测中设置 `TUSHARE_TOKEN`。能力、账号权限、限流和分钟标签语义均独立发现；配置不代表能力可用。必要能力被拒绝或未验证时会阻断可操作输出。默认契约测试使用确定性假 DataFrame：

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## AI 密钥

仅在启用 AI 辅助草稿时才需要 `AI_API_KEY`。提交的 YAML 只保存环境变量名称。运行时供应商配置保存非密钥引用、模型、有界超时/重试/Token 限制和 HTTPS 基础 URL（仅显式回环主机允许明文 HTTP）。

API Key 材料通过密钥边界只写，公共契约无法返回。系统拒绝重定向、URL 内嵌账号密码、带查询参数的基础 URL、执行原始模型内容以及包含密钥的校验错误。AI 输出绝不会直接激活。

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
| 界面显示 `DEGRADED` 或 API 返回 `SERVICE_UNAVAILABLE` | 当前打包只读 fallback 的预期行为，不代表真实监控正在运行。 |
| `runtime service factory is not configured` | 在应用服务组合接通前调用了 `validate`、`monitor`、`replay` 或 `backup`。 |
| 监听主机校验失败 | 使用精确字面量 `127.0.0.1`；系统有意拒绝 `localhost`、`::1`、`0.0.0.0`、主机名和局域网地址。 |
| 8765 端口占用 | 停止另一个本地进程，或选择 1～65535 中未占用的其他端口，同时保持主机为 `127.0.0.1`。 |
| YAML 报告未知字段 | 重新从 `config/app.example.yaml` 开始；模式会有意拒绝不支持的节和明文密钥。 |
| Tushare 能力为 `DENIED`/`UNVERIFIED` | 检查进程环境和账号权限，然后只运行获批的真实探测；绝不能绕过阻断。 |
| AI 返回配置/鉴权错误 | 将密钥保留在 `AI_API_KEY`，检查非密钥供应商 URL/模型，不要把凭据放进 URL 或 YAML。 |
| 前端生成类型漂移 | 运行 `python scripts/generate_frontend_types.py --check`；只在获批 API 契约变更中重新生成。 |

## 禁止端口转发

应用只能在运行进程的同一台桌面计算机上使用。**不要**绑定 `0.0.0.0`、局域网地址、`localhost` 或 `::1`；不要使用 SSH/IDE 端口转发、反向代理、隧道、容器端口发布、主机别名或路由器暴露。精确 Origin 防护和回环监听是安全边界，不是部署上的不便。

由于系统没有登录或远程用户授权，转发 `127.0.0.1:8765` 会在支持的威胁模型之外暴露敏感计划、持仓、健康数据和变更端点。远程访问需要另行设计并审查鉴权和部署模型。

## 项目结构

```text
trade-plan-monitor/
├── config/                   # 非密钥应用引用和样例计划
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
├── SPEC-*.md                 # 英文权威模块契约
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

无语言后缀的文档是供智能体和实施流程使用的英文权威输入；同名 `.zh-CN.md` 文件是中文审阅副本，必须在同一次变更中保持语义等价。

| 契约 | 英文 | 中文 |
|---|---|---|
| 能力地图 | [CAPABILITY-MAP.md](CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](CAPABILITY-MAP.zh-CN.md) |
| 计划领域 | [SPEC-plan-domain.md](SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](SPEC-plan-domain.zh-CN.md) |
| AI 草稿 | [SPEC-ai-plan-drafting.md](SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](SPEC-ai-plan-drafting.zh-CN.md) |
| 行情数据 | [SPEC-market-data.md](SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](SPEC-market-data.zh-CN.md) |
| 策略状态 | [SPEC-strategy-state.md](SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](SPEC-strategy-state.zh-CN.md) |
| 决策引擎 | [SPEC-decision-engine.md](SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](SPEC-decision-engine.zh-CN.md) |
| 通知 Outbox | [SPEC-notification-outbox.md](SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](SPEC-notification-outbox.zh-CN.md) |
| 监控运行时 | [SPEC-monitor-runtime.md](SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](SPEC-monitor-runtime.zh-CN.md) |
| 本地 Web | [SPEC-local-web.md](SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](SPEC-local-web.zh-CN.md) |

## 开发流程

1. 每次只实施一个获批的工作区任务。
2. 修改前阅读任务、模块契约和当前代码。
3. 行为或文档修改前先增加失败测试或契约检查。
4. 运行受影响测试、全量回归、Ruff、格式、编译、依赖、安全和双语一致性门禁。
5. 行为、命令、架构或公共契约变化时，同步更新英文和中文文档。

## 金融免责声明

本项目是个人监控与提醒工具，不构成投资建议、券商服务或订单执行系统。行情数据、AI 输出、技术指标和提醒都可能延迟、不完整或不正确。用户必须自行审核每份计划，并对所有交易决策承担全部责任。
