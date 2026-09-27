# C1 UPD-S3 — 统一权限调度

## 状态与范围

配对 `2026-09-27-c1-unified-permission-dispatch-contract` 已批准。实现基于 UPD-S2 `9796b15469b8e3bc9aa12a3425aae053e56bebfc`。最终作者与独立源码/测试验证及双语报告一致性通过，无剩余 P1/P2。本片不代表 C1 完成，也不代表 RUNNING/DEGRADED 八 scope 自动恢复验收。

本片仅修改 `src/trade_plan_monitor/runtime/production.py`，新增 `tests/integration/test_unified_permission_dispatch.py`，窄迁移现有股票分钟/涨跌停/指数日线权限测试，并新增本报告对。provider、controller、scheduler、service、composition、startup 与 proof parser 不变。R17 clean-process 测试/报告由另一作者单独记录评审；它们依赖本共同入口，不是独立 clean-HEAD 实现。

精确负责路径：

- `src/trade_plan_monitor/runtime/production.py`
- `tests/integration/test_unified_permission_dispatch.py`
- `tests/integration/test_production_stock_minute_permission_execution.py`
- `tests/integration/test_production_daily_limits_permission_maintenance.py`
- `tests/integration/test_production_index_daily_permission_maintenance.py`
- `docs/verification/2026-09-27-c1-unified-permission-dispatch.md`
- `docs/verification/2026-09-27-c1-unified-permission-dispatch.zh-CN.md`

测试使用离线 SDK 响应、真实认证 wrapper/controller 与临时 SQLite。未使用真实服务、用户数据库、依赖升级、部署或推送。root 保留提交权限。

## 实现边界

`run_permission_maintenance_unit()` 与八个命名兼容入口共用一次调用的原 Task/Event 和 `_permission_maintenance_lock`。共同选择器按全局 raw-due/RR 选唯一赢家；命名输家不能执行赢家或准备另一 scope。私有 held body 不重复获取锁。durable `on_reserved` 仍是唯一确认点；每 unit 至多一次预约/SDK 调用。原 O/F 与独立股票 symbol 游标规则保留。

到期但不可用的 scope 获得固定本地复查时间，未选中的就绪兄弟仍可到期。共用纯内存 effective-floor helper 纳入两个旧 index 字段、本地 map、raw permission floor 与 shared cooldown。cheap getter 不读时钟、文件或 SQL。慢不可用检查在完成时重新观察时间，设置未来 30 秒本地唤醒；重复未到期调用不滑动期限。这不会重新捕获或延长冻结的 15 秒入场窗口，也不会缩短已经成立的具体重试 floor。

DAILY_BARS 使用 synthetic scope rank 参与，再执行恰一次 fresh preparation（一个历史页、至多十次 receipt 检查）。同一不可变 preparation 传入 held body。测试证明 broad symbol A 无需求时可得到实际 symbol B 的合法 receipt；没有 broad anchor 仍执行一次 preparation。全局 authority 撤销先抛 `RecoveryAdmissionChangedError`，再考虑普通 generation 退休；仍获授权但旧 generation 跳过且不预约。selected preparation 中退休只恢复自己本次新增的时间值，不撤销其它 scope 之前合法的检查。held-body 的 candidate/authority/anchor 读取也先按同顺序检查 admission gate，再解释不可用证据。SQL 异常仍传播；请求后的 DEFERRED/FAILED 不改为正常退休。

其余五 owner 在最终 authority I/O 后重查原 owner 取消状态，daily-limits/index-daily 还在响应 SQL 后设置 guard。worker 的取消检查使用 invocation Event，不检查 Task；保留既有 authority I/O 和各 scope 的 physical-start 围栏，worker 不执行 SQL。取消释放维护锁，但不会归还仍运行的物理槽；晚成功不能清除权限。只有 `BLOCKED_PERMISSION`、`RATE_LIMITED`、`TRANSIENT`、`TIMEOUT`、`INVALID_RESPONSE` 转为 `FAILED`，并保留具体 `next_retry_at`。`ERROR`、`CLOSED`、`QUEUE_FULL`、存储/回调/编程错误传播。普通 `_request(TRADING_CALENDAR)` 的 inline recheck 已删除；它不能预约或探测权限。

## RED 历史与夹具区别

