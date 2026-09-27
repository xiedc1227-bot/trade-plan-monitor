# S3 自动权限维护停机

## 状态与依赖

作者结果：**1 passed, 1 warning in 6.68s**。独立静态审查与复跑：**限定通过**，**1 passed, 1 warning in 6.53s**，本用例无 P1/P2 发现。这是新增 UPD-R16 连接验收用例，不是 baseline RED 或生产修复。仅新增 `tests/integration/test_s3_scheduled_permission_shutdown.py` 及本双语报告。

实测 checkout 为 HEAD `54b70f6aad10770346697637386de8a22d136633` 加 `runtime/production.py` 与 `web/monitor_composition.py` 的 UPD-S4 候选改动。测试从**尚未提交**的 `tests/integration/test_unified_permission_running.py` 导入稳定 helper `_composition(..., stock=False)`；另复用已提交 `test_s3_permission_reservation_process.py` 的 R17 快照 helper；S4 helper 使用已提交 composition、A07 时钟与 proof-frame fixture。本测试／报告组必须与获验收的 S4 源码／helper 同批或紧随其后提交，不能独立提交到上述 HEAD。

## R16-P01 — 真实 RUNNING owner 与晚证明

1. 创建真实 index-only composition、临时 SQLite、合法 liveness、当前开市 SSE 日历及完整历史锚点。仅 seed 一个在 `2026-09-08 10:00:16+08:00` 到期的 `INDEX_HISTORICAL_MINUTES` latch。Seed 是 fixture 输入，不是实测预约。Startup 为 RUNNING、SDK 零调用、checkpoint 不变。
2. 停驻并释放原 scheduler 实际的首次等待。其 `INDEX_PERMISSION` 职责通过已属于 `runtime._work_tasks` 的任务进入 common 路径；测试不直接调用私有 unit 或 `run_deadline`，也不手工登记 work task。权限锁已持有，`_running_deadline` 保持 false。
3. 在 worker thread 内暂停真实假 `idx_mins` SDK 函数体。恰好一次 SDK 已进入；真实 controller 已将 seed 持久替换为 `10:05:16`（`actual due + 300 seconds`），并推进原 scope 游标。物理槽位数为 1，排队数为 0。
4. 调用真实 `composition.stop()`。在原同步 `begin_shutdown` 返回后的透明观察确认：`business_commit_admission_open` 及捕获 generation 的准入均为 false，controller 已关闭，而 owner 与 runner 均尚未取消。此处断言既有权限准入撤销，不是股票恢复 token 协议。
5. 保留真实 **5.0 秒**宽限期；硬断实际 owned-task 取消前至少经过五个单调时钟秒。取消后逻辑权限锁已释放，但 shielded proof 仍未结束，SDK 仍暂停，物理数仍为 1，数据库仍打开／READY，尚未 disposal，stop 尚未完成。无额外 SDK 调用、业务或 checkpoint 变化。
6. 释放 SDK。完整合法的 48 行历史响应通过真实 provider proof 函数，但最终 cancelled-owner 校验以 `RequestControlError(INVALID_RESPONSE)` 拒绝它。该响应不能解除原权限 latch，也不能抹除／改变持久预约。这是最终 owner 拒绝，不是声称 frame 格式错误。
7. 真实 SQLAlchemy `engine_disposed` 事件仅在已释放、物理／排队数为 0、permission rechecks 为 0 且 owner 完成后发生。Stop 完成时原 runner 已结束、owned tasks 为空、controller 槽位／rechecks 为空、数据库 STOPPED，runtime generation 不变；无 runner failure、替换或 cleanup failure。

实际硬观测的边界顺序为：

```text
admission-before-cancel
owner-cancelled
sdk-returned
valid-proof-returned
database-disposed
```

从维护职责开始前，到暂停／取消／释放／停止各边界，比较含时间戳的完整应用表行。业务快照只排除 schema 元数据、runtime liveness 和 provider-recovery 记账；provider checkpoint 另作精确比较。Evaluation/risk/HOLD/delivery/audit 状态、市场 facts、quotes 和 index snapshots 均保持不变。保留真实 market-window 检查、controller pacing、timeout、liveness 与 stop/drain 实现。

## 命令与冻结候选证据

从仓库目录运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --no-index --check -- NUL tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --no-index --check -- NUL docs/verification/2026-09-27-s3-scheduled-permission-shutdown.md
git diff --no-index --check -- NUL docs/verification/2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md
```

作者 target：**1 passed, 1 warning in 6.68s**。Warning 来自导入的 FastAPI/Starlette test client 既有 `httpx` 弃用提示；未发出真实请求。目标 Ruff 通过；空白检查通过，仅有 Git 通常的 LF/CRLF 提示。

源码作者为此轮冻结了两个源码接线点及共享 helper 接口。Pytest 前后记录完整 JSON hash，`Compare-Object -Property Path,Hash` 对以下六个源码文件和两个测试文件未发现差异：

| 文件 | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `web/monitor_composition.py` | `A716E8B068919E5C2AD2D68F19CA65BB115F616795E1CB7E7B2B6822D6B00567` |
| `runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_unified_permission_running.py` | `8DEB7456B0FC71A8B2C4B8871246EC6A1EC00C6E6F8F3B407234558F3E50E173` |
| `test_s3_scheduled_permission_shutdown.py` | `77985619DB2B059145A6F44EBE0645C2D85586176364524625E3B3B302BFFFDD` |

源码路径相对于 `src/trade_plan_monitor/`；两个测试路径均位于 `tests/integration/`。这是连贯候选证据，不是 clean-HEAD 运行或完整 S4 批准。后续源码／helper 改动需要新的连贯末版窗口。

### 独立验证

独立审查者完整阅读测试并复跑上述同一 target 命令：**1 passed, 1 warning in 6.53s**，同为 Starlette `httpx` 弃用 warning。真实 scheduler／owned-task、先撤销准入再取消、五秒宽限期、晚 proof 拒绝、先排空后 disposal 各边界均未发现 P1/P2。目标／共享 helper Ruff 及 diff 检查通过。

独立采样的八个路径完整前后 JSON hash 一致：`runtime/production.py`、`runtime/scheduler.py`、`runtime/service.py`、`runtime/recovery.py`、`runtime/recovery_targets.py`、`web/monitor_composition.py`、共享 S4 测试和停机测试。Production、scheduler、service、composition 和停机测试的 hash 与作者表一致。独立源码采样包含下列两个文件，代替作者的 `runtime/request_control.py` 与 `state/runtime_recovery.py`；仅由作者采样的文件不重标为独立采样：

| 文件 | SHA-256 |
|---|---|
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |

共享 S4 测试文件在两轮之间有改动，但本独立窗口内稳定为 `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7`。这是独立的候选窗口，不替换作者记录的 helper hash；重叠的单例计数不相加。S4 源码／helper 落地依赖及仅 RUNNING 的限制均不变。

## 限制

仅覆盖一个 RUNNING 历史指数权限代表，不关闭 DEGRADED 停机连接、全部八 scope 组合、UPD-S4/S5、C1 或整体 S3 门禁。既有组件取消与股票恢复停机测试仍是独立证据，不与本片计数相加。仅使用临时 SQLite 和本地 fake SDK 数据。本改动不含源码／旧测试修改、新停机政策、强制终止 SDK、热重载、真实服务、用户数据库、通知、部署或提交。
