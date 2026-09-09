# 实时生产链路验收

> 本文件是面向用户评审的中文副本；规范英文证据记录为
> `live-production-chain-acceptance.md`。任务 ID、命令、数量、路径、枚举和结果必须保持一致。

## 范围与证据边界

本报告覆盖 `tasks/live-production-todo.md` 中的 `LPC001`～`LPC012`。它只取代临时的
WEBF13 Health fallback 方案；不改写历史 WEBF13 结果，不把 T058 股票证据复用于板块指数认证，
也不复用 T059 发布验收。实现保留 Schema v1 数据、既有哈希、回测存储、DeepSeek 行为和全部
既有本地 Web 路由。

## 环境

- 日期/时区：2026-09-08，Asia/Shanghai。
- 市场窗口事实：星期二 `09:52:53` 的已授权开市观测以 `SourceTimeLabel=START` 认证了股票
  数据面；独立的 `15:16:52` 盘后指数运行选择 `SourceTimeLabel=END`，认证四个指数，并把
  `899050.BJ` 记录为 `ERROR`。2026-09-09，交易范围收窄为上述四个指数；北证50现为
  `DEFERRED`，历史观测保持不变。
- 网络边界：两次明确授权的认证运行和明确授权的 LPC006/LPC008 安装式生产验收调用了 Tushare。
  离线测试与确定性回环浏览器 fixture 仍不请求 Tushare、DeepSeek、券商、Webhook 或其他供应商。
- 凭据边界：选定认证与应用路径只从被忽略的本地 `config/app.yaml` 读取凭据；任何密钥值都
  不会写入命令行、报告、日志、数据库、profile 或候选源码。
- 安装式生产证据：被忽略的报告
  `data/live-certification/production-a88bb95d5a054c46aa62847f894c8421.json` 及其隔离 SQLite
  数据库包含 17:00 自然 scheduler/重启证明。最终冻结行为复跑为
  `data/live-certification/production-e3f317ccb8784753a9914c7cfb08bb8c.json` 及其隔离 SQLite
  数据库。这些工件均不包含密钥。

## 契约与迁移证据

- 迁移 0009 为增量迁移。其聚焦套件通过 `21 tests`；迁移与投影 repository 组合套件通过
  `29 tests`，持久读取通过 `18 tests`，既有 SQLite repository 套件通过 `103 tests`。
- 最终聚焦后端门禁通过：timing/runtime 行为 `188 tests`；`test_live_pipeline_acceptance.py`、
  `test_certified_production_runtime.py` 与 `test_production_certification_gate.py` 三个文件合计在
  `38.27s` 内通过 `22 tests`。这些门禁覆盖迁移保留、原子投影写入/回滚、持久重建、供应商控制、
  不可变 deadline 快照、pending-close owner、supervisor 恢复、生产 composition、类型化 Web API
  和 WebSocket generation fence。
- 冻结功能后端运行在 `181.42s` 内通过 `2307 tests`，并有 `1 skipped`、`1 warning`；其精确范围
  排除未改变的 `tests/integration/test_backtest_acceptance.py` 文件，因为该文件已执行两次，且其中
  包含单独保留的 120 秒容量失败。日志为
  `data/live-certification/frozen-production-functional-pytest.log`。这是功能范围绿色，不代表仓库全量
  门禁绿色。
- 2026-09-09 的北证50延期修订在 `41.00s` 内通过 `56 tests`，覆盖认证 profile 与 launcher、
  Tushare 指数 provider/探针、生产 composition、认证过期/篡改闸门、共享 snapshot 和 market-index
  runtime。这些测试不调用外部 provider，并证明 `899050.BJ` 不能进入请求控制器。
- 修订后的功能后端回归在同一离线范围内于 `213.43s` 通过 `2309 tests`，并有 `1 skipped`、
  `1 warning`；该回归不调用外部 provider。
- OpenAPI SHA-256 为
  `2b232e1a9237aa88a2de7c3d1ec3fcc692b198cfddeabc41fa88b7d67cdb3a53`，生成的 TypeScript
  保持逐字节 current。
- 规范、计划、任务清单和本报告的中英文结构及稳定 literal 集合一致；唯一预期的 literal 集合
  差异是对应副本文件名。
