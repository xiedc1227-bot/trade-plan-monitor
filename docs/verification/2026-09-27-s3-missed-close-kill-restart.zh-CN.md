# S3 真实进程强杀后的缺失收盘发现

## 范围

本离线证据片仅新增 `tests/integration/test_s3_missed_close_kill_restart.py` 及本配对报告。开始实现时基线 HEAD 为 `c5ca53d`。并行 DAILY_BARS/分钟权限工作不属于本变更。未修改生产代码、迁移、既有测试、scheduler 或恢复策略。独立复核已通过，本次本地提交仅包含这三个文件。

本次验证的问题是：SDK 调用被真实强杀中断，且此前没有收盘 claim、result 或 pending 标记时，实际 composition 能否自主发现官方收盘义务。测试不向生产代码指定恢复日期，也不直接调用恢复或评估服务。

## 场景与断言

- SMCKR-01：合法激活一个 legacy `003043.SZ` 计划，采用 `2026-09-08` 的 `TRADING_DAY` 策略，实际激活时间为 `09:00 +08:00`；登记于 `2026-09-07` 买入的 200 股，准备可信 SSE/SZSE 日历及有效 owner 心跳。初始不存在评估 claim/result、风险行/审计、提醒/投递尝试、pending close 或决策头。既有迁移只作用于临时 SQLite 文件。
- SMCKR-02：在 `2026-09-08 14:59:30 +08:00` spawn P1。实际 composition 及其 scheduler 在 `15:00:12` 到达真实 adapter 后的 fake `rt_min` SDK 边界，由 process event 证明已进入。SDK worker 阻塞在本地线程 event。父进程确认零 claim/result/pending 后，仅将可控时钟推进至 `17:05`，等待 P1 确认此时刻并报告 `RUNNING`，随后精确强杀该子进程对象。P1 不会从 SDK 返回或执行正常 `composition.stop()`；测试不写 `DEGRADED`、pending 或恢复状态。
- SMCKR-03：P2 使用同一数据库，分别在 `2026-09-08 17:05` 或 `2026-09-09 17:05` 启动，均晚于所有收盘尝试时点。计划的单日策略避免次日新增义务。P2 只调用实际 `create_monitor_composition(...).start()`，其时钟不释放任何 scheduler sleep。启动流程必须在未来调度唤醒执行之前，自主发现并提交缺失的 `2026-09-08` 收盘。
- SMCKR-04：要求恰好一个匹配的 `OFFICIAL_CLOSE` claim 及完整结果，原计划 hash/formula/symbol、激活 revision 1、来源时间 `2026-09-08T15:00:00+08:00`、评估库存 200 股、一个 revision 1 且收盘价 6000 的 `BREACHED_PENDING_CONFIRMATION` 风险行、一条风险审计、一条 `RISK_BREACH` 提醒，且无 pending close。缺失收盘的结果评估时刻为 P2 重启时刻。单独断言风险的 risk.updated_at 与 result.evaluated_at 一致，核验写入时刻并与官方来源时刻区分。风险审计只检查存在及无重复，不单独断言其 created_at 与写入时刻一致。
- SMCKR-05：P3 在 P2 一分钟后启动。claim、完整结果字节、决策头、风险状态/审计、提醒记录及投递尝试必须与 P2 完全一致；持久 fake-channel 日志也保持不变。任何实际发送只能是原日期/symbol 对应的唯一预期 `RISK_BREACH` 事件；禁止陈旧盘中评估或发送。
- SMCKR-06：对两个重启日期分别增加 P1 于 `15:19:30` 启动的对照。真实 scheduler 在下一次 sleep 前完成 `15:20` 收盘，随后同样强杀 P1。P2 必须保留已提交 result/risk/alert，P3 必须保留完整已观察业务状态。同日缺失场景和两个已完成对照都要求一次实际 fake-channel 投递，避免投递检查仅验证零发送。

## 隔离与生命周期

每个 child 都在 composition 启动前独立替换 SDK 创建、时钟、供应商 pacing 和通知 channel，并禁止 requests/httpx 的 HTTP 入口。fake SDK 提供符合交易时段的分钟行及 60.00 的官方收盘；响应经过真实 adapter/controller/composition。

父进程只以只读模式读取自己的临时 SQLite。每个 child 使用独立报告 pipe/event/clock；强杀后，P2/P3 不复用旧 IPC 对象。父进程等待均有上限。清理只强杀并 join 本测试创建的精确 Process 对象，不扫描 PID、不按进程名终止、不访问真实服务、用户数据库或通知服务，不 push/deploy。

## 验证与失败分类

1. 新增测试前，先运行既有实际 composition spawn 基线 `test_production_a06_process_scheduler.py`：**2 passed**，1 条既有 Starlette/httpx 弃用警告，11.97s。已确认真实 composition 入口及既有子进程框架可运行。
2. 初始运行已到达 P2 自主提交收盘。修正了三处测试断言/搭建错误，未修改生产代码：风险枚举应为 `BREACHED_PENDING_CONFIRMATION`，而非 `BREACHED`；持久 `risk.updated_at` 表示写入时刻，不是来源 cutoff（见 `SPEC-runtime-recovery.md` 当前计划风险契约）；`16:00` 本身是收盘重试时点，因此将“所有尝试之后”的时钟改为 `17:05`。这些均不能作为生产漏补证据。来源时刻仍同时断言完整结果的 `source_at` 和规范 snapshot 的 `market_data_at`。
3. 同日原型 **2 passed**，15.16s。增加次日重启及单日激活策略后 **4 passed**，26.52s。没有剩余业务 RED；未放宽任何断言来接受结果缺失、重复或陈旧来源时刻。
4. 最终专项/相邻合并运行：**33 passed**，1 条既有 Starlette/httpx 弃用警告，55.80s。包含全部 4 个新增场景、2 个实际 composition 进程用例及 27 个既有缺失收盘用例。定向 Ruff 与空白检查通过，三个未跟踪文件也分别检查。并行工作在最终检查时已将共享 HEAD 推进至 `95feccb`；这些是当前工作区证据，不是隔离干净 checkout 的验证声明。本地提交只包含这三个文件。
5. 独立复核已通过：**4 passed**，27.96s，Ruff 通过，未发现 P1/P2 问题；配对结构、数字及边界一致。按复核要求，仅澄清报告中的 risk.updated_at 断言与审计存在/去重检查的区别，不改变测试或生产行为。

命令，从 `trade-plan-monitor/` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_a06_process_scheduler.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py -x -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py tests/integration/test_production_a06_process_scheduler.py tests/integration/test_missed_close_execution.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_missed_close_kill_restart.py
git diff --check
```

## 结论与限制

本场景的官方收盘义务在强杀/重启后得以恢复，无需新增 pending 表：既有激活、日历和完成证据允许启动流程自主发现。因此，仅凭执行前推进内存游标以及跳过过期 deadline，不能证明此官方收盘重启路径会丢失义务。

这只关闭指定证据缺口，不代表整个 S3-04 完成。它不证明每个盘中分钟的恢复、多 scope 公平、任意长中断、不完整/损坏日历或库存，以及所有提交/发送窗口的崩溃安全性。次日缺失场景允许零或一次有效官方风险发送，并保留一条持久风险提醒；本次观察到零物理发送。本片不宣称跨日通知可达性，也不宣称全部历史通知都被抑制。它验证所测路径无陈旧盘中发送、无重复通知意图/尝试。独立复核已完成，本次报告修订仅澄清已验证范围。
