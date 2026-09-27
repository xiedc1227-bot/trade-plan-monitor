# C1 UPD-S2 — 日历与指数权限 owner

## 状态与范围

设计：已获配对 `2026-09-27-c1-unified-permission-dispatch-contract`（UPD-S2）批准。实现：作者验证与独立源码/测试评审通过，无剩余 P1/P2；双语报告 parity 已通过。这不代表 C1 完成、八 scope 自动统一派发或 RUNNING/DEGRADED 恢复验收。

实现开始于 F3-C `a1f217be34334fd68f8a635dda953e2b78e97e55` 之后，已有 S1 `b3e04a4` 最终 hook 与 SMWO `fbdcaed`。保留 root 至最终基线 `5e2eda5` 的无关夹具提交。本片仅拥有以下六个路径：

- `src/trade_plan_monitor/runtime/production.py`
- `tests/integration/test_unified_permission_legacy_owners.py`
- `tests/integration/test_production_index_realtime_permission_probe.py`
- `tests/integration/test_production_certification_gate.py`
- `docs/verification/2026-09-27-c1-permission-legacy-owners.md`
- `docs/verification/2026-09-27-c1-permission-legacy-owners.zh-CN.md`

未改 provider、controller、startup、scheduler、lifecycle 或 composition 源码。测试使用离线假 SDK、真实 controller/certification wrapper 和临时 SQLite。未使用真实服务、用户数据库、部署或推送。提交权限仍属 root。

## 实现边界

原三个命名入口获取 `_permission_maintenance_lock` 并调用同一私有持锁主体。有界新鲜全局选择必须选中该操作；命名败者不能执行赢家。预约回调在锁内、紧邻 `recheck_permission` 前生成，仅 durable `on_reserved` 确认推进全局游标。O/F 与两个股票 symbol 游标保持不变。

每次调用冻结 candidate/anchor、provider、wrapper 及 inner client、source label/profile、session factory、原模式 authority、calendar epoch/Event 和 owner Task/cancellation Event。本地读取后同时比较 epoch 与 Event，才安装新 Event；从不 clear 已撤销旧 Event。日历保留已完成休市日证明，history 保留已完成 SSE 工作日开市证明，realtime 保留当日/09:35:12/物理 S cutoff 规则。证明解析仍位于原 provider。

真实 wrapper/resolver 完成后，最后 authority I/O 先于唯一物理采样 S。随后仅做内存检查与冻结行情窗口检查，再调用 resolved SDK。包含等号的 15 秒最迟入场与 31.25 秒行情预留不变。缺失行情窗口 authority 产生固定本地 defer。worker 路径既不执行 SQL，也不读取 Task。

响应验证通过捕获的 factory，在一个 fresh owned explicit-BEGIN snapshot 内读取精确原 anchor，读前后均检查 owner。借用 session 在所有权校验处失败，不关闭或回滚调用方事务。另一个合法日期不能替换原 anchor。最后 authority I/O 后再次检查已请求取消，而不仅在读取前检查；晚到成功不能 clear block。取消释放 maintenance lock，但不提前归还 controller 的物理 slot。

已知 `BLOCKED_PERMISSION`、`RATE_LIMITED`、`TRANSIENT`、`TIMEOUT`、`INVALID_RESPONSE` 转为 `FAILED`。`ERROR`、`CLOSED`、`QUEUE_FULL`、save/callback/响应 SQL 错误继续传播。sentinel defer 保留预约与确认。保留日历原 work key `permission:trade_cal:SSE`，防止绕过已有 work-key backoff。本地 index defer 同时更新旧 index 时间字段与 common cheap getter 的时间 map。

## RED 历史与夹具区分