- 历史独立审查使用此前用户要求的模型矩阵。P2-A（`gpt-5.6-sol/ultra`）对迁移/持久层审查无发现；
  P2-B（`gpt-5.6-sol/max`）发现四个 P1 与一个 P2 runtime 问题，均已修复并补回归；
  P2-C（`gpt-5.6-terra/high`）发现一个 P1 与两个 P2 Web/证据缺口，均已修复。最终 P3
  （`gpt-5.6-sol/ultra`）发现一个 P1 与五个 P2 边界/测试 harness 问题；同一审查者逐项复核
  后返回 `PASS`，没有剩余 P0/P1/P2。本次验收更新中，pipeline/timing 审查使用
  `gpt-5.6-sol/high`，文档审查使用 `gpt-5.6-sol/medium`，网络审查 agent 继承其获分配模型；
  这些本次分配不等同于历史矩阵。

## 运行时与供应商证据

- 先前记录的 provider/认证组件套件通过 `228 tests`。仅对固定 `1MIN` 请求兼容
  `rt_min_daily.freq` 不回显；若明确返回错误频率，仍会拒绝。这是组件证据，与真实认证和
  安装式生产链路验收相互独立。
- 2026-09-08 `09:52:53` 股票 profile 将 `realtime_minutes`、`current_day_minutes`、
  `trading_calendar`、`daily_limits` 与 `daily_bars` 全部记录为 `READY`，且
  `SourceTimeLabel=START`。该 profile 有效至 2026-09-15 09:52:53 Asia/Shanghai，LPC005
  因此关闭。
- Tushare 文档与真实观测证明 `idx_mins` 属于历史数据并在盘后更新；它对上一交易日返回
  `49` 根五分钟线，对当日返回 `0` 行。因此修正后的指数契约会组合 `idx_mins`、
  `rt_idx_min_daily` 与 `index_daily`，而不是复用股票 `rt_min` endpoint。
- 独立的 2026-09-08 `15:16:52` 指数 profile 选择 `SourceTimeLabel=END`，有效至
  2026-09-15 15:16:52 Asia/Shanghai。`000001.SH`、`399001.SZ`、`399006.SZ` 与
  `000688.SH` 为 `READY`；`899050.BJ` 为 `ERROR`。该结果取代早先的全量
  `BLOCKED_PERMISSION` 结论。当前交易范围由这四个已就绪指数构成。北证50在北交所股票进入
  范围前延期；后续认证写入 `DEFERRED`，且不为 `899050.BJ` 请求 `idx_mins`、
  `rt_idx_min_daily` 或 `index_daily`。无需改写历史 profile，LPC007 已按当前范围完成。
- Runtime 测试覆盖每个 deadline 一次不可变的最多十股票批次、判断零重取、分别完整的准入/
  供应商超时、排队请求 `CLOSED` 唤醒、stop 立即停止准入、最终激活 revision fence、持久
  official-close owner，以及有界的新 runtime supervisor。
- 安装式生产验收于 `16:54:10.565727` 启动，并在 scheduler 于 `17:00:00.011473` 自然启动
  `17:00:00` deadline 前报告 `waitingForScheduledClose`。它消费五项能力均为 `READY` 的股票
  profile，保留历史 `899050.BJ=ERROR` 证据，暴露 `LIVE` 上证/深证指数快照，并提交两项官方收盘判断。
  重放这些已提交 identity 时返回零结果且产生零 provider 请求。Dashboard sequence `11` 和已提交
  判断在重启进入 `RUNNING` 后完整保留；运行于 `17:00:18.114695` 结束。
- 在每个到期计划批次内，依赖计划对每个必需指数 endpoint 共享一个 revision-aware 快照。15:00
  盘中与 `OFFICIAL_CLOSE` 阶段属于不同判断 kind，因此两阶段验收会按每个 kind 分别执行一次指数
  endpoint 调用，而不是跨两个 kind 只调用一次。启动恢复也按 pending 交易日期分组 pending close，
  使同一板块股票共享该批次快照。
- 冻结回归覆盖 provider revision 序列 `r1` → `r2` → `r1`：既有 revision 的规范等价内容会复用
  其精确已持久化 snapshot/hash，每项计划结果均绑定该持久化 identity；同 revision 的不同规范内容
  会封闭失败。测试没有放宽任何 snapshot 字段、hash 公式、唯一约束或失败指数隔离规则。指数成功
  与错误路径也共同遵守获取后的整秒边界和未来时间拒绝。
