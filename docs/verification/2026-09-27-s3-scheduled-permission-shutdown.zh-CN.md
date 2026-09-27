# S3 自动权限维护停机

## 状态与依赖

测试覆盖 RUNNING 与 DEGRADED 各一个真实 `INDEX_HISTORICAL_MINUTES` 停机代表。本扩展已独立**限定通过**，无 P1/P2 发现；两个 mode 均纳入最终固定源码的组合运行：**82 passed, 1 warning in 16.52s**。这不是单独两个停机用例的耗时。较早作者的 **2 passed, 1 warning in 12.09s** 仍是 **UPD-S5 中间候选**观察。固定提交全回归及最终集成审查仍待完成，C1/C3 保持 OPEN。这是 UPD-R16 连接验收，不是强造 baseline RED 或生产修复；仅修改停机测试及本双语报告。

本扩展实测于 HEAD `7abed318a3239ca529e699618a946018810c5009` 加 UPD-S5 候选源码和**尚未提交**的 `tests/integration/test_unified_permission_degraded.py::_degraded_composition` helper。保留已提交的 S4 `_composition(..., stock=False)` helper 与 R17 业务／checkpoint 快照 helper。本扩展必须与获验收的 S5 源码／helper 同批或紧随其后提交，不能独立提交到该 HEAD。较早作者窗口中的 related-controller-floor／revoked-wait 工作尚未完成，但已包含在下列末版独立源码窗口内，不再是该检查点的实现缺口。

### 历史 RUNNING-only 窗口

作者结果：**1 passed, 1 warning in 6.68s**。独立静态审查与复跑：**限定通过**，**1 passed, 1 warning in 6.53s**，该用例无 P1/P2 发现。实测 checkout 为 HEAD `54b70f6aad10770346697637386de8a22d136633` 加 `runtime/production.py` 与 `web/monitor_composition.py` 的 UPD-S4 候选改动。S4 共享 helper 当时尚未提交，使用已提交 composition、A07 时钟与 proof-frame fixture。该 RUNNING 测试／报告组后来已随 S4 落地；保留下列历史证据，不重标为新的两 mode 运行。

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

## R16-P02 — 真实 DEGRADED owner 与不变的启动期限

1. 复用 S5 composition fixture，仅有 `TRADING_CALENDAR` 与 `INDEX_HISTORICAL_MINUTES` 两个 latch 在 `2026-09-08 10:00:16+08:00` 到期。Fixture 提供完整已提交股票分钟 prefix、合法 semantics／certification 及真实 liveness。实际 startup calendar reference 被权限阻断：startup 返回 DEGRADED，原因是 `REFERENCE_REFRESH_FAILED`／`REFERENCE_BLOCKED_PERMISSION`，`_accepting_work` 为 false，SDK 零调用，seed checkpoint 不变。Pipeline 已存在，原 startup retry 保持 `NOW + 30 seconds`（`10:00:45`）。
2. 仅停驻并释放 `10:00:16` 的真实 lifecycle retry wait；其 fixture 推进时钟并调用真实 `state.heartbeat()`。生产循环先修复 calendar，再在同一时刻通过真实 `INDEX_PERMISSION` owned task 进入历史指数 proof。两个实际维护职责恰好依次观测到 `trade_cal`、`idx_mins`。测试不直接调用 unit／deadline，不修改 runtime 状态，不开启普通工作，不手工登记 owned task。
3. 历史 SDK 暂停时，状态仍为 DEGRADED，`_accepting_work` 仍为 false，已安装 pipeline 和 runtime generation 不变，原 startup retry 仍为 `10:00:45`，普通 market clock 没有等待。既有 stop／generation 准入合法允许权限工作，没有伪造新准入能力。Calendar 已解除阻断，但历史权限仍 blocked，并保留真实持久预约 `10:05:16`。含已提交分钟 prefix 的完整业务行保持不变。
4. 原样应用 R16-P01 的真实 stop、五秒宽限期、取消、晚合法 proof 拒绝、预约保留、物理槽位排空及 engine disposal 断言。无后续 SDK 或业务写入。最终为 STOPPED，无 runner failure、runtime 替换或 generation 变化。

