# 监控闭环回测操作指南

英文规范：[monitor-loop-backtest.md](monitor-loop-backtest.md)。本文说明已实现的单计划研究流程。实际证据和审阅状态见[验证记录](../verification/monitor-loop-backtest.zh-CN.md)。

## ML-O01. 支持范围

每次运行冻结一份完整已审核 Schema 5 计划、一个标的和一份期初账户。规则在适用交易日保持固定；成交更新账户和共用监控状态。本期不包含每日后继、计划链、多计划同时运行或多标的共用资金。同步、数据集校验、提取及回放共用一个未完成任务槽。排队、运行中、等待取消及过期但未确认的工作，在终态完成或明确恢复前保持占用；切换页面不能释放任务。

这是离线模拟，不激活实时计划、不发券商订单、不发送真实通知、不重写监控持仓。历史兼容运行仍按原契约读取。

## ML-O02. 准备并审核一份原文

打开 `/backtests/new`，选择原文准备方式，粘贴完整原文或读取一份 UTF-8 文本/Markdown 文件。分别保留编写时间、历史可用时间及生效交易日；日期时间使用 Asia/Shanghai。缺失事实保持未知。先保存再提取。已接受准备记录的身份保留在 URL，刷新/返回会载入同一记录。

提取使用既有已配置 AI 防护，每份原文修订最多 3 次尝试。可重试失败需要明确重试；未知付费结果不会静默重试。审核所有可执行字段、原文映射条款、补充、排除项及期初账户事实。不支持/未解决条款阻止冻结。AI 提供候选，明确人工确认提供审核权限。

修改已保存原文会使候选/审核失效，必须重新提取及审核。已提交冻结输入保持不变。已审核 `FROZEN` 候选通过 `candidateHash` 公开权威准备清单身份；内部提取哈希保留原始原文/提取绑定。运行提交使用该清单身份。

## ML-O03. 期初账户、费用与时间

期初批次表示原文实际持仓，不是模拟买入，也不收购买费用。取得单价、批次总成本、原文参考价及具有有效时点的期初估值分别记录。例如，100 股、每股 40.105 元保留总成本 401050 分。未知现金、库存、成本或可卖量不能变成虚构的零。人工修正必须有明确审核证据。

选择 `FOLLOW_REMINDERS` 或 `OBSERVE_ONLY` 及精确费用/滑点。前者从有效提醒生成完整数量请求，后者不改变持仓。`RECORDED_ACTIONS` 保留为有界领域兼容值，不增加自动请求；原文准备界面提供两种已实现自动响应选择。整手、T+1、CORE、仓位上限、风险/冲突及含费用现金检查由服务端权威执行。完整数量失败时不替代为部分交易。

省略/null 结束日期在接受提交时一次解析为上海日期与证据截止。明确结束日期包含当日，不能早于历史起点或超过提交时的本地日期。重试/重启复用原截止。当前未完成交易时段只保留可用完整证据；真实缺口保持阻断。原文可用/生效前不产生事件。结束保留未平持仓，不生成清仓交易。报告分别展示请求/解析结束日期、实际证据截止、不可用市场收益指标和历史成本损益。

## ML-O04. 公开 API 与结果读取

修改请求使用既有本地 Origin 防护及 `Idempotency-Key`。发送前冻结 Body/Key，未知响应必须以完全相同的一对明确重试。服务端修订与身份为权威。

| 操作 | 路由 |
|---|---|
| 保存一份原文 | `POST /api/v1/backtest-preparations` |
| 读取耐久进度 | `GET /api/v1/backtest-preparations/{preparation_id}` |
| 修改原文 | `PUT /api/v1/backtest-preparations/{preparation_id}/source` |
| 明确提取 | `POST /api/v1/backtest-preparations/{preparation_id}/extractions` |
| 审核冻结 | `POST /api/v1/backtest-preparations/{preparation_id}/reviews` |
| 请求取消 | `POST /api/v1/backtest-preparations/{preparation_id}/cancellations` |
| 确认未知提取已结束 | `POST /api/v1/backtest-preparations/{preparation_id}/recoveries` |
| 提交/读取运行 | `POST /api/v1/backtest-runs`, `GET /api/v1/backtest-runs/{run_id}` |
| 读取因果审计/成交 | `GET /api/v1/backtest-runs/{run_id}/details`, `GET /api/v1/backtest-runs/{run_id}/fills` |

