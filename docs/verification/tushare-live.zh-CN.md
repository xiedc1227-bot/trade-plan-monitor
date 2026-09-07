# Tushare 真实契约验收

> 历史 T058 证据。下文记录的一次性子进程凭证边界已于 2026-09-07 被“在被忽略的本地
> `config/app.yaml` 中直接配置凭证”取代。

状态：通过——显式阻断分支已验收；五项能力均因脱敏 provider 代码 `TRANSIENT` 处于 `ERROR`

- 证据日期：2026-08-31 11:24:21～11:24:26 `+08:00`（`Asia/Shanghai`）。
- 证据基线：`main` 的 `eee65fd9ede37cee229c0147ba2ddb55a5f311d5`；本报告描述基于该基线派生、尚未提交的 T058 候选变更。
- 边界：经明确授权，通过 `api.quicksync.cn` 对 `rt_min`、`rt_min_daily`、`trade_cal`、`stk_limit` 和 `daily` 执行一次 T058/P18 真实探测。没有调用券商、通知、AI provider、历史同步或未批准的 provider 接口。
- 决策：不能根据本次运行把任何能力标记为 `READY`。生产分类把每项 provider 失败归约为安全代码 `TRANSIENT`，并映射为能力状态 `ERROR`。应用已被证明保持降级、只读和显式阻断；时间戳状态保持 `SourceTimeLabel.UNVERIFIED`，且不宣称 `SourceTimeLabel.START` 或 `SourceTimeLabel.END`。

## 参考环境与凭据处理

| 项目 | 观测事实 |
|---|---|
| 主机 | Windows 11 `10.0.26200`，本地单用户进程 |
| Python / pandas / Tushare SDK | CPython 3.14.7 / pandas 3.0.5 / tushare 1.4.29 |
| 业务时钟 | `Asia/Shanghai`；全部观测时间均带明确 `+08:00` |
| 端点 | HTTPS 主机 `api.quicksync.cn`；URL 不含凭据 |
| 凭据引用 | `TUSHARE_TOKEN` 只提供给已授权子进程 |
| 真实调用授权 | 进程内 `TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE=1`；普通测试套件跳过联网测试，显式 `-m live` 选择器在缺少授权或 Token 引用时失败关闭 |

凭据页只在获得动作时确认后于受控浏览器中打开、读取并关闭。Token 只保留在内存中，通过标准输入传给唯一获准子进程，仅写入该子进程自身环境，从未加入父进程环境；使用后随浏览器执行上下文清除。它从未写入文件、命令行、报告、Git 对象或测试输出。原始 SDK 异常、HTTP body、header、请求参数和授权响应均不属于证据产物。

## 能力与节流证据

脱敏 RED 独立尝试全部五个已批准操作，确保单个失败不会隐藏其他能力状态。

| 操作 | 结果 | 延迟毫秒 | 安全观测 |
|---|---|---:|---|
| `trade_cal` | `ERROR`（`TRANSIENT`） | 7 | 零行；未保留 schema 或 body |
| `stk_limit` | `ERROR`（`TRANSIENT`） | 24 | 零行；未保留 schema 或 body |
| `daily` | `ERROR`（`TRANSIENT`） | 2 | 零行；未保留 schema 或 body |
| `rt_min` | `ERROR`（`TRANSIENT`） | 13 | 一次精确 10-symbol 请求；返回零个股票 |
| `rt_min_daily` 样本 1 | `ERROR`（`TRANSIENT`） | 26 | 零行 |
| `rt_min_daily` 样本 2 | `ERROR`（`TRANSIENT`） | 18 | 零行 |

各调用开始时间至少相隔一秒。六次开始时间按连续秒记录在 `11:24:21+08:00`～`11:24:26+08:00`。该节奏下未观察到 `RATE_LIMITED` 分类。测试没有主动制造限流流量，也不根据文档或其他账号推断本账号的每分钟配额。

以下机器可读对象是与英文报告逐字节一致的规范脱敏证据。它有意不包含凭据值、原始请求、响应 body 或 provider 异常文本。

<!-- T058-CANONICAL-EVIDENCE-START -->
```json
{
  "acceptanceBranch": "VISIBLE_BLOCK",
  "baseline": "eee65fd9ede37cee229c0147ba2ddb55a5f311d5",
  "capabilities": {
    "daily": "ERROR",
    "rt_min": "ERROR",
    "rt_min_daily": "ERROR",
    "stk_limit": "ERROR",
    "trade_cal": "ERROR"
  },
  "calls": [
    {
      "latencyMs": 7,
      "operation": "trade_cal",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:21+08:00"
    },
    {
      "latencyMs": 24,
      "operation": "stk_limit",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:22+08:00"
    },
    {
      "latencyMs": 2,
      "operation": "daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:23+08:00"
    },
    {
      "latencyMs": 13,
      "operation": "rt_min",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:24+08:00"
    },
    {
      "latencyMs": 26,
      "operation": "rt_min_daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:25+08:00"
    },
    {
      "latencyMs": 18,
      "operation": "rt_min_daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 2,
      "startedAt": "2026-08-31T11:24:26+08:00"
    }
  ],
  "endpointHost": "api.quicksync.cn",
  "finalMinute": null,
  "officialCloseRows": null,
  "pacingSeconds": 1.0,
  "rateLimitObservation": "NO_429_UNDER_PACING",
  "requestedSymbols": 10,
  "returnedSymbols": 0,
  "sourceTimeLabel": "SourceTimeLabel.UNVERIFIED",
  "timezone": "Asia/Shanghai"
}
```
<!-- T058-CANONICAL-EVIDENCE-END -->

