# C1 UPD-S5 — DEGRADED 权限维护

## 状态与范围

本实现基于源码 `2dfa902`；当前 HEAD `7abed31` 仅追加任务文档。独立源码/测试评审及最终报告语义一致性检查通过，无剩余 P1/P2。本片实现已批准的 [UPD-07/08](2026-09-27-c1-unified-permission-dispatch-contract.zh-CN.md)，不代表关闭 C1/C3 或最终全量门禁。

作者拥有六个路径：`src/trade_plan_monitor/` 下的 `runtime/service.py`、`web/monitor_composition.py`；`tests/integration/test_unified_permission_degraded.py`；窄范围迁移的 `tests/integration/test_runtime_lifecycle.py`；以及本报告双语文件。另由独立作者维护的[调度权限停机](2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md)测试/报告追加 DEGRADED 停机代表。不改 pipeline、scheduler、provider、schema、公共状态、阈值、依赖、真实服务或用户数据库；不推送/部署。

## 不变量与实现

- 可选 `next_permission_maintenance_at` 回调默认返回 `None` 期限，并保留布尔值为假的合法 callable 对象。生产绑定与 RUNNING 相同的纯 composition getter。非法回调/结果仍是编程错误。
- 既有生命周期 owner 从实际完成时刻按 30/60/120/300 秒固定启动期限。权限唤醒不增加启动次数、不缩短或滑动启动期限，也不改变公共 `next_retry_at` 含义。两期限均到期时先执行一次启动，正常失败后至多一个合法权限单元；权限超时跨越期限后只执行一次逾期启动，不补播、不并行。
- 后来的共享冷却和真正相关操作的期限可延长固定期限。私有有界枚举集合只记录真实可重试 `RequestControlError.operation`，包含初始参考数据/恢复的两个失败。不从缺失能力推测操作，也不扫描无关 raw floor。参考数据及恢复均实际成功才清理旧依赖；新 RUNNING→DEGRADED 过程替换集合；清理不得缩短已固定期限。不保留异常对象。
- 权限工作沿用 `_execute_deadline` 与 `_work_tasks`。不会开启 `_accepting_work`、在 DEGRADED 执行普通行情，或单独将 DEGRADED 改为 RUNNING；只有到期完整启动成功才能恢复。保留既有 pipeline、锁、本地 defer、全局/O-F/两个 symbol 游标状态及 generation。
- 真实 heartbeat 可在重试等待期间发布 NEEDS_RESTART。初始只读运行分支现在返回前复用既有显式停止等待；已请求停止仍可立即释放。严重错误及取消保留原清理方式，不增加后台协调器。

