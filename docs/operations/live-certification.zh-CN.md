# Tushare 真实认证

## 目的

`LPC005` 与 `LPC007` 是分别选择的一次性检查。它们直接在当前进程运行，并从本地应用 YAML
读取 Tushare Token。股票与板块指数继续使用独立授权短语、能力集合、时间戳标签和证据 profile；
不再需要 Windows 凭据管理器或子进程。

股票认证覆盖 `trade_cal`、`stk_limit`、`daily`、一次十股票 `rt_min` 批量调用，以及两次
`rt_min_daily` 观测。板块指数认证会对每个已批准的 `MarketIndexCode` 分别检查历史
`idx_mins(freq="5min")`、当日 `rt_idx_min_daily(freq="5MIN")` 与 `index_daily`。“A股实时分钟”
权限不能替代单独命名的“指数实时分钟”权限。

## 所需数据权限

当前实现只调用下列九个 Tushare 接口。2026-09-08 的账号审计使用配置文件中的 Token 与已配置的
`https://api.quicksync.cn` 端点完成，未打印或记录任何凭证值。

| 官方数据/权限中文名 | 使用的接口 | 功能依赖 | 当前账号状态 |
|---|---|---|---|
| 交易日历 | `trade_cal` | 实时监控和回测同步的开市日校验 | `READY` |
| 每日涨跌停价格 | `stk_limit` | 股票涨跌停状态与回测同步 | `READY` |
| A股日线行情 | `daily` | 股票官方日线参考与回测同步 | `READY` |
| 股票历史分钟行情 | `stk_mins` | 回测所需股票历史分钟数据同步 | `READY`（实测返回 241 行） |
| A股实时分钟 | `rt_min`、`rt_min_daily` | 股票实时监控与当日累计数据恢复 | `READY` |
| 指数日线行情 | `index_daily` | 板块指数官方日线参考 | `READY` |
| 指数历史分钟行情 | `idx_mins` | 板块指数监控的历史预热 | `READY`（实测返回 49 行五分钟数据） |
| 指数实时分钟 | `rt_idx_min_daily` | 当日板块指数实时监控 | **`BLOCKED_PERMISSION`** |

因此，当前实现所需但账号唯一缺少的数据权限，是单独售卖的 **“指数实时分钟”**。开通“A股实时分钟”
不会同时获得该权限。`rt_min_daily` 随 A股实时分钟权限一并提供，当前实现不需要为它另购权限。

当前代码没有调用竞价、实时日线、ETF、行业分类实时、Level-2 或逐笔接口，因此现阶段不需要这些权限。

### 测试与运行边界

- 默认自动化测试使用确定性的 fake，并跳过需要显式授权的真实契约用例；因此常规测试不依赖供应商
  权限或网络访问。
- 真实探测已完成但权限不可用时，会把能力写为 `BLOCKED_PERMISSION`，输出
  `CERTIFIED_VISIBLE_BLOCK`，并以退出码 `0` 结束。
- 只有消费该数据的生产功能保持不可执行。因此，缺少“指数实时分钟”只会阻止板块指数实时条件，
  不会阻塞测试套件，也不会阻塞无关的股票或回测功能。

## 配置

复制一次版本化模板，并把凭证直接填写到被忽略的本地文件：

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

```yaml
tushare:
  api_url: https://api.quicksync.cn
  timeout_seconds: 30
  token: replace-with-your-tushare-token

ai:
  api_key: replace-with-your-deepseek-api-key
```

`config/app.yaml` 中的 `tushare.token` 与 `ai.api_key` 是唯一凭证来源。仓库 `.gitignore`
已排除该文件；程序不读取环境变量或独立凭证文件。

## 授权运行

分别执行股票与指数认证：

```powershell
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py stock --authorize LPC005_STOCK_LIVE_CERTIFICATION --config config/app.yaml
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py index --authorize LPC007_BOARD_INDEX_LIVE_CERTIFICATION --config config/app.yaml
```

工作日可用的 `Asia/Shanghai` 窗口如下：

| 数据面 | 上午 | 下午 | 官方收盘后复核 |
|---|---:|---:|---:|
| 股票 | `09:32`～`11:25` | `13:02`～`14:55` | `15:20`～`16:30` |
| 板块指数 | `09:40`～`11:25` | `13:10`～`14:55` | `15:20`～`16:30` |

runner 还要求 `trade_cal` 证明观测日确实开市。本地窗口不合适时，会在读取配置或调用供应商
之前返回 `NOT_RUN_MARKET_WINDOW`。

## 证据与失败语义

认证 profile 会写入被 Git 忽略的 `data/live-certification/` 目录：

- `tushare-stock-live.json`
- `tushare-board-index-live.json`

profile 包含端点 identity、SDK 版本、时间戳、能力状态、时间戳标签语义与 SHA-256 完整性值。
只有 HTTPS 端点完全匹配、未超过七天、哈希完整且数据面 schema 正确的 profile 才会被接受。

认证调用使用单 worker 串行执行，调用起点至少间隔 `1.25` 秒，每次 `15` 秒超时，且认证期间绝不
重试。首个 `RATE_LIMITED` 会停止所有后续供应商调用。只有五项能力全部为 `READY` 且
`SourceTimeLabel` 已验证时，股票 profile 才可执行。指数 readiness 按指数分别保存，一个指数
受阻不会授权或禁用其他指数。

## 权威参考

- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
- [Tushare `stk_limit`](https://tushare.pro/document/2?doc_id=183)
- [Tushare `daily`](https://tushare.pro/document/1?doc_id=27)
- [Tushare `stk_mins`](https://tushare.pro/document/2?doc_id=370)
- [Tushare `rt_min`](https://tushare.pro/document/2?doc_id=374)
- [Tushare `rt_min_daily`](https://tushare.pro/document/2?doc_id=457)
- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `rt_idx_min_daily`](https://tushare.pro/document/2?doc_id=420)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
