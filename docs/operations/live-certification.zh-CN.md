# Tushare 真实认证

## 目的

`LPC005` 与 `LPC007` 是分别选择的一次性检查。它们直接在当前进程运行，并从本地应用 YAML
读取 Tushare Token。股票与板块指数继续使用独立授权短语、能力集合、时间戳标签和证据 profile；
不再需要 Windows 凭据管理器或子进程。

股票认证覆盖 `trade_cal`、`stk_limit`、`daily`、一次十股票 `rt_min` 批量调用，以及两次
`rt_min_daily` 观测。板块指数认证会对四个可见指数 `000001.SH`、`399001.SZ`、
`399006.SZ`、`000688.SH` 以及隐藏的深圳全市场成交额基准 `399107.SZ` 分别检查历史 `idx_mins(freq="5min")`、当日
`rt_idx_min_daily(freq="5MIN")` 与 `index_daily`。已知北证50 identity `899050.BJ` 标为
`DEFERRED`，在北交所股票进入范围前不会发出认证请求。“A股实时分钟”权限不能替代单独命名的
“指数实时分钟”权限。

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
| 指数实时分钟 | `rt_idx_min_daily` | 当日板块指数实时监控与成交额 | 上证指数、深证成指、深证 A 指、创业板指、科创 50 为 `READY`；北证 50 为 `DEFERRED` |

“指数实时分钟”于 2026-09-08 激活并实测后，原有已认证权限已不存在受阻项。2026-09-11
另行授权的续期也已认证成交额基准 `399107.SZ`。仅开通“A股实时分钟”原本不会同时获得该权限。
`rt_min_daily` 随 A股实时分钟权限一并提供，当前实现不需要为它另购权限。
2026-09-08 探针曾观测到北证50实时分钟返回空集；当前产品范围现已整体延期北证50。后续认证
profile 保留其已知 identity 并标为 `DEFERRED`，不会为 `899050.BJ` 调用 `idx_mins`、
`rt_idx_min_daily` 或 `index_daily`。

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
| 股票 | 不可认证 | `13:02`～`14:55` | `15:20`～`16:30` |
| 板块指数 | `09:40`～`11:25` | `13:10`～`14:55` | `15:20`～`16:30` |

runner 还要求 `trade_cal` 证明观测日确实开市。本地窗口不合适时，会在读取配置或调用供应商
之前返回 `NOT_RUN_MARKET_WINDOW`。

股票认证有意不开放上午窗口。以 `09:30` 开始的连续早盘序列无法区分 start-labelled 分钟与独立
`09:30` 开盘快照后跟 end-labelled 分钟。下午窗口可以证明 `11:30` 与 `13:01` 两个边界；若两者
未同时出现，股票标签保持 `UNVERIFIED`。

## 当前续期证据

2026-09-11 在 `10:20:44.522358+08` 观测的板块指数续期认证 `000001.SH`、`399001.SZ`、
`399107.SZ`、`399006.SZ` 和 `000688.SH` 均为 `READY`，`SourceTimeLabel=END`，有效至
`2026-09-18 10:20:44.522358+08`。`899050.BJ` 继续为 `DEFERRED`，且没有发出 provider 请求。

较早的 2026-09-08 股票 `START` 结论是开市过早的不足推断。2026-09-09 的两次 13:10 尝试和
有界重试在旧标签逻辑下正确报告 `current_day_minutes=ERROR/UNVERIFIED`。每份脱敏诊断均有 139 行，
范围 `09:30` 至 `13:18`，包含 `11:30` 且不含 `13:00`。严格修复后的股票运行观测于
`14:48:40.405317+08`，认证五项能力均为 `READY`，`SourceTimeLabel=END`，有效至
`2026-09-16 14:48:40.405317+08`；它证明独立的 `09:30` 快照之后为 end-labeled 分钟。

两项续期认证均使用 `config/app.yaml`。已配置的 `connect_ip` 持续成功，无需临时逐次修改 proxy。
2026-09-09 13:27 的安装式生产尝试因计划收盘窗口不合资格而在联网前拒绝；它不是生产链路验收证据。

## 证据与失败语义

认证 profile 会写入被 Git 忽略的 `data/live-certification/` 目录：

- `tushare-stock-live.json`
- `tushare-board-index-live.json`

profile 包含端点 identity、SDK 版本、时间戳、能力状态、时间戳标签语义与 SHA-256 完整性值。
只有 HTTPS 端点完全匹配、未超过七天、哈希完整且数据面 schema 正确的 profile 才会被接受。

认证调用使用单 worker 串行执行，调用起点至少间隔 `1.25` 秒，每次 `15` 秒超时，且认证期间绝不
重试。首个 `RATE_LIMITED` 会停止所有后续供应商调用。只有五项能力全部为 `READY` 且
`SourceTimeLabel` 已验证时，股票 profile 才可执行。指数 readiness 按指数分别保存，一个指数
受阻不会授权或禁用其他指数。`DEFERRED` 的北证50 identity 不可执行；若被选中，会在进入请求
控制器前失败。

实测 `rt_idx_min_daily(freq="5MIN")` 会返回一条独立的 `09:30` 开盘快照，之后才是以区间结束时刻
标记的五分钟 K 线。认证仅在判断时间标签语义时排除这条开盘快照；运行时归一化原本就会丢弃它，
因为它不是已完成的五分钟区间。

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
