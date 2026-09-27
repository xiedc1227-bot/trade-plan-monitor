# S3 通知事务/发送强杀重启证据

## SNKR-01 范围与状态

本报告日期为 2026-09-27，覆盖 [S3-07](../../tasks/runtime-recovery-todo.zh-CN.md) 的四个离线进程崩溃窗口，仅新增 `tests/integration/test_s3_notification_kill_restart.py`。本片未修改生产源码、既有测试、通知政策或迁移。root 审查者已独立审读测试并复跑全部四项，无 P1/P2 发现；双语报告一致性审查通过，三文件本地提交获批。

这是有界证据，不关闭 S3-07、C3 或第三步。A07 F2/F3 接线后的停止/排空验收仍独立待办。本片不涉及真实服务、外部通知、用户数据库、部署、推送或热重载。

## SNKR-02 生产路径与进程证明

每项使用一个临时 SQLite 数据库和四个顺序运行的 `spawn` 进程。复用已提交的官方收盘 fixture：`003043.SZ` 的合法 legacy `TRADING_DAY` 计划、激活代次 1、200 股前日持仓、日历和心跳。初始被观察的决策/通知表为空。仅验证同日 `RISK_BREACH` 路径，不构成任意停机时长覆盖。120 小时规则衡量软件停止运行时长，而非最新行情时间戳。

P1 在 `2026-09-08 17:05` 启动真实 monitor composition；启动流程自主发现遗漏的 `15:00` 官方收盘并生成决策。没有预置结果、告警或尝试记录，也没有直接调用业务/恢复/派发方法。保留必需的真实 `IN_APP` channel 和 `CurrentDeliveryAdmission`。只有 SDK、时钟、节拍及额外的 `CONSOLE` channel 使用 fake；硬断言实际 fake SDK 调用了 `trade_cal` 和 `daily`，HTTP transport 拒绝网络访问。

fake channel 向本地 JSONL 追加外部效果 marker，并在返回成功前执行 `flush`/`fsync`，不提供幂等抑制。仅暂停的观察器包裹真实业务 UoW commit 和 dispatcher finalization；未提交 receipt 窗口在真实 SQL update 后通过同一连接确认到达。子进程报告 PID 和边界事实后，阻塞在进程私有 Event 上。父进程通过独立只读连接读取已提交状态，只强杀并回收自己创建的子进程，要求非零退出码，并验证强杀前后持久状态和 marker 不变。P1 不执行正常 stop。

P2、P3、P4 分别在 `17:05:30`、`17:06:00`、`17:06:01` 真实重启 composition。每次必须进入 `RUNNING`，在不推进时钟的情况下停驻于未来的调度 sleep，然后正常 stop 退出。不修改既有 60 秒 claim 租约及准入/健康规则。

## SNKR-03 四个硬断言窗口

| 窗口 | 强杀前 | 重启断言 |
| --- | --- | --- |
| `business-uncommitted` | 事务内已有各一条 ledger、result、risk state、alert、delivery eligibility 和 decision head，并删除了对应 pending close；这些暂存变化均未提交。 | 保留独立读取的事务前已提交快照，包括其合法 pending-close 身份。启动流程生成唯一规范收盘决策并完成发送。 |
| `business-committed` | 唯一规范业务意图已提交；delivery eligibility 为 `HOLD`；尝试记录和外部 marker 均为零。 | 启动流程恢复同一 event 和业务记录，再完成发送，不生成第二个业务意图。 |
| `receipt-uncommitted` | `IN_APP` 已发送；已有一个外部 marker；console receipt 在事务内为 `DELIVERED`，但独立读取仍看到已提交的 `CLAIMED` attempt，且无响应码/发送时间。 | +30 秒时 claim 和 marker 不变。租约到期相等点（+60 秒）复用同一 event、attempt ID 和 attempt number 1；预期出现第二个外部 marker，然后提交 receipt。 |
| `receipt-committed` | console receipt 已持久化为 `DELIVERED`，响应码 200，无下次重试时间；恰有一个外部 marker。 | 所有重启均保留原有尝试记录和 marker，不新增 attempt 或发送。 |

