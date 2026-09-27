# S3 回归夹具对齐——五文件薄片

## 范围与状态

基线：`53b731271b4b3a10a8558da993ecd000f03c1d58`。仅修改测试；生产代码、共享 `ControlledClock`、控制器政策、依赖与业务契约均不变。独立源码/测试评审与最终报告 parity 已通过，无 P1/P2。本片不部署、不调用真实 SDK、不使用用户数据库；协调者负责本地提交。

所有权内的测试文件均位于 `tests/integration/`：

- `test_certified_production_runtime.py`
- `test_explicit_runtime_production.py`
- `test_index_permission_process_restart.py`
- `test_production_a06_matrix.py`
- `test_production_a06_process_scheduler.py`

加上本报告英文版与 `.zh-CN.md` 对应版，共七条自有路径。另一个回归薄片负责 `test_live_pipeline_acceptance.py`、`test_runtime_crossed_market_deadline.py`、`test_s3_index_retry_process.py`；本文不认领其验证证据。

## 基线与失败映射

Root 在基线提交上的固定全量运行结果为 **16 failed, 5695 passed, 1 skipped, 4 deselected, 1 warning in 1087.48s**。本片处理其中九个失败，并保留两个相关的原通过参数对照：

| 测试族 | 原失败用例 | 旧夹具失配原因 |
| --- | --- | --- |
| 认证缺口预算 | `[15-True]`（保留 `[59-False]`） | 行情尾部 inline 修复已按设计替换为有界股票维护；部分 startup 建立完成时刻 +30s 下界。 |
| 显式计划定时 BUY | 一个 | 第一次 sleep 现在可能是合法维护唤醒，而非原行情唤醒。 |
| 指数权限跨进程重启 | `[rt_idx_min_daily]`（保留历史参数） | 实时权限命名落选者不能绕过 common 同期限历史优先选择。 |
| A06 混合家族矩阵 | 两个损坏家族与两个必需指数用例 | startup 至多获取一个 symbol；健康 explicit 家族在原行情求值前仍需合法补齐 pending prefix。 |
| A06 进程调度 | 两个 symbol | 新增维护后，固定 first-sleep 判断使夹具在原行情目标前停住。 |

编辑前的只读 RED 复现：

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_certified_production_runtime.py::test_production_deadline_repairs_only_detected_gaps_with_realtime_budget -q --tb=short
1 failed, 1 passed in 14.13s

.venv/Scripts/python.exe -m pytest tests/integration/test_explicit_runtime_production.py::test_real_monitor_composition_scheduler_dispatches_explicit_buy tests/integration/test_index_permission_process_restart.py::test_migrated_index_permissions_recheck_independently_across_processes[rt_idx_min_daily] -q --tb=short
2 failed, 1 warning in 11.98s