- 生产运行记录的最小物理请求启动间隔为 `1.2524307999992743` 秒，重启前插桩调用数为：
  `trade_cal=2`、`stk_limit=1`、`daily=4`、`rt_min_daily=2`、`idx_mins=4`、
  `rt_idx_min_daily=4`、`index_daily=4`、`rt_min=1`。这些安装式 composition 事实与组件及
  真实认证证据共同关闭 LPC006 与 LPC008。
- 最终冻结行为人工复跑于 `17:37:38.919297` 启动、`17:38:16.077702` 结束；启动与重启均为
  `RUNNING`，两项官方收盘均提交，重复运行返回零结果且产生零新请求，并保留 Dashboard sequence
  `11`。其最小物理请求启动间隔为 `1.2519141000084346` 秒；endpoint 计数与上证/深证 `LIVE`
  快照均和 17:00 运行一致。它仍如实记录盘中 `GAPPED` 与
  `freshIntradayCertifiedByThisRun=false`。
- 同一次运行不认证新鲜盘中完整性：`freshIntradayCertifiedByThisRun=false`。盘后盘中结果为空且为
  `GAPPED`，目标为 15:00，返回的最新分钟为 14:59。对生产数据库的只读检查发现两只股票各有
  `239` 分钟，且二者均缺少 13:01 分钟。该限制被如实记录，没有升级为通过。

## Web 与浏览器证据

- `scripts/generate_frontend_types.py --check` 报告 OpenAPI 快照与生成的前端类型为最新。
- `vue-tsc --noEmit -p tsconfig.json` 通过。
- Vitest 在 `6.28s` 内通过 `40 files / 599 tests`。
- Vite 生产构建通过。`PriceChart` 是独立的 `95.39 kB` JavaScript chunk，已注册的
  Canvas renderer 是独立的 `475.20 kB` 异步 chunk；Dashboard chunk 不包含这两个资源，
  非图表浏览器用例也不请求它们。
- Playwright 使用一个 worker，在 `channel: "chrome"` 的 `chrome` 项目上于 `34.3s` 内通过 `22 tests`。
  相关 fixture 逐例断言浏览器控制台 error 为零、浏览器控制台 warning 为零且
  `requestfailed` 为零；类型化 `UNAVAILABLE` 不打开 WebSocket。安装式生产用例启动精确的
  `.venv` 控制台可执行文件，验证打包 SPA 与类型化空库响应，停止后在同一临时数据库上重启，
  再次验证相同的诚实状态。Node runner 打印的 `NO_COLOR`/`FORCE_COLOR` 警告不是浏览器
  控制台输出。
- 安装式旅程使用动态保留的回环端口，把 readiness 绑定到子 launcher 与解析出的 Uvicorn
  PID，直至两个 identity 都退出才释放句柄，并把 `taskkill.exe`/`icacls.exe` 调用限制为三秒。
  契约错误浏览器 fake 向应用交付可见的 HTTP `503`/`409` 响应，不再把它们伪装成
  `INVALID_RESPONSE`。

## 验证命令与结果

已完成的 live-chain 与 Web 命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contract/test_tushare_live.py -q -m "not live"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_live_pipeline_acceptance.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py -q
.\.venv\Scripts\python.exe scripts\verify_live_production.py --authorize LPC006_LPC008_PRODUCTION_ACCEPTANCE --wait-for-scheduled-close
.\.venv\Scripts\python.exe scripts\verify_live_production.py --authorize LPC006_LPC008_PRODUCTION_ACCEPTANCE --config config/app.yaml
.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_tushare_market_index.py tests/integration/test_runtime_lifecycle.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_monitor_production_composition.py tests/integration/test_plan_production_composition.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_sqlite_repositories.py tests/integration/test_web_api.py tests/integration/test_websocket.py -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts\generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