任务归属/取消依据本地 Python 3.14 实现及官方 [asyncio task 文档](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.create_task)、[Event 文档](https://docs.python.org/3.14/library/asyncio-sync.html#asyncio.Event)。未升级依赖。

## RED 证据与夹具区别

首轮四个生命周期测试结果为 **4 failed in 0.98s**：延迟进入会滑动已发布启动期限，同时尚缺可选权限时钟。最小期限/回调实现后为 **4 passed in 0.78s**；扩展后为 **18 passed in 0.77s**。这些是历史组件窗口，不是最终集成总数。

真实相关/无关 controller 测试为 **1 failed, 1 passed in 2.38s**：calendar 权限在 +1 失败后将 raw floor 持久化延至 +301，但相关启动仍只等待 +30；无关 history floor 正确保留启动期限。独立批准的有界依赖集合修复此 P2。初始双错误/None floor/依赖清理控制先为 **3 failed in 1.42s**，修复后通过。

临时 token 文件真实变化经 worker 验证、实际 heartbeat 在旧重试等待释放前发布 BLOCKED，得到 **1 failed in 1.84s**：runner 未等显式停止即退出。已批准的早返回修正关闭此 P2。此前夹具同时执行手动和实际 heartbeat，发生 liveness revision 竞争；该夹具问题不是上述产品 RED。最终用例在该边界仅使用实际 heartbeat loop。

真实八 scope 首版夹具缺少已提交股票 prefix，正确触发既有 blocked startup recovery 失败；随后用临时数据库合法 prefix 事实修正，未放宽产品门禁。既有 lifecycle 夹具的时钟一致化经独立批准：仅真实默认 TIMEOUT 按收到的 delay 推进虚拟时钟，另修正一个显式 before-shutdown TIMEOUT 用例。SHUTDOWN/取消及原 stop/error 断言全部保留。迁移后该文件单独 **51 passed in 1.17s**。

## 候选验证

全部命令在仓库根目录执行，使用离线假 SDK 和临时 SQLite。

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_degraded.py tests/integration/test_runtime_lifecycle.py tests/integration/test_s3_scheduled_permission_shutdown.py -q --tb=short
```

最终作者目标：**82 passed, 1 warning in 16.64s**（29 个 S5 用例 + 51 个既有 lifecycle 用例 + 2 个真实停机模式）。实际 DEGRADED composition 经归属明确的 INDEX_PERMISSION 唤醒执行全部八 scope，每单元一个 SDK、仅清自身权限、权限路径业务数据精确零变化、owner/generation 不变，并在后续完整启动成功恢复。全部证明完成后，实际公共健康仍为 DEGRADED/只读，显示原启动重试时间；合法评估前 dashboard 和 websocket 仍不可操作/非 live。真实 both-due 失败及 429 用例保留新持久化 300 秒期限；真实严重 ERROR 进入清理。小型时钟测试覆盖递进、同刻、超时跨越、非法回调及严重错误身份。

最终仅测试追加驱动合法未配置、无 pipeline 的 composition，在 +30/+90 执行启动重试并发布下一 +210 期限，配置/owner 不变、getter 为 `None`、SDK 与维护次数均为零。不引入或承诺在线安装认证：初始合法 bootstrap 仍沿既有 start 路径；冻结时缺 revision 的 baseline 后来出现新语义 revision 仍需重启。两项新增/加强检查首次 **2 passed in 2.91s**。追加前相同源码的目标结果为 **81 passed, 1 warning in 16.36s**，测试 hash 为 `53B2AB4794E84F7C36A2292096363BC6A126A90535FE14A2BFBDC647C13D29A2`；该历史窗口单独保留。

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_running.py tests/integration/test_production_a04_retry_timeline.py tests/integration/test_s3_installed_runtime_read_liveness.py tests/integration/test_monitor_production_composition.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/unit/test_monitor_runtime.py -q --tb=short
```

作者：**161 passed, 1 warning in 31.47s**，使用最终源码，但早于上述仅测试追加。包含已提交的纯 absent-pipeline 适配测试与真实离线 DEGRADED composition 健康测试。不同窗口计数不得相加，也不得将后来的目标测试 hash 归到此前窗口。

```text
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/service.py src/trade_plan_monitor/web/monitor_composition.py tests/integration/test_runtime_lifecycle.py tests/integration/test_unified_permission_degraded.py tests/integration/test_s3_scheduled_permission_shutdown.py
git diff --check
```

两项通过。warning 是既有 Starlette/httpx 弃用提示。最终作者 82 目标窗口前后完整 SHA256 如下且相同；此前 81/161 窗口除已明确记录的早期目标测试 hash 外，其余值相同：

| 路径 | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `tests/integration/test_runtime_lifecycle.py` | `6095D74B06D6718DAA26D100AD332F2175222319F9B07277F5E545E2C608D159` |
| `tests/integration/test_unified_permission_degraded.py` | `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125` |
| `tests/integration/test_s3_scheduled_permission_shutdown.py` | `D184921AFF0363C11120DAFEC70B7154F98ADEE568758DDD57D9C23214A0B561` |

## 独立评审与剩余门禁

两项窄修复均在实现前获独立批准。评审者在测试追加前窗口报告上述相同命令：目标 **81 passed, 1 warning in 16.38s**，相邻 **161 passed, 1 warning in 31.52s**，十个相关源测 hash 稳定，Ruff/diff 通过，源码无剩余 P1/P2。

最终独立目标使用上述精确三文件命令：**82 passed, 1 warning in 16.52s**。六个源码（`production`、`service`、`scheduler`、`composition`、`recovery`、`recovery_targets`）加四个测试（`lifecycle`、`degraded`、`scheduled permission shutdown`、`running`）完整 pre/post SHA256 JSON 一致；目标 hash 为 `DBF72BC1BA54121CC522DB37243588DE2FBFDA04F5CE908295BE30AE7743C125`。上述五路径 Ruff 与 `git diff --check` 通过。源码/测试评审包含追加的 absent-pipeline/public-read 控制，无剩余 P1/P2。最终双语报告一致性通过。C1/C3 和固定全量门禁仍单独保持开放。
