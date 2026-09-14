# R17 下午真实执行——业务验收未通过

英文原版为同名 `.md`，本文为中文审阅副本。执行基线：`main` 分支、提交 `878f15e9180c75a7c882e3e739c56f184f829da0`，保留原有 12 项 tracked 用户改动及四项 R00 untracked 文件。用户在协调任务中直接批准了下午方案。本次是实际的新单次会话，不是回放、定时尝试或复用 R14 授权。

## 1. 结果及有界会话

**真实链路部分执行，业务验收 FAILED。** 已操作真实本地浏览器及供应商调用边界，但没有有效审核计划进入激活，没有完成行情监控周期，没有送达提醒。R14-A/C7 仍未通过。安全拒绝非法草稿与成功支持计划是两回事。

run 为 `r17-20260914-a`，方案为 `R17-20260914-AFTERNOON-60`。上海时间 14:36:44 默认预检就绪；受控命令在获批的 14:40 截止前启动。最终审计记录 **2026-09-14 Asia/Shanghai 14:37:10.665445–14:52:10.867411**，共 **900.201966 秒**；应用健康的启动时间另为 14:37:10.706979。物理尝试为 **AI 3 次、行情 1 次（`trade_cal`）**，联网前拒绝零次、无重试，未调用股票/指数端点。清理返回 `INACTIVE`，退出后 18765 端口已关闭，旧 R14 和新 R17 一次性占位均保留。16 个受保护 SHA-256 全部匹配。启动器状态 `WALL_LIMIT_REACHED`、退出码 **0** 仅表示有界进程正常结束，**不代表业务验收通过**。本地 Web 服务可打开不等于监控正常。

限额保持：三次 DeepSeek 物理尝试、原文各一次、`deepseek-v4-pro`、零重试、30 秒超时、提示词 19,000 UTF-8 字节及输出 4,096 token；行情总 60 及获批的指数 30/股票历史 2 分配；仅回环 18765、隔离 SQLite 和 IN_APP。未改变原文、阈值、持仓、生产数据库或运行中的业务代码。未创建自动任务或替代会话。

## 2. 三份真实 AI 结果

| 场景 | 上海时间提交 / 完成 | 实际终态 | 诊断证据 |
| --- | --- | --- | --- |
| `LITERAL` | 14:38:12 / 14:38:42 | `PROVIDER_ERROR` | `providerErrorCode=TIMEOUT`，一次尝试，未返回用量及结束原因 |
| `SEM-AMB-01` | 14:40:08 / 14:40:14 | `INVALID_OUTPUT` | mapping 阶段 `AI_FIELD_EVIDENCE_INVALID`，`finishReason=stop`，模型匹配；输入 4,930 + 输出 561 token |
| `SEM-UNS-01` | 14:40:31 / 14:40:39 | `INVALID_OUTPUT` | mapping 阶段 `AI_FIELD_EVIDENCE_INVALID`，`finishReason=stop`，模型匹配；输入 4,937 + 输出 904 token |

三份原文均经真实浏览器 UI 各提交一次，三条持久化诊断的原文哈希匹配获批文本。失败原文没有重提。所有结果均阻断激活，公开结果中的草稿和映射为空。没有注入人工替代草稿或合成 K 线让真实会话通过。

两个映射错误只能证明输出未通过原文/当前草稿证据检查，不能定位具体错误字段，也不能证明拒绝这些模糊计划是缺陷。诊断 `path=unknown` 仍是限制。原文超时不能证明余额不足、模型不可用或解析代码错误。超时请求的计费未知；另外两次返回的用量不能证明总费用。历史 R14 失败仍须独立看待。

## 3. 实际监控及浏览器观察

14:41:55 的只读健康 API 返回 `DEGRADED`、`readOnly=true`、`trading_calendar=ERROR`、`REFERENCE_REFRESH_FAILED`，没有 `nextPollAt`、已完成分钟或求值。浏览器系统页显示相同的降级/只读及日历错误。其他能力的 READY 来自配置认证状态，报告延迟为零；不能证明本次调用了这些端点并成功。

