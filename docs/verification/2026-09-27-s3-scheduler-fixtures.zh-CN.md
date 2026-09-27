# S3 调度夹具迁移：离线验证

## 范围与证据基线

本片仅更新基于 `53b731271b4b3a10a8558da993ecd000f03c1d58` 的测试 `test_live_pipeline_acceptance.py`、`test_runtime_crossed_market_deadline.py`、`test_s3_index_retry_process.py`。此前非 live 全量回归结果为 16 失败、5695 通过、1 跳过、4 取消选择、1 警告，耗时 1087.48 秒。其中七个失败属于这三个文件。迁移前独立复现结果为 live pipeline：3 失败、10.48 秒；crossed market：3 失败、18.68 秒；index retry：1 失败、4.11 秒。这些基线由协调调查提供，本实现片没有重复运行。

过时前提包括固定 sleep 次数、把首次唤醒归类为市场/指数任务，以及启动时修复全部五个股票标的。此前尚未到达的后段断言必须实际执行后才能判断产品行为。

## S1：定时器与指数失效夹具

定时器用例使用局部时钟，按真实调度到期时间放行至 `10:05:12`，最多放行 12 次，之后停驻且不推进时间。它等待下次 sleep 停驻，并断言市场到期时间恰好为 `10:01:12` 至 `10:05:12` 五次、五次 `rt_min` 调用、同一 owner/generation、运行正常且未故障的 runner、恰好一份持久化决策结果和决策 head、目标 `10:05`、评估时间 `10:05:12`。重启保留同一投影。共享 `ControlledClock` 未修改。

expiry/tamper 用例仅预提交合法历史输入：五个标的各 64 根规范化 END 分钟，范围为 `09:31` 至 `10:34`，共 320 行。价格、成交量、成交额与 fake SDK 相同，`received_at` 合法。在一个临时 UoW 事务中，真实 `history.upsert_minutes` 会派生可替换报价；先确认不存在原有报价后，夹具仅删除这五个派生 `LatestQuote` 行，再进行一次提交。新 UoW 校验全部分钟端点、无 `10:35`、无报价、无决策、决策 head 或指数快照。这只属于测试准备。

真实启动最多执行一次股票历史抓取。原有真实市场 deadline 随后为每个标的形成全部 65 根分钟和恰好五个决策，每个保持 activation revision 1。保留原有共享指数 hash、独立指数、BSE 阻断、Schema 1，以及每个可用指数的三个端点各请求一次的断言。expiry 和 tamper 均执行到后段：全部快照转为 `BLOCKED`，且没有新增指数 SDK 请求。原有 legacy-certification 路径不变。

## S2：跨市场分钟与无效时间回顾

文件局部 sleep 替换按真实到期时间放行至固定的首个目标市场处理 `10:04:12`，最多放行 10 次，然后停驻。正控仍在真实 fake-SDK 调用内部跳时至 `10:05:13`。它等待原 `10:05:12` handler 返回和下次 sleep 停驻，使 `10:05:13` 的股票恢复唤醒无法在观测前修复缺口。记录全部任务，允许 `STOCK_RECOVERY`，但市场子集必须恰好为 `10:01:12` 至 `10:05:12`，各一次。断言原有 owner/generation、`10:04` 缺口、`GAPPED` 健康、投影 revision 增长以及零评估/告警。

两个负控均先完成真实 `10:04:12` handler，再回退到 `10:04:11` 或前进至 9 月 11 日。保留只读 `DEGRADED`、`MARKET_DEADLINE_REVIEW_UNAVAILABLE`、无下次 poll/retry、runner 存活、原 last deadline 和零告警，并增加零评估与同一 owner/generation 检查。

## S3：跨 OS 重启的指数重试

步进时钟只放行真实调度 sleep，每阶段限制 32 步。失败阶段等待实际 `REALTIME_MINUTE` 目标 `10:00` 在 `10:00:12` 完成后才捕获市场证据。保留五指数、依赖计划阻断、健康显式计划、实际 fake-channel 发送、回执和干净停止断言。

重启仍在 `10:00:20`，保持持久化重试下限和原始 cutoff。透明 `_run_deadline` observer 在完整 `INDEX_RECOVERY` 入口和出口捕获所有 SDK 调用、业务表快照和发送，不更改参数、返回值、异常或调度。非空 SDK 增量必须仅由所需指数的 `idx_mins`、`rt_idx_min_daily`、`index_daily` 端点组成，绝不从增量中过滤股票调用。相邻股票维护区间单独记录。从 startup 到指数完成，业务数据和发送也保持不变。

复制观测的负控仍能拒绝注入的股票调用、评估写入、告警写入和发送。后续真实调度唤醒在 32 步内到达 `10:05:12`，恰好完成一次目标 `10:05`，然后停驻且不再推进。保留原有原始回执、事件、目标唯一性、不重复发送、不同 PID 和干净退出检查，并增加 owner/generation 断言。

## 验证与限制

作者对冻结的三个测试文件进行最终验证：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_live_pipeline_acceptance.py tests/integration/test_runtime_crossed_market_deadline.py tests/integration/test_s3_index_retry_process.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_live_pipeline_acceptance.py tests/integration/test_runtime_crossed_market_deadline.py tests/integration/test_s3_index_retry_process.py
```

结果：**24 通过、1 警告，30.91 秒**；Ruff 通过。警告为既有 Starlette/httpx 弃用提示。首次完整 live-pipeline 运行 19 项通过、21.35 秒；crossed-market 3 项通过、4.20 秒；index-process 2 项通过、7.56 秒。定时器开发期间还暴露了过时的首次 sleep 断言和作者新增身份字段断言的字段名错误，均已在最终验证前纠正。本片实际覆盖范围内没有观察到后段产品失败。

独立验证对同样三个冻结文件报告 **24 通过、1 警告，31.21 秒**，Ruff 和 diff 检查通过，静态审查无 P1/P2 问题。这是独立的一次运行，不是额外 24 个不同测试。审查者验证了这三个测试与六个相关源文件（production、service、scheduler、composition、recovery、targets）的前后 hash 不变；该采样不是整个源码树的 hash。

冻结 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `tests/integration/test_live_pipeline_acceptance.py` | `972C20C70BAD157F6AF3AA065BE2BB00627029A2B334CD2D58034A0693A87C4C` |
| `tests/integration/test_runtime_crossed_market_deadline.py` | `1F878CF8B66802CCF36B9C362AEED1E5C270358740B6015BDE08602852048F5F` |
| `tests/integration/test_s3_index_retry_process.py` | `4CE3658C64E7F46F7586068CA5FD622FE4FA085AECFD05A3A44E5F781D7924FD` |

本片未改动生产源码。协调者针对已提交组合改动的最终回归仍需完成；本报告不宣称全量测试已通过。全部工作使用临时 SQLite、注入时钟、fake SDK 数据和 fake delivery。没有使用 live provider、外部通知、真实用户数据库、push、部署或 hot reload。实现者未提交，协调者负责本地提交。
