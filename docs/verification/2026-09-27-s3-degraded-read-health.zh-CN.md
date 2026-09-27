# S3 降级重试读取健康证据

## DRH-01 — 范围

为既有真实组合层 A04 场景补充 tests-only S3-08 验收。root 持有 `tests/integration/test_production_a04_retry_timeline.py` 及本双语报告。不修改生产代码、公开状态/字段、供应商政策或重试间隔。所有请求均使用既有 fake SDK 及临时 SQLite；不涉及真实服务、真实通知、用户数据库、推送或部署。

保留四次原有日历传输失败、30/60/120/300 秒下限、同 owner/controller/generation 及最终真实决策要求。本片不实现或验收 C1 UPD-S5 的权限/startup 双时钟。

## DRH-02 — 断言及已评审 fixture 对齐

在四次实际重试等待中，真实读取服务均须返回 `DEGRADED`、`read_only=true`、`degraded_reason=REFERENCE_REFRESH_FAILED`、无 block reason、READY 数据库/WAL，以及等于生命周期完整 startup 重试时间和实际等待期限的 `next_retry_at`。该期限仍须满足 controller backoff/共享冷却，不能人为缩短至仅 controller floor。`REFERENCE_TRANSIENT` 是既有日志分类，不是公开 degraded-reason 值。

总览须准确保持 `UNAVAILABLE / AWAITING_FIRST_EVALUATION`，无当前 symbol health，实际 socket heartbeat frame 返回 `runtimeLive=false` 和 `runtimeGeneration=null`。本地读取可用，但 socket 或合法本地 owner 均不等于业务进展。evaluation/alert 行保持为空。检查真实 runtime generation，不检查有意排除在 v1 公开响应序列化之外的副本隐藏 generation 字段。

启动恢复后保留原先首次 10:09 唤醒及零求值。继续释放真实调度器等待，最多额外八轮，直至精确 `10:10:12`。每次中间唤醒均须保持同 runtime/generation、无 runner fault、零 evaluation/alert。不得直接选择或调用 deadline、根据 sleep 序号推断行情职责、跳过目标或从任意最终唤醒反推预期目标。唯一结果须具有 `10:10` 目标、真实 `10:10:12` 求值时间，decision head 保留原计划 hash 和 activation revision 1，且无 alert。

Sol 已在编辑前独立批准这一有界 fixture 对齐及读取补充断言。未删除、跳过或削弱原业务断言、用例或重试阈值。

## DRH-03 — 开发证据

在已提交 F3-C（`a1f217b`，文档 HEAD `39ab6f4`）上，未修改的原 A04 测试为 **1 failed in 2.16s**。四次重试检查均通过，失败来自固定第二次 sleep 假设：新增合法维护在 `10:09:42` 唤醒，不是所假设的 `10:10` 行情职责。这是新职责揭示的旧 fixture 假设，不是产品 RED，也不是删除该职责的理由。

完成已评审修改后，专项 **1 项通过，2.36s**。追加唯一结果/求值时刻断言后，两文件运行通过；随后 Ruff 指出测试回调的循环变量绑定问题。显式绑定后，最新作者结果为 **2 passed, 1 warning in 4.45s**，目标 Ruff 通过：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_a04_retry_timeline.py tests/integration/test_s3_installed_runtime_read_liveness.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_production_a04_retry_timeline.py
```

最终测试 SHA256 为 `40C345937E654EAED3D81361B08A35C8AC375B9BBC9BF2F800AB9875A847CA83`。这些运行与 S2 writer 修改源码窗口重叠，最新观测的 `production.py` hash 为 `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7`。它们是开发证据，不宣称源码稳定或全套运行；计数有重叠，不能相加。

## DRH-04 — 剩余门禁

独立 Sol 评审批准这三个文件，无 P1/P2。上文精确的两文件 pytest 命令通过 **2 项，1 warning，4.67s**。协调运行前后六个源码及两个测试 hash 保持不变，其中 `production.py` 为 `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7`，A04 为上文最终 hash。两个测试文件的独立 Ruff 通过，定向 diff 检查通过；双语一致性及原业务断言已独立核对。

这是短暂冻结源码的 S2 工作候选兼容窗口，不批准 S2 实现，也不是固定提交全套验收。C1 统一权限调度、完整 S3-08 矩阵、固定提交汇总回归及最终集成评审仍为 OPEN。不宣称新增公开 API 或第 4 步页面/协议。