准备运行提交绑定 `preparationId`、`manifestHash`、`response`、`costs` 和可选 `endDate`，不接受手写未来交易。`monitor-loop-result-v1` 结果包含冻结来源、完整计划/期初账户、原生 `backtest-report-v4` 指标及因果 `monitor-loop-event-v1` 行。原生审计读取使用 `kind=DECISION`，页面由服务端排序，最多 100 项。回执保留公开模拟身份；内部存储成交键绑定运行，避免顺序实验碰撞。既有旧暂存成交仍严格校验，并可重放且不新增重复行。

结果页展示汇总、证据截止、账户/估值限制、按时间排列的评估/提醒/请求/执行/状态/估值及实际成交回执，不虚构逐笔损益。原生闭环导出在流式输出前返回 409，界面操作不可用；既有冻结研究导出字节保持兼容行为。

## ML-O05. 失败、取消与未知操作

503 表示局部服务能力失败或有界 SQLite BUSY/LOCKED 冲突；原文/运行表单保留原请求供明确安全重试。409 表示状态/绑定或共用未完成槽冲突，其他操作前先读取权威状态。任务失败与服务降级是不同事实；刷新或历史读取均不静默重新提交工作。

取消确认不代表物理完成。正在提取的任务在自有调用结束前保持准入。未知代次跨刷新/导航保持可见，释放前须通过明确恢复操作核实旧调用已经结束。迟到原文结果受代次/修订隔离。回放取消或发布失败不产生已完成的部分报告。取消/租约/提交竞争保留既有 Claim Token 与原子发布检查。

## ML-O06. 存储与有限边界

默认独立路径为 `data/backtest-market.sqlite3`、`data/backtest-results.sqlite3`、`data/backtest-preparation.sqlite3` 及 `data/backtest-cursor.key`。保留既有路径/存储域校验，浏览器/API 命令不接受任意服务端文件路径。回放只读耐久复制输入/证据，配置、供应商、AI 和通知调用均为零。

原文最多 150000 字符；有界原文字节、3 次提取、70000 条闭环记录及最多 420001 行审计为明确边界。结果以最近 30 次运行作为一个总上限，包括置顶，使用有界清理并保护自有输入/报告文件。分页最多 100 项；整数保持安全，金额计算保持精确。历史同步只有一个活动任务，以 BACKGROUND 优先级，在日历/日线/分钟/涨跌停真实请求起点间至少等待 1.25 秒。缓存命中不新增等待；取消会在下一供应商调用前观察节流。不增加全局配额分配器或动态 CPU/内存控制器。

## ML-O07. 复现本地验证