## 批次、部分行与单位

`rt_min` 收到一次逗号分隔的 10-symbol 请求。该调用在返回任何 provider 行之前被分类为 `TRANSIENT`，因此真实结果是请求 10 个、返回零个且没有意外股票。这既不是批次为 `READY` 的证据，也不是 provider 部分行行为的证据。

没有原始市场数据行可用于真实单位对账。因此，实时价格转分、成交量为股、成交额为元、日线成交量乘 100 和日线成交额乘 1000 均保持真实未验证。既有确定性离线契约测试仍然有效，但不会被冒充为 T058 真实证据。

## 时间戳映射、最终分钟与官方收盘

两次 `rt_min_daily` 样本均在返回数据行前以安全 provider 代码 `TRANSIENT` 结束。时间戳映射因此保持 `SourceTimeLabel.UNVERIFIED`；本报告不选择 `SourceTimeLabel.START` 或 `SourceTimeLabel.END`。

无法观测 15:00 最终分钟、完整 240 分钟交易日或官方 `daily` 收盘。两个必需接口均为 `ERROR`，因此修正后的收盘分支不执行新增调用，并让应用保持显式只读。证据记录 `finalMinute=null` 与 `officialCloseRows=null`；不宣称 `OFFICIAL_READY`。

## 失败关闭应用证明

候选测试按照与 `TushareMarketDataProvider.probe_capabilities` 相同的契约把生产 provider 代码映射为 `ProviderCapabilityStatus`，随后启动真实 `RuntimeLifecycleService`。任何包含 `BLOCKED_PERMISSION`、`RATE_LIMITED` 或 `ERROR` 的完整组合都必须产生 `DEGRADED`、`read_only=true`、`next_poll_at=null` 以及零个自有可执行任务。健康 API 模型必须保留每项独立状态，已跟踪健康矩阵必须把当前 `ERROR` 状态渲染为“错误”。补充 provider 保护仍证明未验证时间戳映射不会触达 SDK 调用。这是应用级显式阻断，而不是仅根据 provider 作出的推断。

## 命令与结果

规定的授权选择器为：

```text
python -m pytest tests/contract/test_tushare_live.py -q -m live
```

第一次诊断 RED 因 pytest 常规 traceback 包含非敏感请求参数而作废；其中没有出现 Token 或原始 provider 响应。失败面随即改为采用 `pytrace=False` 的固定错误码。之后一次在 10:15 把全部失败标记为 `BLOCKED_PERMISSION` 的运行也已作废，因为它使用重复且宽松的分类器，而不是生产分类器。

一次中间 `3 passed` 运行也已作废：审查发现其收盘测试在 15:20 前额外调用两次，而报告只记录原始六次调用。接入生产分类器后，经授权的精确选择器在 11:24 得到预期 RED：五项 provider 错误均安全分类为 `TRANSIENT`，但测试仍把 adapter 错误码误作能力状态。该选择器报告 `3 failed`，只执行已记录的六次调用，并确认配置的 Token 原值未出现在输出中。修正后的候选现把这些代码映射为 `ProviderCapabilityStatus.ERROR`，复用稳定的五能力观测，收盘测试零新增调用。此项修正后，受影响的离线行情/运行时套件报告 `399 passed, 2 skipped`。

修正后的授权选择器完成结果为 `3 passed in 6.09s`。最终受影响离线行情/运行时重跑完成结果为 `399 passed, 2 skipped in 5.77s`。Ruff check、针对 158 个已跟踪或候选 Python 文件的 Ruff format、`compileall`、`pip check`、空白检查、报告等价性、配置 Token 原值缺失检查和普通零联网选择器均通过。

另行执行的一次非必需完整后端诊断在既有 `test_ten_symbol_252_day_replays_meet_capacity_budgets` 首个股票超过 120 秒截止 0.087856 秒后停止；其聚焦重跑在 284.90 秒内复现相同的宿主机性能失败。没有修改阈值或回测代码；该诊断不属于 T058 要求的真实调用加完整离线行情/运行时闸门，也不会被呈现为通过证据。

T058 通过其明确替代条件满足验收：每项必需能力要么为 `READY`，要么应用诚实且显式保持阻断。本次没有任何能力为 `READY`；五项能力均为 `ERROR`，报告只声明已证明的显式阻断分支。以后如需取得 `READY` 证据，必须获得新的操作专项授权并处于合适市场窗口；新证据必须替换而不是曲解本次事实。

## 脱敏与产物策略

跟踪报告只包含环境变量名 `TUSHARE_TOKEN`、稳定能力码、计数、时间戳、端点主机及有界延迟。它不包含凭据 URL、Token 值、`Authorization`/`Bearer` 材料、原始响应、provider 异常文本、下载代码、截图、浏览器 profile 或临时观测文件。五个受保护的仅验证文件均保持未跟踪且未修改，且没有任何一个被执行或作为证据使用。一次意外 `rg` 诊断搜索读取了受保护稳定性文件中的六个匹配行；该事件已向用户披露，其输出已从证据中排除，之后每项正式输入均使用明确的已跟踪或候选文件允许清单。
