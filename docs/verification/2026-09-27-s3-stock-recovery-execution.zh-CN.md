# S3 股票恢复执行 — F3-B

## SRE-01 — 状态与边界

基线 `05487b4` 包含已验收 F3-A。本片遵循已批准的[启动分钟修复契约](2026-09-27-s3-startup-minute-repair-contract.zh-CN.md)，包括 F3-09。设计及两项窄接口澄清已获批准。Sol 独立实现评审及最终 hash 核对已完成：批准，无 P1/P2。

五个候选文件：`src/trade_plan_monitor/runtime/production.py`、`src/trade_plan_monitor/runtime/recovery.py`、`tests/integration/test_s3_stock_recovery_execution.py` 及本双语报告。root 保留提交权限。未改变 scheduler/service/composition 默认接线、provider/controller 政策、schema、依赖、全局 scope 上限、启动获取数量或原 A07 文件。未推送、部署、发出真实请求或使用真实用户数据库。

`run_stock_recovery_unit()` 是**直接调用的组件**，不是自主恢复验收。启动保留 F2 最多 10 个标的的过渡行为，且不加 maintenance 预留。F3-C 仍须接入 lifecycle/scheduler ownership，将启动缩为最多一个正确记账的 ticket，保留启动不完整时完成时刻 +30 的 floor，并关闭原 A07 两项 progress RED。index-only 路径不能新增股票权限要求。

## SRE-02 — 单次 ownership 与结果矩阵

- 每个 unit 同步有界本地需求，最多领取一个轮转 ticket，重新捕获其精确 scope，最多发出一次当前日物理请求，并在结束后重新同步。F3-A 缓存不是获取/提交权限。替换 activation/target 或同分钟时钟回拨，不能把旧 ticket 转移给新工作；未知目标在本地 retry 到期时属于正常零获取重新定目标。
- 已提交完整前缀不发请求。合法空/部分响应保留事实，完成时刻 +30 秒重试。部分事实在新 owner 中保留，F2 新事务中的 missing-now 差集保护已有行。一个标的失败不饿死另九个；物理请求开始继续服从共享 1.25 秒节流。
- 只有 RATE_LIMITED/TRANSIENT/TIMEOUT 转为供应商 RETRY，时间为 `max(completion + 30 seconds, next_retry_at)`。同时存在的 `retarget_required` 及晚到目标替换不能消除该 floor。实际 HTTP 429 通过共享 controller 阻止兄弟/指数请求。
- BLOCKED_PERMISSION 保留既有权威阻断和 F3-A 冻结 revision。业务 unit 不探测或解除。局部预留/窗口拒绝不伪造为供应商失败或 cooldown，而是给出具体本地 wake。
- ERROR/QUEUE_FULL/CLOSED/INVALID_RESPONSE controller 失败向上传播原始 `RequestControlError`，保留对象身份、attempts 和 cause，即使同时需要 retarget。没有原始请求异常的本地畸形响应，仅由 F3 owner 抛固定脱敏 `RuntimeError`。存储/程序/协议异常不会转为空/部分或 retry。
- 只有 `_generation_current()` 已失效且权限/binding 未改变、未撤销时才正常退役。配置/认证失败、authority Event/epoch/source 改变及已发生的 fatal/storage 故障仍传播。`_admission_revoked` 不是普通 stop 捷径。获准 provider retry 先记账，再因退休关闭缓存 wake。取消仍在物理 drain 后传播；owned ticket 不提前释放。

获批的 `ScopedRecoveryResult.request_error` 扩展是尾部可选字段，带 `repr=False, compare=False`；只有既有 `except RequestControlError` 保存原对象。generic `recover_scope` 仍返回原有分类，controller 不变。异常仅内部传递，不加入公开响应、持久化或报告。`repr=False` 不代表通用序列化脱敏。

## SRE-03 — 物理边界与启动兼容

maintenance 复用 `_FrozenPermissionMarketWindow`、既有 31.25 秒预留及包含等号的 15 秒最晚开始边界。同刻让位行情。可选逐调用 `_recover_frozen_scope(..., physical_start_guard=...)` 在等待前、排队后的 worker/provider 入口，以及真实认证 wrapper/resolver 完成后的 SDK 调用前检查。worker guard 只用不可变行情时间、线程安全时钟及 F2 内存/token 约束，不增加 worker SQL 或 asyncio Task 检查。hook 不存于 provider/controller，也不跨调用共享。