总览显示 `EMPTY_DATABASE`、无指数快照、无活动明确规则计划。提醒页在默认全部筛选下为零条记录、无实时更新。SQLite 中没有日历、价格 K 线、计划、审核、激活、明确规则求值、提醒事件、投递尝试或库存行。未执行 ACK 或登记成交。本次提醒为空，**不代表**正常监控了活动计划而条件没有满足：实际监控尚未启动。

日历失败的精确原因未确认。`src/trade_plan_monitor/web/monitor_composition.py:514` 的 `refresh_references()` 在第 520 行把异常收敛为安全阶段码。未捕获供应商返回正文或底层错误类别；本次没有额外调用日历、重试或重启来排查。不能无证据归因于额度、token、网络或 Schema。

## 4. 已确认的前后端契约回归

每次提交获受理后，真实页面均显示“无法确认 AI 提取状态；服务端任务可能仍会继续，请稍后重试查询或重新提交。”并丢失操作结果。对三个已知 operation ID 的本地 GET 均为 HTTP 200，返回正确失败终态及 `diagnosticStatus=RECORDED`。

`PlanExtractionView` 在 `src/trade_plan_monitor/web/routers/plans.py:537` 新增 `diagnostic_status`，`src/trade_plan_monitor/web/ai_service.py:310` 的 `_run_extraction()` 填充该值。但 `web/src/api/ai.ts:205` 的 `isPlanExtraction()` 在第 209 行使用严格字段白名单，没有 `diagnosticStatus`。于是 `web/src/composables/usePlanDrafting.ts:85` 的异常分支用通用状态错误覆盖了已受理操作。

**已运行离线因果对照：**把三份捕获的公开 API 返回，通过注入本地 Response 送入仓库实际 TypeScript `createAIPlanApi()`，全程不联网。三份均在 HTTP 200 下报 `INVALID_RESPONSE`。仅在离线副本中移除 `diagnosticStatus`，三份均被接受，保留原有失败状态。未改变生产载荷、服务器、浏览器校验器或运行代码。这确认了独立于 AI 失败的接口缺陷。此前后端/离线接线回归没有覆盖这个浏览器响应契约，因此未发现它。

最小修复：同步生成类型与手写客户端契约，校验诊断枚举及空值，用生产形状的排队/运行/终态响应覆盖客户端和 composable；仍应拒绝不相关的未知字段。状态显示失败不应引导无限次付费重提。再次付费前须通过实际浏览器验证。

## 5. 命令及证据

用户直接批准后，从 `trade-plan-monitor/` 实际执行一次：

```powershell
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance --execute --authorize R17_20260914_3_AI_60_MARKET_IN_APP_15MIN --run-id r17-20260914-a
node remediation/evidence/R17-execution-20260914/reproduce-client-contract.cjs
```

最后一条命令为离线对照，退出 0，使用未修改的当前 TypeScript 源码复现三次拒绝及三次反事实接受。这是验证证据，不是修复。本地只读 API 和 SQLite 查询不消耗供应商额度。基线的协调 27 项及实施 56 项准备测试仍是离线准备，不能当作真实验收。

`remediation/evidence/R17-execution-20260914/` 含 `observed-health.json`、`observed-extractions.json`（公开失败 DTO，不含原文或模型原始输出）、`extraction-diagnostics.jsonl`、`client-contract-replay.json`、可复现 `.cjs` 脚本、`browser-observations.json` 及标识实际安装前端的 `web-assets.json`。最终 `audit.json` 和 `summary.json` 记录实际计数、时长、端口/占位检查、保护哈希及最终只读 SQLite 表计数。原文哈希匹配三份获批文本，最终相关业务表仍为空。隔离数据库位于 `data/r17-acceptance/r17-20260914-a/`，不提交。证据中不包含密钥、供应商原始错误或账户配置。

## 6. 最小后续顺序

1. 离线修复并在浏览器验证诊断状态 API 契约回归。
2. 为日历失败保留有界、无密钥的错误类别，离线测试启动失败与恢复；仅根据已有证据诊断本次原因。
3. 改善映射诊断的字段/阶段精度，验证原文计划超时行为；不能假定已授权增加超时或付费额度。
4. 上述检查通过后，再提出新的有界真实会话。本次一次性授权和占位不得复用。真实提取/审核/激活、新鲜股票数据及持久化规则求值仍待完成；可见 IN_APP 收悉仍须实际观察。