以下首次仓库级命令并非绿色：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live"
```

该命令在 `1614.22s` 内得到 `5 failed, 2286 passed, 1 skipped`。其中一项是既有
`test_ten_symbol_252_day_replays_meet_capacity_budgets` watchdog，对 `000001.SZ` 在 `120.066243s` 触发。
其余四项属于本次变更回归：两个旧 Web fixture 缺少 `runtimeGeneration`、一个 timing 测试引用
旧 snapshot 名称、一个 replay 断言未包含新增的持久 data-health 事件。这四项均已修复，聚焦回归
通过。未改变的 252 日容量失败继续保留，且阈值没有放宽。中间复跑排除了该单项已测用例；整个未改
`test_backtest_acceptance.py` 文件已执行两次后，最终冻结功能复跑将其整体排除。因此 LPC012 仍保持
未完成。

一次中间 filtered 复跑使用以下显式 filter，在 `1221.40s` 内得到
`2306 passed, 1 failed, 1 skipped, 1 deselected`。malicious-decimal helper 因未抛出预期异常而失败；
后续聚焦单跑通过，但在冻结代码顺序复跑前不宣称原因。本次中间复跑不是绿色，也不是代码冻结后的
最终结果：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live" -k "not test_ten_symbol_252_day_replays_meet_capacity_budgets"
```

最终冻结功能运行使用以下更宽的显式文件排除，因为整个未改变容量套件此前已经执行两次：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q --tb=short -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py
```

最新结果：`2309 passed, 1 skipped, 1 warning in 213.43s`。保留的全范围容量失败仍使 LPC012 保持未完成。

## 遗留风险与延后实时证据

- 股票实时分钟时间戳语义已认证为 `START`，有效至 2026-09-15 09:52:53 Asia/Shanghai。
- 板块指数时间戳语义已认证为 `END`，有效至 2026-09-15 15:16:52 Asia/Shanghai。只有
  `000001.SH`、`399001.SZ`、`399006.SZ` 与 `000688.SH` 位于当前范围且为 `READY`。历史文件
  保留 `899050.BJ=ERROR`；当前策略把北证50视为 `DEFERRED`，绝不视为已认证。
- 已实现直接 `tushare.token` 与 `ai.api_key` 配置，并将其作为唯一凭证来源。根据用户针对个人
  工具的明确策略，已移除 Windows 凭据管理器、环境/文件引用与仅子进程认证。已配置 Token
  仅由明确授权的认证与 LPC006/LPC008 生产验收调用使用。
- 带哈希保护的股票与板块指数 profile 现在会在七天后过期，并在篡改、端点不匹配、schema
  不匹配或跨数据面复用时安全阻断。真实股票探针与逐指数探针已经实现，包括首个 429 后全局停止；
  股票 profile 全部就绪；指数 profile 如实保留历史 `899050.BJ` 错误和其他四个就绪指数。新探针
  会跳过北证50并记录 `DEFERRED`。
- CPython 无法强制终止任意不合作的同步 provider callable。真实 Tushare transport 已配置自身
  15 秒超时，shutdown 有界且可见。该主机 WinINET 使用 `127.0.0.1:7897`，TUN fake DNS
  `198.18.0.2` 把 `api.quicksync.cn` 解析为 `198.18.0.42`；默认 Requests、`trust_env=False` 与
  `NO_PROXY=*` 仍产生 `TLSV1_ALERT_INTERNAL_ERROR`。经授权连接 `111.229.23.244` 时保留原始
  Host/SNI 与 CA 校验并成功；`101.35.23.219` 失败，错误 hostname certificate 负向检查也被拒绝。
  被忽略的本地设置 `tushare.connect_ip=111.229.23.244` 在无需逐次修改 proxy 环境的情况下支撑两次
  生产验收通过。该公网地址属于运维设置，源码不硬编码，并继续受真实 endpoint certificate 约束。
- 仓库级离线闸门仍被上述无关的 252 日回测性能预算阻断；live-chain 聚焦、前端和浏览器门禁均为绿色。

## 验收状态

`LIVE_CHAIN_PRODUCTION_ACCEPTED_BSE_DEFERRED`——LPC005～LPC008 已按当前交易范围通过独立真实
认证及安装式生产证据。独立指数运行认证当前范围内全部四个指数和 `SourceTimeLabel=END`。北证50
保留为已知 identity，但明确标为 `DEFERRED`；在北交所股票进入范围前既不认证，也不请求。LPC012
仍因未改变的仓库级 252 日容量门保持未完成。不得仅凭组件测试或生成 profile 声称完成。