本用例有意在原 startup retry 前停止，证明 DEGRADED 权限停机连接，不证明后续 DEGRADED-to-RUNNING 启动恢复。共享停机 oracle 参数化未削弱 RUNNING 分支。

## 历史命令与冻结 RUNNING 候选证据

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

共享 S4 测试文件在两轮之间有改动，但本独立窗口内稳定为 `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7`。这是独立的候选窗口，不替换作者记录的 helper hash；重叠的单例计数不相加。该历史独立结果仅覆盖 RUNNING，且当时具有上述 S4 源码／helper 落地依赖。

## 两 mode 的 S5 中间候选证据

从仓库目录运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --check -- tests/integration/test_s3_scheduled_permission_shutdown.py docs/verification/2026-09-27-s3-scheduled-permission-shutdown.md docs/verification/2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md
```

作者 target：**2 passed, 1 warning in 12.09s**。Warning 同为导入的 Starlette `httpx` 弃用提示。目标 Ruff 与限定路径 diff 检查通过。未发出真实请求。计数与历史 RUNNING 证据重叠，不相加。

源码作者协调了短暂的 source／helper 冻结。下列九个路径的完整前后 JSON hash 全部一致；pytest 完成后的 `Compare-Object -Property Path,Hash` 未返回差异。源码路径相对于 `src/trade_plan_monitor/`；测试路径均位于 `tests/integration/`。

| 文件 | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `runtime/service.py` | `EB6EFACDE9821E7AD0D739DBB1B6FA532D744A1740C0D767C6C0F0784F796106` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |
| `test_unified_permission_degraded.py` | `6F4F3685AD0DDC2047F19ECE9204725C83C2A08EF680842F68FC66E755609A80` |
| `test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |

这不是 clean-HEAD 或最终 S5 运行。下列末版独立章节记录后续 source／helper 改动后所需的两 mode 复跑；历史 RUNNING-only 独立审查不重标为 DEGRADED 扩展的批准。

## 最终独立固定源码验证

独立审查者静态审查两个停机 mode，无 P1/P2 发现，并执行以下精确组合命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_degraded.py tests/integration/test_runtime_lifecycle.py tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
```

结果：**82 passed, 1 warning in 16.52s**，包含 29 个 DEGRADED 用例、51 个 lifecycle 用例及本片 2 个停机 mode。Warning 为既有 Starlette `httpx` 弃用提示。这是组合耗时，不是单独计时的两用例停机运行。Ruff 与限定路径 diff 检查通过。这些重叠观察不与此前计数相加。

审查者确认以下精确十个路径的完整前后 JSON hash 一致。本独立采样包含 `runtime/recovery.py` 与 `runtime/recovery_targets.py`，不包含仅在作者集合中的 `runtime/request_control.py`／`state/runtime_recovery.py`。源码路径相对于 `src/trade_plan_monitor/`；测试路径均位于 `tests/integration/`。

| 文件 | SHA-256 |
|---|---|
| `runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `test_unified_permission_degraded.py` | `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125` |
| `test_runtime_lifecycle.py` | `6095D74B06D6718DAA26D100AD332F2175222319F9B07277F5E545E2C608D159` |
| `test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |
| `test_unified_permission_running.py` | `BA2C4F2FFA815869D480C9E2BF9A1FEF5EBC878EE45D13FBA5A1F4ACB08372E7` |

末版窗口包含 related-floor／revoked-wait 修正及最终 DEGRADED 测试；停机测试保持作者两 mode 的 hash 不变。它验证两个停机代表在该获验收 S5 候选上的表现，不是固定提交总体验收，也不关闭 C1/C3。源码／helper 落地、固定 HEAD 全回归及最终独立集成批准仍是分别待过的门禁。

## 限制

覆盖 RUNNING 与 DEGRADED 各一个已经独立审查的历史指数权限停机代表。本报告本身不关闭全部八 scope 组合、UPD-S5、C1/C3 或整体 S3 门禁。既有组件取消、股票恢复停机及更广的 S4/S5 测试各自保留验收范围，即便纳入同一命令也不与本片计数相加。仅使用临时 SQLite 和本地 fake SDK 数据。本扩展不含源码／无关测试修改、新停机政策、强制终止 SDK、热重载、真实服务、用户数据库、通知、部署或提交。