.venv/Scripts/python.exe -m pytest tests/integration/test_production_a06_matrix.py -q --tb=short -k 'malformed_stock_row or required_index_failure' tests/integration/test_production_a06_process_scheduler.py -k 'malformed_stock_row or required_index_failure or malformed_family_row_recovers'
6 failed, 1 warning in 11.80s
```

最后一条命令包含两个 `-k`，实际生效的是后一个，选中了预期六例。额外失败现场诊断不另算产品回归。

## 已批准的对齐与保留断言

1. **缺口预算：** 保留原 startup/行情 10:00:15 与 10:00:59，断言没有 inline 当日获取，并保留原 +30s 下界（10:00:45 / 10:01:29）。真实 `MarketSessionScheduler` 使用实际行情窗口，在 10:01:15 / 10:01:59 选择维护。下一行情为 10:02:12：57s 允许恰好一个 symbol 请求；13s 拒绝全部 SDK 调用，gap/head 仍缺失、task 集合不变、无未来分钟，精确下次唤醒为 10:02:12 +1µs。这是组件证据，不声称自主 composition 进展。
2. **BUY：** 仅局部释放不晚于原 10:05:12 的实际调度期限，最多八次唤醒。等待原行情 handler 返回后，检查完成状态、唯一 BUY、精确 target 10:05/evaluated_at 10:05:12、activation revision、runtime/runner/generation 与合法 SDK endpoints。
3. **指数进程：** 保留两个成功 scope 参数，在两次 common 调用之前将另一个 endpoint 设为失败。实时命名落选者的 SDK/raw/block/rotation 均不变。common 固定历史后实时，每 unit 恰好一次物理请求、只改自身 latch、兄弟 raw/block 不变，失败 scope 保留 300s 下界。第二个干净进程保留原 +100s 零调用与 +600s 一调用、schema 23、持久 checkpoint、零业务写与正常退出。旧 +600s 场景不是 R17 精确等号证据。
4. **A06 矩阵：** 一个 legacy startup 获取后，至多运行一次真实 `STOCK_RECOVERY` 组件 unit，补 pending explicit symbol；断言 SDK 精确增加一次，非 minute/quote 业务行不变。保留必需指数 replacement 的 10:04:15 及其完整 index-only 重试阶段；仅到原 10:05:15、行情前才准备 pending explicit prefix。不循环补齐所有 requirements。原损坏隔离、健康家族进展、投递、身份、精确目标、指数持久下界断言均保留。
5. **A06 进程：** 子进程局部时钟在最多八次唤醒内释放不晚于原 10:00:12 / 10:05:12 的实际期限，然后停住。完成必须同时满足原行情 handler 已返回与下一未来停点。startup 仅有一次 legacy 获取，每次维护至多一个当日请求。保留两个真实 spawn 进程及原失败/健康家族、身份、目标、结果、告警、重启断言。

两项开发中的观察错误经 reviewer/root 明确批准后修正，并非产品修复：缺口拒绝返回 `None`，因为准入在 recovery result 产生前就被拒绝（初始新增断言结果：1 failed, 1 passed in 18.72s）；BUY 告警可能在 handler 返回前已提交（初始完成观察结果：1 failed, 1 warning in 6.71s）。末版保留硬副作用断言，不再假定错误的返回值或完成点。

## 作者验证

开发分窗：gap **2 passed in 15.22s**；BUY **1 passed, 1 warning in 6.51s**；index process **2 passed in 8.01s**（早于末次兄弟状态断言）；matrix **4 passed, 1 warning in 8.80s**；A06 process **2 passed, 1 warning in 12.05s**。这些重叠窗口不相加。

末版五文件命令：**41 passed, 1 warning in 95.00s**。

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_certified_production_runtime.py tests/integration/test_explicit_runtime_production.py tests/integration/test_index_permission_process_restart.py tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py -q --tb=short
```

限定 lint 与空白检查已通过：

```text
.venv/Scripts/python.exe -m ruff check tests/integration/test_certified_production_runtime.py tests/integration/test_explicit_runtime_production.py tests/integration/test_index_permission_process_restart.py tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py
git diff --check
git diff --name-only -- src
```

最后一条命令未返回任何路径。全部测试数据库和 SDK 均为临时、离线环境。warning 是既有 Starlette/httpx 弃用提示。

## 独立验证

Astra 独立运行上方完全相同的五文件 pytest 命令：**41 passed, 1 warning in 94.92s**。限定五文件 Ruff 命令与 `git diff --check` 均通过。完整静态评审无 P1/P2。独立窗口采样六个源码文件（production/service/scheduler/composition/recovery/recovery_targets）与五个自有测试：十一条完整 SHA256 前后全部一致。这是限定采样，不声称全部源码均已哈希。作者与独立计数覆盖相同用例，不相加。

## 冻结哈希与剩余门禁

下表九条 SHA256 在末版作者窗口前后全部一致：

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `F1083412137BDD38EDC6EF2B03F9C85797C6CCEDC6A5F7030D80E1B9211DC9BC` |
| `src/trade_plan_monitor/runtime/service.py` | `FF6D119BE17A0C4C7452CC468D549F8F9E68BC3469FDF0C2B830AD760E956AC1` |
| `src/trade_plan_monitor/runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `10BB57BC792645115AE045342E796D90FEF99F9E1ADDF6F0296B0B86E2CE6FD2` |
| `tests/integration/test_certified_production_runtime.py` | `A20F6CC67FE9545C190AF063CC467D36B0CD5F92F0EB91B64CD13D4A981945C5` |
| `tests/integration/test_explicit_runtime_production.py` | `C42DD37428A775759CFDD18BEA67A5A3DFC8922D215ADFD8F95E11198E97C278` |
| `tests/integration/test_index_permission_process_restart.py` | `750CDBCD43079FE3DEFFF2B662ED8B8C6145B28FD3605C59E66F6608A00261B3` |
| `tests/integration/test_production_a06_matrix.py` | `DF977CE2171CDEB83E6D7DC32A55C19869BAD60BF572FEE0FD99CFA42AAC5F52` |
| `tests/integration/test_production_a06_process_scheduler.py` | `DFFBA4A9A3FC245DCFE1A632761A3418B66551EBDE14AFA8206D63906BF8D887` |

独立五文件源码/测试评审与报告 parity 已通过。最终已提交固定全量门禁仍 OPEN。定向通过不代表原 16 个失败的全量门禁已关闭。
