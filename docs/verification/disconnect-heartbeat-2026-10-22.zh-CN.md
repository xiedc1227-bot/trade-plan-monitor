# 感知断连的心跳 P0 验证

日期：2026-10-22。基线：`b323840`。[英文原版](disconnect-heartbeat-2026-10-22.md)。[规格](../specifications/backtesting/SPEC-disconnect-aware-heartbeat.zh-CN.md)、[任务](../specifications/backtesting/TASKS-disconnect-aware-heartbeat.zh-CN.md)、[可移植证据](evidence/2026-10-22-disconnect-heartbeat-verification/measurements.json)。

## DHA-V01. 交付范围

P0 增加连接局部监督，恰好拥有 1 个接收子任务和 1 个发送子任务。终止信号阻止后续心跳准入、回放和发送。关闭 socket 经既有所有权取消其健康观察者，并等待两个传输子任务。重复外层取消不能丢弃子任务清理；保留原取消身份/参数，兼容 Starlette/AnyIO。清理失败仍是失败。每页回放都会让出执行，因为不拥塞的发送不一定挂起。

生产修改仅限 `src/trade_plan_monitor/web/monitor_connection.py`、`src/trade_plan_monitor/web/websocket.py` 及 `src/trade_plan_monitor/diagnostics/read_tracing.py` 的固定诊断阶段名。两个既有假 socket 增加阻塞接收接口，两个新增集成测试模块覆盖行为。不包含前端产品、依赖、codec、数据库 schema、读取所有者、权威或证明校验器实现修改。

## DHA-V02. 复现与正确性

初始 18 个回归在原始源码上出现 17 个失败，1 个发送失败对照通过。实现后通过聚焦协议/所有权/追踪套件。另增快速回放回归，先复现消费排队断连前仍发送 100 帧；每页检查点使夹具中仅发送 1 帧。再增用例证明取消健康调用时，清理失败不会被吞掉。冻结候选的全部 20 个新增用例通过。

即使第二次外层取消，停止态临时健康读取器仍由原 `finally` 停止/排空管理。共享证明覆盖领先者、跟随者和全部观察者退出，并分别验证有效/失败证明。存活观察者获得完整校验的结果或原始拒绝。存储检查点/排空超时保留暂停，拒绝新读取，阻止提前释放数据库；后续成功清理只释放正确所有者的暂停。既有真实检查点失败恢复用例也保留在回归范围。

## DHA-V03. 真实浏览器关闭与准入

两轮固定主采集沿用相同配置、历史数据、协议及 20 秒心跳周期，每轮覆盖 54 个页面、40 次直接结果读取、20 个已接收的持续连接对照心跳帧，以及有界 2/8 页面负载。改后主采集的读取中关闭试验有 8 个页面发生真实重连，初始 20 次中仅 12 次能确认浏览器关闭时拥有的读取仍在途。随后固定补充恰好 12 次试验，恢复后跟随真实最新 socket，12 次全部符合。保留全部初始试验。因此改后为 32 次原始试验中 24 次确认在途关闭，对比改前 20 次中 20 次；补充试验不进入原主采集的结果耗时比较。

| 首次心跳前关闭负载 | 改前 | P0 |
|---|---:|---:|
| 首次心跳前关闭页面 | 20 | 20 |
| 浏览器关闭后才开始的心跳健康尝试 | 20 | 0 |
| 这些尝试进入快照的次数，含重试 | 22 | 0 |
| 这些快照线程 CPU 秒数合计 | 25.71875 | 0 |
| 主采集中返回 HTTP 200 的直接结果读取 | 40 | 40 |
| 页面脚本错误/业务写入 | 0 / 0 | 0 / 0 |

CPU 合计对每个拥有的快照跨度只计一次，不叠加嵌套证明耗时；它描述这些废弃页面的尝试，不代表整个服务 CPU 或所有负载的预测。基线没有接收侧终止观察，因此其“服务端已知关闭后准入”指标不可用，不是零。

改后主采集与补充的全部 74 条 socket 根追踪都有子任务等待完成记录，观察到终止后新增健康准入为 0。20 次首次心跳前关闭中，终止至子任务排空中位数为 0.14675 ms，最大 5.3551 ms。这些是服务端调度边界，不是浏览器关闭感知延迟或通用关闭 SLA。

已准入物理工作刻意分开计算。24 次确认在途关闭记录了观察者取消，而拥有的读取仍可能晚于 socket 根结束；最长观测为 3.5211112 秒。这是保留物理所有权/协作退出，不是再次准入心跳，也不是成功返回部分校验结果。

## DHA-V04. 结果观察与剩余失败

