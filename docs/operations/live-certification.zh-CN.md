# Tushare 真实认证

## 目的

`LPC005` 与 `LPC007` 是分别授权的一次性检查。父进程不接触密钥：它只接收 Windows
凭据管理器的目标名称，并使用白名单环境启动子进程。只有该子进程会读取凭据，临时将其暴露为
`TUSHARE_TOKEN`，仅运行一个选定数据面，随后恢复环境并清零可变凭据缓冲区。

股票与板块指数运行绝不共用时间戳证据。股票认证覆盖 `trade_cal`、`stk_limit`、`daily`、
一次十股票 `rt_min` 批量调用，以及两次 `rt_min_daily` 观测。板块指数认证会对每个已批准的
`MarketIndexCode` 分别检查 `idx_mins(freq="5min")` 与 `index_daily`。

## 一次性凭据配置

请在私密的本机终端执行以下命令。输入提示不会回显 Token。绝不要把 Token 放进命令行、聊天、
源码树、`.env`、报告或截图。

```powershell
.\.venv\Scripts\python.exe scripts\set_tushare_live_credential.py
```

默认 Windows 凭据管理器目标为 `trade-plan-monitor/tushare-live`。配置脚本会校验可打印 ASCII，
通过 `CredWriteW` 保存凭据，并清零它的可变副本。真实子进程通过 `CredReadW` 读取，并始终使用
`CredFree` 释放原生缓冲区。

## 授权运行

分别执行股票与指数认证：

```powershell
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py stock --authorize LPC005_STOCK_LIVE_CERTIFICATION
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py index --authorize LPC007_BOARD_INDEX_LIVE_CERTIFICATION
```

工作日可用的 `Asia/Shanghai` 窗口如下：

| 数据面 | 上午 | 下午 | 官方收盘后复核 |
|---|---:|---:|---:|
| 股票 | `09:32`～`11:25` | `13:02`～`14:55` | `15:20`～`16:30` |
| 板块指数 | `09:40`～`11:25` | `13:10`～`14:55` | `15:20`～`16:30` |

子进程还要求 `trade_cal` 证明观测日确实开市。本地窗口不合适时，会在创建子进程或调用供应商
之前返回 `NOT_RUN_MARKET_WINDOW`。

## 证据与失败语义

脱敏、带哈希保护的 profile 会写入被 Git 忽略的 `data/live-certification/` 目录：

- `tushare-stock-live.json`
- `tushare-board-index-live.json`

profile 只包含端点 identity、SDK 版本、时间戳、能力状态、时间戳标签语义与 SHA-256 完整性值；
不包含 Token、授权响应、原始供应商数据帧、请求头或供应商异常文本。只有 HTTPS 端点完全匹配、
未超过七天、哈希完整且数据面 schema 正确的 profile 才会被接受。

认证调用使用单 worker 串行执行，调用起点至少间隔 `1.25` 秒，每次 `15` 秒超时，且认证期间绝不
重试。首个 `RATE_LIMITED` 会停止所有后续供应商调用。权限失败保留为 `BLOCKED_PERMISSION`；
其他失败会收敛为稳定且不含密钥的状态。只有五项能力全部为 `READY` 且 `SourceTimeLabel` 已验证时，
股票 profile 才可执行。指数 readiness 按指数分别保存，一个指数受阻不会授权或禁用其他指数。

## 权威参考

- [Microsoft `CredReadW`](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw)
- [Microsoft `CredWriteW`](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credwritew)
- [Microsoft 密码处理指南](https://learn.microsoft.com/windows/win32/secbp/handling-passwords)
- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