全程目标命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_dispatch.py -q --tb=short
```

- 初始四例：**4 failed, 1 warning, 2.98s**（缺共同 API、普通 calendar inline probe），随后 **4 passed, 1 warning, 3.07s**。
- 最终 authority 取消、严重错误传播与全局 admission 控制在实现前失败。中途扩展批次混有非法 index-daily 响应/参数夹具和缺少必填异常 `attempts`；这些夹具失败不算产品修复。独立具体 floor 命令 `-k concrete_error_retry_floor` 得到 **5 failed, 29 deselected, 1 warning, 5.18s**。修正后 34 例检查点为 **34 passed, 1 warning, 24.83s**。
- selected preparation 退休：`-k selected_preparation_retires`，**4 failed, 34 deselected, 1 warning, 4.38s**；按批准的不可变传递/准备后 gate 修改后为 **4 passed, 34 deselected, 1 warning, 4.30s**。
- 共同快速入口遗漏旧 index 字段产生两条正式 `legacy_index_floor` 失败。慢 B1 与 UNKNOWN preparation 产生两条正式 `slow_unavailable` 失败：在合并 synthetic-rank 窗口中为 **2 failed, 2 passed, 41 deselected, 1 warning, 2.53s**。DAILY_BARS harness 最初未绑定 durable repository；补上真实临时 repository 是夹具准备，不是产品修改。随后完整检查点为 **45 passed, 1 warning, 30.61s**。
- 真实 resolver/SDK-held 取消、真实 provider 分类与 common/named 确认：**36 passed, 45 deselected, 1 warning, 30.39s**。下一完整检查点为 **87 passed, 1 warning, 66.30s**；此结果早于后续 held-preparation authority 控制，不是最终验收。
- 自审进一步发现 held-body 准备过程中 authority 失效。修正后的正式 `-k held_preparation_authority --tb=line`：**10 failed, 87 deselected, 1 warning, 9.36s**，随后为 **10 passed, 87 deselected, 1 warning, 9.83s**（`--tb=short`）。此前一次误把 DAILY_BARS 而非 INDEX_DAILY 纳入两个参数，不是干净的十例 RED 窗口。六条实际 selected-anchor SQL 控制及一条 SQL 错误/退休同时发生控制为 **7 passed, 97 deselected, 1 warning, 6.30s**（`-k 'selected_real_anchor or preparation_sql_failure'`）。
- 独立评审确认两个股票分钟 held pre-controller 检查及 DAILY_BARS 两个 held 认证检查中仍有相同 P2。正式 `-k prepared_owner_certification_io --tb=line`：**8 failed, 104 deselected, 1 warning, 7.88s**，随后为 **8 passed, 104 deselected, 1 warning, 8.21s**（`--tb=short`）。每例调用真实 authority validator、仅准备一次、保留 raw floor/SDK-zero/ack-zero，正常退休不新增 defer。三处 owner-thread 布尔检查先执行有序 global gate，再解释局部 false；controller admission、worker、response 与已预约结果不变。评审者另行 stdin 诊断不计为 pytest RED。

最初五文件相邻批次为 **3 failed, 320 passed, 1 warning, 94.91s**。Sol/root 批准两项窄迁移：sparse 股票分钟测试区分一个共同选择事务与原两个执行事务，保留精确 1001 日期/五个分块/一个响应快照/禁止 `_work`；不可用的命名 DAILY_LIMITS 输家期待 SKIPPED，同时保留固定本地时间、不变 raw floor/游标、SDK 零调用和合法 index 兄弟。两项控制结果为 **2 passed, 1 warning, 2.29s**。generation-false index-daily 原 SKIPPED 断言未迁移，由源码 admission 逻辑修复。

之后相邻窗口为 **4 failed, 319 passed, 1 warning, 96.24s**：旧 DAILY_LIMITS 撤销/generation 预期及两个 queued CLOSED 预期与批准的 typed 撤销/正常退休/严重错误传播边界冲突。Sol/root 仅批准对应预期迁移：恢复文件后重复撤销仍抛 typed；旧 generation 不新增 defer；queued stop 传播原 CLOSED（核对 operation 与零物理 attempts）。queue-abort 仍 DEFERRED。保留原 raw/floor/block/cursor/SDK-zero 控制。两文件定向 `-k 'restored_stock or no_authority or stop'`：**5 passed, 47 deselected, 1 warning, 4.05s**，包含不变的 index generation 控制。这些是政策对齐夹具，不是新增产品修复。

## 最终验证

最后 P2 修复前，源码 `89E6821719286359D33D3640E2D381FACBA9A80030770DC9B015D6AA3BC3E68D` 获得 **106 passed, 1 warning, 87.47s**（104 条共同控制，加 2 条 R17）及 **323 相邻 passed, 1 warning, 98.65s**。同一旧窗口的独立目标验证为 **106 passed, 1 warning, 86.75s**，11 个 hash 不变。这些明确为修前结果，不是最终验收。重叠计数不可相加。现有 warning 是 Starlette 的 `httpx` 弃用提示。

下方冻结 hash 的最终作者结果：**114 passed, 1 warning, 94.52s**（112 条共同控制，加 2 条 R17）；**323 相邻 passed, 1 warning, 98.89s**。两个批次中源码/测试 hash 保持不变。

最终目标包含独立作者的 R17 用例：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_dispatch.py tests/integration/test_s3_permission_reservation_process.py -q --tb=short
```