两轮主采集的全部 80 次直接结果响应均为 HTTP 200，完整响应哈希相同。耗时来自不同真实所有者代次及后台活动的观察，不作为受控的因果提速结论。

| 主采集结果范围，各 20 个样本 | 改前中位数/范围，秒 | P0 中位数/范围，秒 |
|---|---|---|
| 独立发起读取 | 2.353 / 2.176–5.132 | 2.205 / 2.053–4.776 |
| 有持续连接监控客户端时读取 | 2.424 / 2.217–5.778 | 2.347 / 2.030–6.502 |

混合场景最大值上升，中位数虽下降，尾部波动仍然存在。每轮另行保留 7 个 HTTP 503，其中 5 个监控总览、2 个任务列表。这些是受保护的准入失败，不算快速成功；没有弱化上限、等待或校验来掩盖。补充浏览器采集的控制台/页面错误为 0，业务写入为 0。

## DHA-V05. 权威与证据不变量

`MonitorReadOwner`、`RuntimeStatusReadService`、`IndexEvidenceFlights` 及 `src/trade_plan_monitor/state/projections.py` 的完整源码哈希与改前锁定记录一致。关联追踪中每个成功的持续连接拥有读取，前后权威跨度计数均独立匹配。各自时钟/BEGIN 快照、激活重读、计划/库存/风险/日历/证据检查、原有 2 次尝试、8 个读取/15 秒协作等待、1 个物理校验者/1 个不同输入排队所有者、64 MiB 保留，以及仅在途精确输入共享，全部保持不变。

取消工作可以在既有检查点退出且不返回响应，不能认证部分证明。不增加已完成健康/证明缓存、强制线程取消或提前释放资源。完整性/保留/时间边界测试仍使用原校验器。进程内变异捕获 5 个新增边界缺陷及 8 个既有完整性/权威缺陷：准入守卫、观察者取消、子任务等待、取消身份、回放公平性；decoder envelope、canonical equality、event hash、set identity/count/hash、length prefix 和 authority token。变异探针不修改生产文件。

## DHA-V06. 开销、对照噪声与分配

首轮固定 20 轮交替测量未达开销目标：墙钟中位数 2.1765525 → 2.2941853 秒（+5.40%），CPU 2.125 → 2.2578125 秒（+6.25%）。这些样本完整保留。约第 11 轮出现双方共同耗时跃迁；配对 CPU 差值中位数为 0。6 个带观测的归因样本中，变化主要落在未修改的快照线程内；它们排除在计时验收外，也不能唯一归因为硬件、调度或 GC。

确认采集前固定仅做一轮：恰好 10 对 A/A，随后 20 个 ABBA/BAAB 区组，不再扩样。A/A CPU 配对差异范围为 -7.78% 至 +15.57%，说明环境噪声明显。平衡比较含改前 40 次、改后 40 次；墙钟中位数 2.6916485 → 2.69103075 秒（-0.023%），CPU 中位数同为 2.6484375 秒（0.00%）。区组配对差异中位数为墙钟 -0.387% / CPU -0.678%。确认点估计满足未改变的 <=5% 墙钟/<=2% CPU 目标；这不证明零开销或很窄的置信界，也不抹除首轮失败结果。

全部冻结心跳完整帧一致。这些测量使用只读的 2008 候选监控副本、固定时钟和合成的所有者缺席权威，并使用加速夹具时钟及外层观察者取消。它们隔离测量完整校验读取及传输清理，不是真实所有者/浏览器验收，也不是真实心跳周期耗时。A/A 对照和初始/确认设计分别保留，没有挑选性混合以获得通过。

另行对每个变体使用 3 个新进程观察分配，Python 分配峰值中位数为 42,889,248 → 42,895,625 字节，增加 6,377 字节（约 0.015%）。其受跟踪影响的计时不进入开销验收。这是 Python 分配峰值，不是整个进程 RSS，也不是校验器单独的保留证据字节计数。

## DHA-V07. 最终测试与浏览器检查

- 最终后端：460 项通过，1 个既有 Windows/POSIX 所有权跳过，1 个既有 Starlette 弃用警告，耗时 434.97 秒。
- 最终聚焦协议/所有权/追踪回归：54 项通过；20 个新增用例也独立通过。较早的完整候选回归为 459 项通过/1 个既有 Windows 跳过；以上冻结源码最终总回归将替代该结果。
- 浏览器回归：25 项通过，耗时 1.3 分钟，覆盖监控总览权威、响应式/无障碍边界、序列间隙恢复、流完成/调用者取消，以及回测流程。类型检查通过。并行日库存 UI 的源码/夹具修改不属于 P0 范围。
- 真实页面确认：来源/摘要切换、结果刷新与返回监控成功；首次/刷新结果和监控总览均为 HTTP 200，监控为 RUNNING/STANDBY，脚本/控制台错误为 0，写入为 0。已检查截图。最后确认使用后来未启用追踪的实例，不声称获得新的物理追踪 ID；固定测量轮次保留各自原始关联。
- 限定范围 Ruff、空白、双语文档 ID/数字/技术标记/命令/链接与保留检查通过。不放宽测试门槛、完整性断言或诊断上限。

