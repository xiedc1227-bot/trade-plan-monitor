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
- 市场窗口事实：星期二 `09:52` 的已授权开市观测认证了股票数据面；`10:04` 的修正后指数
  观测记录了指数实时权限阻断。
- 网络边界：两次明确授权的认证运行调用了 Tushare。离线测试与确定性回环浏览器 fixture
  仍不请求 Tushare、DeepSeek、券商、Webhook 或其他供应商。
- 凭据边界：选定认证与应用路径只从被忽略的本地 `config/app.yaml` 读取凭据；任何密钥值都
  不会写入命令行、报告、日志、数据库、profile 或候选源码。

## 契约与迁移证据

- 迁移 0009 为增量迁移。其聚焦套件通过 `21 tests`；迁移与投影 repository 组合套件通过
  `29 tests`，持久读取通过 `18 tests`，既有 SQLite repository 套件通过 `103 tests`。
- 当前代码的 live-chain 后端合并命令通过 `558 tests`，覆盖迁移保留、原子投影写入/回滚、
  持久重建、供应商控制、不可变 deadline 快照、pending-close owner、supervisor 恢复、生产
  composition、类型化 Web API 和 WebSocket generation fence。
- OpenAPI SHA-256 为
  `2b232e1a9237aa88a2de7c3d1ec3fcc692b198cfddeabc41fa88b7d67cdb3a53`，生成的 TypeScript
  保持逐字节 current。
- 规范、计划、任务清单和本报告的中英文结构及稳定 literal 集合一致；唯一预期的 literal 集合
  差异是对应副本文件名。
- 独立审查使用用户要求的模型矩阵。P2-A（`gpt-5.6-sol/ultra`）对迁移/持久层审查无发现；
  P2-B（`gpt-5.6-sol/max`）发现四个 P1 与一个 P2 runtime 问题，均已修复并补回归；
  P2-C（`gpt-5.6-terra/high`）发现一个 P1 与两个 P2 Web/证据缺口，均已修复。最终 P3
  （`gpt-5.6-sol/ultra`）发现一个 P1 与五个 P2 边界/测试 harness 问题；同一审查者逐项复核
  后返回 `PASS`，没有剩余 P0/P1/P2。

## 运行时与供应商证据

- 修正后的 provider/认证聚焦套件通过 `228 tests`。仅对固定 `1MIN` 请求兼容
  `rt_min_daily.freq` 不回显；若明确返回错误频率，仍会拒绝。
- 2026-09-08 `09:52` 股票 profile 将 `realtime_minutes`、`current_day_minutes`、
  `trading_calendar`、`daily_limits` 与 `daily_bars` 全部记录为 `READY`，且
  `SourceTimeLabel=START`。LPC005 因此关闭。
- Tushare 文档与真实观测证明 `idx_mins` 属于历史数据并在盘后更新；它对上一交易日返回
  `49` 根五分钟线，对当日返回 `0` 行。因此修正后的指数契约会组合 `idx_mins`、
  `rt_idx_min_daily` 与 `index_daily`，而不是复用股票 `rt_min` endpoint。
- 2026-09-08 `10:04` 指数 profile 将五个已批准指数全部记录为 `BLOCKED_PERMISSION`，
  阻断 endpoint 为 `rt_idx_min_daily`，且 `SourceTimeLabel=UNVERIFIED`。LPC007 仍需 Tushare
  中单独命名的“指数实时分钟”权限。
- Runtime 测试覆盖每个 deadline 一次不可变的最多十股票批次、判断零重取、分别完整的准入/
  供应商超时、排队请求 `CLOSED` 唤醒、stop 立即停止准入、最终激活 revision fence、持久
  official-close owner，以及有界的新 runtime supervisor。
- 生产继续保持 `DEGRADED` 且不可执行，因为安装式 composition 仍使用硬编码的
  `UNVERIFIED` provider 状态，尚未消费现已就绪的股票 profile。板块指数能力继续作为独立的
  未满足闸门。

## Web 与浏览器证据

- `scripts/generate_frontend_types.py --check` 报告 OpenAPI 快照与生成的前端类型为最新。
- `vue-tsc --noEmit -p tsconfig.json` 通过。
- Vitest 通过 `40 files / 592 tests`。
- Vite 生产构建通过。`PriceChart` 是独立的 `95.39 kB` JavaScript chunk，已注册的
  Canvas renderer 是独立的 `475.20 kB` 异步 chunk；Dashboard chunk 不包含这两个资源，
  非图表浏览器用例也不请求它们。
- Playwright 使用一个 worker，在 `channel: "chrome"` 的 `chrome` 项目上通过 `22 tests`。
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
.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_tushare_market_index.py tests/integration/test_runtime_lifecycle.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_monitor_production_composition.py tests/integration/test_plan_production_composition.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_sqlite_repositories.py tests/integration/test_web_api.py tests/integration/test_websocket.py -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe scripts\generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

以下仓库级命令并非绿色：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live" -x
```

它先通过 `1213 tests`，随后既有
`test_ten_symbol_252_day_replays_meet_capacity_budgets` watchdog 在 `120.076626s` 取消
`688981.SH`。在无任何并发检查的资源隔离复跑中，相同未修改回测性能闸门再次失败：
`003043.SZ` 达到 `120.074936s`。本工作没有修改回测源码或阈值，因此如实报告该失败，
不隐藏、不跳过、也不放宽。

## 遗留风险与延后实时证据

- 股票实时分钟时间戳语义已认证为 `START`，有效至 2026-09-15 09:52 Asia/Shanghai。
- 板块指数实时能力和时间戳证据需要 Tushare 单独的“指数实时分钟”权限；A股实时分钟与
  指数历史分钟均不能满足该闸门。
- 已实现直接 `tushare.token` 与 `ai.api_key` 配置，并将其作为唯一凭证来源。根据用户针对个人
  工具的明确策略，已移除 Windows 凭据管理器、环境/文件引用与仅子进程认证。已配置 Token
  仅由明确授权的认证调用使用。
- 带哈希保护的股票与板块指数 profile 现在会在七天后过期，并在篡改、端点不匹配、schema
  不匹配或跨数据面复用时安全阻断。真实股票探针与逐指数探针已经实现，包括首个 429 后全局停止；
  股票 profile 已就绪；指数 profile 会如实保留权限阻断。
- CPython 无法强制终止任意不合作的同步 provider callable。真实 Tushare transport 已配置自身
  15 秒超时，shutdown 有界且可见。当前主机代理会把 `api.quicksync.cn` 映射到拦截地址，
  因此已授权证据运行使用了进程内直连路由；无人值守生产使用前仍需解决该主机网络问题。
- 仓库级离线闸门仍被上述无关的 252 日回测性能预算阻断；live-chain 聚焦的 `558` 个测试为绿色。

## 验收状态

`LIVE_CHAIN_STOCK_CERTIFIED_INDEX_PERMISSION_BLOCKED`——LPC005 已通过真实开市证据。LPC006
仍未绑定到生产，LPC007 受独立指数实时权限阻断，LPC008 继续依赖 LPC007 与生产绑定。
LPC006～LPC008 与 LPC012 仍保持未完成；生产安全保持不可执行和 `DEGRADED`。