测试证明预留恰界、真实 wrapper 越界后 SDK 为零、真实 controller 排队越界后 SDK 为零，以及包含等号的最晚开始边界。已入场调用可晚返回，但仍受 F2 持久化约束。启动默认不带该 guard；原 C2 仍允许真实 10:00:59→10:01:13 调用入场，并拒绝未来分钟。maintenance 自己的活动不被算作新的实时任务。

直接执行及真实 composition shutdown 对照包含 wrapper 尚未进入 SDK 和已进入 SDK 两个窗口。`begin_shutdown` 同步设置尝试 token，早于取消；drain 前保留数据库及物理槽位，晚写为零。取消保留晚权限失败记账，再重新抛出。真实 SDK 等待中的 reactivate 拒绝旧行；稍后重新捕获的 scope 可恢复。这些是组件/ownership 对照，不是 F3-C scheduler progress 证明。

## SRE-04 — TDD 证据

TDD/增量/安全/Git 约束使改动保持在批准范围。fixture 修正（补齐日历内存缓存、使用 adapter 识别的 requests connection exception 而非内置异常）不计产品修复。

| 窗口 | 证据 |
| --- | --- |
| 缺少 unit 入口 | 4 failed，1 warning，2.16s；随后 4 passed，1 warning，1.94s |
| 预留恰界及真实 wrapper 越界 | 3 failed，5 passed，1 warning，2.91s；随后 8 passed，1 warning，2.59s |
| 原请求异常 / retry+retarget | 14 failed，9 passed，1 warning，5.61s；随后 23 passed，1 warning，4.87s |
| root 发现的同分钟回拨 + 已批准旧 owner 终止 | 4 failed，32 passed，1 warning，8.28s；随后 36 passed，1 warning，7.92s |
| unknown 目标 retry 在同步和领取之间到期 | AttributeError RED：1 failed，57 deselected，1 warning，1.72s；guard 后 GREEN：1 passed，57 deselected，1 warning，1.49s |

root 和独立 Sol 在实现前批准请求异常保留接口及严格约束的退休谓词。没有放宽 generic 错误政策。中间 47/53/57 运行早于最终 unknown-target guard，不是最终验收证据。

## SRE-05 — 作者最终验证

命令从 `trade-plan-monitor` 执行；仅使用离线 SDK 及临时数据库。各运行独立，不相加。

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_execution.py', '-q', '--tb=short']))"
```

**58 passed，1 warning，13.05s**。import blocker 确认不依赖未跟踪 A07；helper 来自已提交 F2/F3-A 及既有 fixture。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_frozen_startup_recovery.py tests/integration/test_s3_stock_recovery_owner.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_runtime_recovery_storage.py tests/unit/test_runtime_reconciliation.py tests/unit/test_recovery_targets.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

直接相邻：**184 passed，1 warning，41.83s**。原 A07：**11 passed，2 failed，11.98s**，仅 A-empty/B-missing-0931 自主进展仍 RED。原截止点/oracle 对照均通过；未放宽断言、skip 或 xfail。

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/runtime/recovery.py tests/integration/test_s3_stock_recovery_execution.py
git diff --check
```

二者通过，属于限定范围而非全项目。既有 Starlette/httpx 弃用 warning 保留。没有重跑无关的 350 项权限矩阵。

## SRE-06 — 冻结候选与独立评审

Sol 独立评审及最终 hash 核对已批准五文件候选，无 P1/P2。其独立的禁止 A07 import 运行结果为 **182 passed，1 warning，52.58s**：58 项 F3-B execution、35 项 F3-A owner、65 项 F2 frozen recovery 及 24 项纯 schedule 测试。独立原始命令为：

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_execution.py', 'tests/integration/test_s3_stock_recovery_owner.py', 'tests/integration/test_s3_frozen_startup_recovery.py', 'tests/unit/test_runtime_reconciliation.py', '-q', '--tb=short']))"
```

三个源码/测试路径的限定 Ruff 及限定 diff 检查通过。评审者未独立重跑原 A07；SRE-05 的 11 passed / 2 failed 仅为作者证据。评审期间源码/测试 hash 保持不变。实现作者没有提交；root 保留提交权限。

| 路径 | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `CD1DDCE27C7C1C42BBABE0029039B334A921CE4C5B0836AE231FA5877E66B7E6` |
| `src/trade_plan_monitor/runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `tests/integration/test_s3_stock_recovery_execution.py` | `FF468865FD618D51231B4B9DB84815CD6276346BB393CD732376337E951E9AA3` |

F3-C 仍需真实同 generation 自主前缀恢复及 10:05:12 求值、maintenance 行情游标/已过复查接线、启动 ticket 记账、index-only 兼容，以及合法求值前 public 状态不可操作。C1 和通用 dispatcher/政策变更仍不在范围。