在项目目录运行的最终后端命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_disconnect.py tests/integration/test_monitor_disconnect_ownership.py tests/unit/test_monitor_read_ownership.py tests/unit/test_index_evidence_flights.py tests/integration/test_websocket.py tests/integration/test_runtime_status_websocket.py tests/unit/test_read_tracing.py tests/unit/test_audit_read_integrity.py tests/integration/test_read_trace_ownership.py tests/integration/test_monitor_read_tracing.py tests/integration/test_monitor_evidence_sharing.py tests/integration/test_backtest_thread_ownership.py tests/integration/test_runtime_status_projection.py tests/integration/test_runtime_status_composition.py tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_workspace_reads.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_retention.py tests/unit/test_loop_diagnostics.py tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_contract_negotiation.py tests/integration/test_web_api.py -q --basetemp=.pytest_cache/dha-final-regression
```

在 `web/` 运行浏览器命令：`npm run test:e2e -- dashboard.spec.ts streamCompletion.spec.ts backtest-workspace.spec.ts backtests.spec.ts`；类型：`npm run type-check`。

## DHA-V08. 运行事件与保留改动

初始探针连接到了追踪窗口已过期的旧服务，未关联样本已排除。该所有者正常停止/排空后，以相同配置启动固定基线及候选测量窗口。不手动清除历史记录或存储围栏。

两轮固定浏览器采集与补充结束后，最后确认最初遇到连接拒绝；随后另一个未启用追踪的标准入口实例占用了端口。没有 Python 崩溃事件或正常退出记录能确定旧实例替换的发起方。重复启动未能绑定并自行关闭，不计为验证。保留当前所有者。6 个传输/权威函数的规范运行代码签名与冻结候选一致；其快照中拥有的读取/保留证据字节均为 0，2 个传输子任务属于其仍活动客户端，不属于已结束的测量连接。不能把不同实例的计数当作前后性能测量。

初始并行 AI 提取文件指纹仍一致。新观察到的并行 `src/trade_plan_monitor/web/daily_service.py`、`web/src/components/plans/PlanSimulationPanel.vue` 和 `web/tests/unit/dailySimulation.spec.ts` 修改也排除在外，本任务未编辑。只读库存仍为 5 条历史回测、19 条准备、14,800 条审计明细及 0 条成交，非零成交由夹具覆盖。配置及库存保持不变，记录在可移植证据中。执行期间其他工作将仓库 HEAD 推进到 `729d56c`，这些提交不属于 P0，原样保留。实施阶段未提交或推送；后续用户指令另行授权在审查通过后按范围发布。

## DHA-V09. 限制与剩余工作

准入保证始于服务端观察到终止状态。静默网络故障在传输报告前无法被发现；已准入工作仍由原所有者管理到实际完成。活动监控读取仍校验全部历史证据，其 CPU 竞争和已观察到的混合结果最大 6.502 秒仍可能出现。P0 处理废弃连接准入，不声称解决全部活动读取尾延迟。规范字节 P1、进程隔离、扩容线程池、调整心跳超时和证明缓存均不属于本次修改。

## DHA-V10. 发布前审查

后续审查未发现 P0 差异中存在阻塞性的正确性、架构、安全或性能缺陷。本次重新运行断连/所有权、两版 websocket 契约、追踪、读取所有权和证据在途共享测试，72 项通过，耗时 10.60 秒，保留 1 条既有 Starlette 弃用警告。限定范围 Ruff 通过。重新执行的进程内准入、子任务排空及取消身份变异均被预期断言检出；这些是刻意构造的负向对照，不是候选代码失败。审查无需修改生产文件。

7 个候选源码/测试指纹仍与测量候选一致，4 个所有权/校验核心文件与基线一致，8 个初始 AI 文件指纹全部保持不变。4 组双语文档通过一致性及链接检查。既有 460 项后端通过和 25 项浏览器通过结果仍适用于冻结代码，不冒充本次重新运行。可移植测量证据原样保留。发布前远端 `main` 已等于 `729d56c`，因此先前 AI 提取及日库存提交不属于本次新增推送范围。仅明确列出的 17 个 P0 文件允许进入本次提交。