冻结源码/测试 SHA256：

| 文件 | SHA256 |
|---|---|
| `production.py` | `E20702C1E50C07F8E5FA20E03F49AFB31FF721BA560169BC13DB11338E42A47E` |
| `test_unified_permission_dispatch.py` | `7738D92C7CCC26D1F59C94260430CD86E67A65F9B759C8BF06EED4CBBBC93584` |
| `test_production_stock_minute_permission_execution.py` | `3D6ECFFDD110B07EE0EA93F24AE583637D5612EBCA29549ACB216389EE7C1791` |
| `test_production_daily_limits_permission_maintenance.py` | `9C41C3B8C2B0DE75F92A1D5475B18F67830994846ACE5C24A8D4A92F10768D79` |
| `test_production_index_daily_permission_maintenance.py` | `8CC53070DE0C0CC120995C5EC07AD68438C6466729F94B2C0DF1C5DB4C63F1A3` |

直接相邻命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_legacy_owners.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py -q --tb=short
```

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_unified_permission_dispatch.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py
git diff --check
```

两项检查通过。源码 diff 体量主要来自现有 owner body 去除一层锁缩进；`git diff -w` 可分离逻辑修改。此固定作者窗口无并行源码作者修改。

## 独立评审与剩余工作

Sol 独立执行上方完全相同的最终两文件目标命令：**114 passed, 1 warning, 95.33s**。上方完全相同的五文件相邻命令独立得到 **323 passed, 1 warning, 98.45s**。两条命令退出后，全部 11 个源码/测试完整 SHA256 与执行前 JSON 一致：上方五个负责路径、不变的 scheduler/service/recovery/recovery-targets/composition，以及 R17 测试 `C634BB3D21E01FCAE2E559FE42A6055C9D9DD9F431ABC5E4210289E256F18B4A`。六路径 scoped Ruff（production、dispatch、minute、limits、index-daily、R17）及 `git diff --check` 通过。三个预约前 gate 位置已修复，独立源码/测试评审无剩余 P1/P2。双语报告一致性通过。两组独立计数分别记录，不相加为测试总数。

此前 S2 取消及 calendar work-key P2 回归均保留在相邻套件。R17 独立 `2026-09-27-s3-permission-reservation-process` 报告负责真实 sequential-process 证据：原独立 2 例窗口使用源码 `1AD6922F...`，不是上方最终源码。最终 114 例窗口包含这两例，不重标旧独立结果。私有组件测试不能替代 R18 自动恢复。

S4/S5 仍负责 scheduler/composition/common getter 接线、`INDEX_PERMISSION` dispatch 分支、真实 RUNNING/DEGRADED 八 scope 唤醒、lifecycle/restart/无忙循环验收及完整 UPD-R01..18 关闭。本片不新增 loop 或默认自动 common 调用。

实现依据批准契约及本地已安装源码。Python 文档说明了 [asyncio lock ownership](https://docs.python.org/3.14/library/asyncio-sync.html#lock) 与 [Task cancellation counts](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.Task.cancelling)；取消检查留在 owner loop。既有 provider proof 语义和 physical-start 窗口不跨 operation 泛化。
