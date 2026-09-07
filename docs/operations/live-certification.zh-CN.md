# Tushare 真实认证

## 目的

`LPC005` 与 `LPC007` 是分别选择的一次性检查。它们直接在当前进程运行，并从本地应用 YAML
读取 Tushare Token。股票与板块指数继续使用独立授权短语、能力集合、时间戳标签和证据 profile；
不再需要 Windows 凭据管理器或子进程。

股票认证覆盖 `trade_cal`、`stk_limit`、`daily`、一次十股票 `rt_min` 批量调用，以及两次
`rt_min_daily` 观测。板块指数认证会对每个已批准的 `MarketIndexCode` 分别检查
`idx_mins(freq="5min")` 与 `index_daily`。

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

直接配置的 `tushare.token` 与 `ai.api_key` 优先。迁移期间仍可读取原有 `token_ref` 和
`api_key_ref` 结构，因此现有个人配置不会立即失效。仓库 `.gitignore` 已排除
`config/app.yaml`。

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

- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