目标命令始终为：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_permission_legacy_owners.py -q --tb=short
```

- 初始仲裁/锁/ack 测试：**9 failed, 1 warning, 4.90s**；最小锁/选择变更后：**9 passed, 1 warning, 4.52s**。
- 扩展 33 用例真实失败检查点：**15 failed, 18 passed, 1 warning, 13.48s**（`--tb=line`），覆盖缺窗口拒绝、真实 wrapper 围栏及被吞掉的 fatal index 错误。共享 owner 围栏后：**33 passed, 1 warning, 13.40s**。
- 更早扩展运行曾为 **21 failed, 12 passed, 14.69s**，混有非法 `attempts=7` 夹具构造和 checkpoint 故障锁存后 stop 正确传播。它们是夹具修正，不是产品修复或上述干净 RED 证据。
- reviewer 独立诊断出最后 authority I/O 期间取消问题。正式 `-k final_authority_io` 测试：**3 failed, 84 deselected, 1 warning, 2.76s**，三者均因取消却错误 clear block。最小 owner 线程复查后：**3 passed, 84 deselected, 1 warning, 2.38s**。中间 **3 failed, 84 deselected, 1 warning, 2.60s** 仅为测试属性拼写错误（将现有 `active_count` 写成 `active_physical_count`），此时实际 clear 断言已修复。
- reviewer 独立诊断出日历 work-key 兼容问题。正式 `-k original_work_key`：**1 failed, 87 deselected, 1 warning, 1.76s**，恢复旧 key 后 **1 passed, 87 deselected, 1 warning, 1.60s**。真实 controller 晚到失败产生比原预约晚一秒的 work-key floor；测试保留该时间前 SDK 为零、任何新预约/ack，以及有效 floor 后一次合法调用。

五个原 realtime calendar-fence 夹具仅在对应调用中增加 `block_historical=False`。它们的 stock certification 使 history 成为合法、更早的全局赢家；这些不是仲裁测试。Sol 批准该夹具隔离，未削弱 token/epoch/queue/物理调用/floor/业务零写断言。两个原 index 文件随后 **71 tests passed in 14.36s**。新三 owner 败者测试继续覆盖真实仲裁。

原四个 calendar failure 参数现在期待批准的 `FAILED` 边界，而非已知 provider 错误外抛。包装器记录真实 controller 异常并重新抛给 owner，保留 category、300 秒 floor、一次物理调用及日历/业务数据零变化断言。定向结果：**4 passed, 40 deselected, 4.24s**。root 单独提交的四个 certification 夹具不在本片修改范围。

## 最终作者证据

扩展目标覆盖 109 用例：非赢家、真实预约串行、save/callback 故障、queue veto/恰一次确认、缺窗口/固定 defer、真实 resolver 延时/撤销/inner-client 替换、15 秒等号、31.25 秒等号与 resolver 越界、最后 I/O→唯一 S 顺序、精确原 anchor、epoch/Event 交错及新 token 重建、SQL 与最后 authority I/O 期间已请求取消、SDK/resolver 持有期间取消与 drain、owned snapshot、借用 session、响应 SQL 故障、休市日差异及错误矩阵。已知失败还对比证明前后完整日历/minute/quote/index/evaluation/alert/delivery 行。

追加最后六个物理顺序控制前，全目标 **103 passed, 1 warning, 40.81s**。追加六项为 **6 passed, 103 deselected, 1 warning, 3.52s**。上述最终命令在下列冻结源码/测试 hash 上 **109 passed, 1 warning, 42.74s**。重叠窗口计数不可相加。

直接相邻命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_certification_gate.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/unit/test_permission_reservation_ack.py -q --tb=short
```

结果：**136 passed, 1 warning, 51.00s**。warning 为已有 Starlette `httpx` 弃用提示。这是作者证据，不是独立评审证据。

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_unified_permission_legacy_owners.py tests/integration/test_production_certification_gate.py tests/integration/test_production_index_realtime_permission_probe.py
git diff --check
```

限定 Ruff 与 `git diff --check` 已通过。独立结果见下文。

冻结 SHA256：

| 文件 | SHA256 |
|---|---|
| `production.py` | `A7D112694000DDF4DB5BF35170B32BDC4F056D18A991B69BDC272AEAE3CC5938` |
| `test_unified_permission_legacy_owners.py` | `104E6FFA2F71CACAFC01B5F6DB21014E6EA35A6B102451E11A398C450DA5BF2E` |
| `test_production_certification_gate.py` | `D8C3A617242B46A294CC322649A8BB258243B082D1D0DF30825E5A02087160AE` |
| `test_production_index_realtime_permission_probe.py` | `C6E1369123D82B03B260AF645EE68EB8262EB62D22FC4994B4537761918BB3B3` |

## 独立验证

Sol 独立重跑上述最终目标命令：**109 passed, 1 warning, 42.35s**。有限相邻命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/unit/test_permission_reservation_ack.py -q --tb=short
```

结果：**124 passed, 43.77s**，无 warning。reviewer 在两项修补后确认无剩余 P1/P2，并认可四 calendar/五 realtime 夹具变更；限定四路径 Ruff 与目标 diff 检查通过。首次相邻命令误写 `tests/integration/test_permission_reservation_ack.py`，0.01s 未运行测试；这仅为命令路径错误，不是 RED 或通过证据。最终六个源码/三个测试 hash 均与开始一致，包括上述四个本片 hash。HEAD 从 `8d61a8e` 变为 `5e2eda506824e68a9f4ce089689cfe087fd255c3`，仅包含 root 的 process429 夹具提交；这是稳定的未提交 S2 候选测试，不是 clean-HEAD 测试。双语报告 parity 已通过。

## 来源与剩余工作

实现遵循已批契约及现有本地 controller/session 所有权代码。Python 的 [Task cancellation count](https://docs.python.org/3.14/library/asyncio-task.html#asyncio.Task.cancelling) 支持在外层异常处理前拒绝已请求取消；[threading.Event](https://docs.python.org/3.14/library/threading.html#event-objects) 提供线程可读 token。SQLAlchemy 的 [SQLite 事务指导](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl) 已由现有 `state/database.py` BEGIN listener 与 `require_owned_recovery_session` 落实；未增加第二次 BEGIN。本地 SQLAlchemy 仍为 2.0.52，未升级依赖。

双语报告 parity 已通过；独立最终源码/测试评审通过。S3 仍负责 common 八 scope 派发、全部不可用时的 timing、移除 inline calendar recheck、剩余宽 catch，以及另外五个 owner 的最后 authority-I/O 取消控制。S4/S5 仍负责真实 RUNNING/DEGRADED 调度、双时钟及完整 UPD-R01..18 连接/跨进程验收。本片直接命名 owner 测试不能替代它们。