在 `trade-plan-monitor/` 使用既有开发环境执行。下列检查使用合成事实和一次性存储，不使用真实用户数据或付费供应商。若默认 OS pytest 临时根目录不可用，可追加新的工作区 `--basetemp=.pytest_cache/local-verification-unique` 目录，不修改检查：

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"
.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline
npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
```

Windows 负载命令分别运行 600 秒十只股票监控基线和 600 秒顺序准入原生回放/WAL 负载，回放准入起点间隔至少 120 秒（每十分钟最多五次实验）。这只约束离线夹具，不新增生产提交限速。每阶段至少采集 1000 次状态请求，验证全部计划评估及稳态语义提醒。状态 p95 <= 250 ms、p99 <= 1000 ms、p95 增量 <= 100 ms、调度 p99 增量 <= 250 ms 保持原计划门槛。`--smoke` 仅是短时开发试跑，不能证明这些门槛。被忽略的 `.pytest_cache/backtest-thread-load.json` 记录主机、时长、实际百分位、内存/WAL 观察及完成任务，双语报告保留实际证据。夹具只验证实测工作量，不认证真实 AI/供应商、大型生产数据集或全部共用主机争用场景。

实测负载修正先过滤当前评估历史再解码旧数据标记，并在一次监测事务内复用兼容判定。损坏及旧数据仍保留原保护；不引入持久缓存、历史重写或监测规则变化。

## ML-O08. 惰性启动与明确服务控制

应用启动、监测导航、路由预取及服务状态读取不触碰回测存储、游标密钥、提供方和执行线程。首次实际回测读取才进行一次元数据准备；准备尚未完成时可能返回 503。元数据就绪不会授权待恢复工作。真正新增的准入仅授予所选任务执行权限；重放旧幂等收据不会获得权限。当前回测页面分别展示服务准备/故障、任务状态和原文状态。

通过 `GET /api/v1/backtest-service` 读取惰性、`no-store` 状态。状态包括 `DISABLED`、`NOT_INITIALIZED`、`STARTING`、`READ_READY`、`READY`、`RECOVERING`、`DEGRADED`、`STOPPING` 和 `STOPPED`。`READ_READY` 允许元数据读取，执行协调器仍保持休眠。`READY` 表示具备执行能力，不会自动恢复历史任务。仅执行侧失败时，`DEGRADED` 仍可能保留健康的元数据读取；应检查能力，而不能把所有降级状态当成不可读。

状态包含 `epoch`、`revision`、`generation`、`canRead`、`canSubmit`、`canCancel`、`canExport`、`physicallyDrained`、`authorizedJobIds` 和 `reason`。epoch 是 32 位十六进制启动身份，禁用服务时为 null；修订/代次为安全整数。最多授权一个任务。`SERVICE_REPAIR_REQUIRED` 是安全的降级原因。读取/取消/导出能力表示服务接口是否可用；具体操作仍受自身状态/模式约束，包括不支持的原生闭环导出。服务修订、准备修订和任务领取代次分别归属。

明确选择局部修复。向 `POST /api/v1/backtest-service/recovery-requests` 发送当前 `epoch`、`expectedRevision`、`action` 和 `resumeJobIds`，沿用既有来源及幂等保护。`RETRY_PREPARATION` 要求所选任务列表为空且已实际排空。`RESUME_JOBS` 要求恰好一个所选任务 ID。UI 仅在明确要求查看待恢复任务后加载，再要求选择与确认；浏览历史或变为就绪均不提交第一项待恢复任务。修复本身不创建付费提取、不提交新运行，也不改变冻结截止。待确认控制应使用原始请求体/键重试。启动身份/修订变化冲突时重新读取状态，不能静默改写待确认命令。

向 `POST /api/v1/backtest-service/stop-requests` 发送 `epoch` 和 `expectedRevision` 停止该服务。两种控制均返回 202，并带 `Cache-Control: no-store`、`Location: /api/v1/backtest-service` 和 `Retry-After: 1`。确认发生在繁重工作完成之前，受计划的 1 秒门槛约束。确认代表意图已接受，不代表实际清理完成。继续观察状态：自有工作及最终清理结束后才能进入 `STOPPED`。卡住的自有调用可能停留于 `DEGRADED` 且 `physicallyDrained=false`，排空前阻止替换。仅停止服务不会清除未知耐久提取记录或任务准入；应通过该记录明确且有证据的恢复路径解决。

每次启动最多缓存 1000 条控制键收据。重载保留耐久任务/原文身份；应用重启改变 epoch 并丢弃当前会话执行授权。两者均不静默重跑排队、到期、取消中或未知工作。局部修复/停止期间监测导航仍可使用；只有实际监测证据支持时才能声称监测健康。

## ML-O09. 同进程限制与批准身份历史

专用有界归属线程在已验收 Windows 夹具中达到 7 条回测线程。它们隔离调度及普通异常，与监测共享 CPU、内存、进程生命周期和磁盘。不具备每线程 CPU/内存上限、强制杀死线程，或对原生崩溃、进程资源耗尽、主机/存储故障的保证。协作取消及有界排空保留归属；增加子进程是未来可选范围决定，不是强制升级。实际负载结果及主机限制记录于 MV43；不代表真实 AI/提供方认证。

重试/重启应保留原文/提取清单、冻结运行/截止、审计/收据、领取及游标的权威身份。内部绑定运行的成交键避免跨运行存储冲突，不改名因果收据及先前事件。既有旧成交仍支持精确验证。已知历史 OpenAPI 批准不一致及其限范围审阅纠正保留在 MV12/U04；最终审阅的契约身份归属 ML-T29/U09，不能仅根据类型生成成功推断。