所有恢复后的决策均保留原始 plan hash/version/formula、`15:00` 来源收盘、激活代次 1、200 股风险持仓、唯一 risk audit、唯一 alert，且无 pending close。既有已提交业务记录不变。P4 验证完整被观察快照（含 eligibility 和 attempts）以及 marker 均不变。已经完成的 `IN_APP` receipt 不会重发。console receipt 丢失可能导致外部效果重复：这里证明的是持久业务意图和 claim 复用，**不是外部 exactly-once 发送**。

## SNKR-04 结果与候选身份

首轮 `business-uncommitted` 为 **1 failed, 3 deselected in 3.62s**，原因是初始 oracle 错误地期待数据库为空：官方行情上下文持久化已独立提交合法 `PendingOfficialClose`。随后将 oracle 修正为比较独立读取的决策前快照，并断言精确 pending 身份；保留全部暂存决策参与记录不得提交的断言。这是 oracle 误差，不是产品 RED；没有修改生产代码。修正后该项通过（**1 passed, 3 deselected in 10.57s**）。其余项开发轮通过（**3 passed, 1 deselected in 28.94s**），但运行期间源码发生变化，因此不能作为稳定候选证据。

加强断言后，作者在协调冻结源码的窗口内验证 **4 passed in 38.53s**。相邻通知、准入、生命周期和装配测试单独验证 **118 passed in 7.16s**，有一条既有 Starlette/httpx 弃用警告。Ruff 通过。该窗口前后四份跟踪源码指纹一致：

| `src/trade_plan_monitor/` 下源码 | 作者验证窗口 SHA-256 |
| --- | --- |
| `web/monitor_composition.py` | `3D9D8A7B36CEDB248A06E2D633078F06CF3F7A8BAEE2A7D61511B4985F7B52C8` |
| `runtime/recovery.py` | `7F8FFB6AAE4739C864FB3C40F7EEDF5E270422D826E2903F1344453DB4658B7D` |
| `runtime/production.py` | `021993781B39E3F1E88EB63402D30CCE1EBB65B2D6B0DD4746F646A0FE252581` |
| `runtime/service.py` | `DF3EE4DF221D7FB40088B3CDAD66F263C8AB1D529C2A5774F213AFE41E9FAD43` |

root 审查者随后独立复跑未改动的测试：**4 passed in 36.82s**，Ruff 通过，审查无 P1/P2 发现。第二个冻结窗口使用相同 HEAD `7c178184b84b835aa93b40e7120185c95fccaccf` 加 F2 核心工作区候选；被监测指纹前后一致：

| `src/trade_plan_monitor/` 下源码 | root 审查窗口 SHA-256 |
| --- | --- |
| `runtime/recovery.py` | `C090C838BF61F5DA7EB89184C2153AC9D83C00490A9AB49D97BA6F0CC7E5378F` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `runtime/production.py` | `7D5FA3724CE7CC0243535B2A7FDCD54E78EB7A4A703FAEFC41F56AF553CEBBB7` |
| `web/monitor_composition.py` | `DBB3381DC4D29F80AAAF755F9340317D3A655D85C8C85649883A059C3404901E` |

未改动的测试 SHA-256 为 `46E62F96653D36D7C1DEF4A0520DE7F98BE1E90103123CABA26C31825B8C7632`。两个窗口均为工作区候选观察，不是 clean-HEAD 聚合验收，也不批准 F2。开发轮与最终轮存在重叠；作者 4 项、相邻 118 项和审查者 4 项是独立观察，不能累计为去重测试数量。

## SNKR-05 复跑与局限

在 `trade-plan-monitor` 中使用既有环境执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_notification_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -m 'not live' -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_notification_kill_restart.py
git diff --no-index --check -- NUL tests/integration/test_s3_notification_kill_restart.py
```

最初开发命令使用同一测试路径，参数分别为 `-k business-uncommitted -x -q --tb=short` 和 `-k 'not business-uncommitted' -x -q --tb=short`。no-index 检查会报告新文件差异，并可能提示 LF 转 CRLF 规范化；这些不是空白缺陷。

未覆盖：真实 channel 行为/幂等性、所有信号或两个计划家族、每条指令级崩溃位置、跨日释放、任意停机时长、并发 owner，或接线后的 F2/F3 worker 停止/排空。此前四个官方收盘强杀重启用例仍是独立局部证据，不能代替完整崩溃/发送矩阵。本片不引入新发送政策或外部 exactly-once 承诺。
