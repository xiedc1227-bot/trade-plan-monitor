# S3 顺序进程间的权限预约

## 状态与范围

作者验收：**2 passed in 7.90s**，无 warning。独立审查与复跑：**限定通过**，**2 passed in 7.74s**，无 warning，本范围内无 P1/P2 发现。这是新增 UPD-R17 证据，不是 baseline RED 或生产缺陷修复。

仅新增测试 `tests/integration/test_s3_permission_reservation_process.py`。它通过真实 common `run_permission_maintenance_unit`、生产 composition、controller 与 SQLite repository，覆盖一个代表 scope：`INDEX_HISTORICAL_MINUTES`（`idx_mins`）。两个场景验证通用持久准入边界，不声称覆盖全部八 scope 或 UPD-R18 自动 RUNNING/DEGRADED 唤醒。

实测 checkout 为 HEAD `3f111f73508049f263787b4ec2c1a4a87d4903fc` 加尚未提交的 UPD-S3 production 候选。虽然导入的 fixture helper 均已提交，但 common 方法尚未提交。这三个测试／报告文件必须与获验收的 S3 源码同批提交，或紧随源码提交之后；不能独立提交到该 HEAD。

## R17-P01 — 原始 300 秒下限

两个 child 都使用真实 index-only composition：无 active plans，有合法 index evidence、原始 SSE 完整日锚点 `2026-09-07` 和当前开市日历。初始权限 latch `2026-09-08 10:00:14+08:00` 是显式 fixture 输入，**不是**实测预约。

1. Child 1 在 `10:00:15` 启动并到达 RUNNING，将真实 scheduler 停在等待处，释放 sleep 次数为零。完整 SDK 调用列表为空，startup 没有改变持久 checkpoint。
2. 一个 common maintenance unit 恰好执行一次假 `idx_mins` SDK 调用，收到 `BLOCKED_PERMISSION`，保留真实预约 `10:05:15`（`now + 300 seconds`）。持久提交后恰好执行一次原始确认回调。
3. Child 1 成功 stop、drain 并以 code 0 退出后，才 spawn Child 2。
4. Child 2 在 `10:05:14.999999` 启动，同样 RUNNING、startup SDK 调用为零且 checkpoint 不变。该时刻的 common unit 零预约、零 SDK；精确 `10:05:15` 的 unit 预约一次、调用一次、验证原锚点 proof 并清除自身 block。其回调在原始确认之前观察到新下限 `10:10:15` 已持久保存。

## R17-P02 — 更晚的共享 429 与 token 变化

首次预约与 clean-exit 边界相同。停止前，Child 1 推进到 `10:02:15`，通过同一个真实 controller 执行一次单独计数的假 `index_daily` 调用，返回 `RATE_LIMITED`。这是显式 setup 工作，不是第二次 common-unit 调用。它建立共享 cooldown `10:07:15`，同时保留历史权限原始下限 `10:05:15`。

测试只在进程均已停止的间隙手工更换假凭据，endpoint identity 不变；这不是热重载。Child 2 原样恢复两个下限，在 SDK 调用列表为空时进入 RUNNING。在 `10:05:14.999999`、精确 `10:05:15`、`10:07:14.999999` 的 common unit 均零预约、零 SDK。精确 `10:07:15` 才允许一次预约与一次原锚点 proof；回调在确认前看到 `10:12:15` 已持久保存。所有拒绝点均未以更晚的共享下限覆盖 raw 下限。

## 共同硬断言

- 通过真实 OS `spawn` 创建两个 child；父进程 join 旧进程成功退出后才创建新 owner。时钟始终单调前进。
- 实际 runner 停在等待处，未被替换。两个 child 均必须 RUNNING、repository-bound、具备 index authority 且没有 stock semantics。Startup 在**全部 SDK endpoints** 上零调用，完整 checkpoint 快照不变。
- 观察器透明包装 `_permission_probe_reservation_callback`。每次真实回调时，一个新建的独立只读 SQLite 连接必须读到稳定 endpoint identity 下精确的 `now + 300` 行，然后转发一次原始回调并验证真实 rotation 确认。Seed 行及回调工厂创建不计作预约。
- 每个 common 调用都硬断预约／SDK 增量相等且仅为 0 或 1。单独计数的 429 setup 恰好一次物理尝试，不增加权限确认。
- 不 mock 真实 market-window 检查或原锚点。每次 common 物理调用必须使用 `idx_mins`、SSE composite 和原锚点请求日期；合法完整历史 frame 通过真实 provider proof 路径验证。
- 在 startup、每个 unit、429 setup、stop 和进程替换前后比较所有应用表的完整行。仅排除 schema 元数据、runtime liveness 与 provider recovery 记账；facts、quotes、indexes、evaluation/risk/HOLD/delivery/audit 状态保持不变。
- 每个 child 内 runtime 实例／generation 不变，无 runner failure 或 restart。成功 stop 清空 owned tasks 与 controller 槽位、关闭准入、排空 runner，并报告数据库 STOPPED。跨进程 generation 按预期不同。

## 命令与候选窗口

从仓库目录运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_permission_reservation_process.py -q --tb=short
.venv/Scripts/ruff.exe check tests/integration/test_s3_permission_reservation_process.py
git diff --check
```

作者 target 为 **2 tests in 7.90s**，无 warning。目标 Ruff 通过；`git diff --check` 无空白错误（Git 对另一作者拥有的 production WIP 输出了通常的 LF/CRLF 提示）。

源码作者在下表 production hash 提供短冻结，运行完成即解冻。初始／末尾 PowerShell 表格显示缩略了 hash 列；解冻前以 JSON 记录了下面的完整值。其余源码是该 HEAD 未改动的已跟踪文件。这是冻结候选窗口，不是 clean-HEAD 或 full-suite 声明。

| 文件 | SHA-256 |
|---|---|
| `runtime/production.py` | `1AD6922F9253369BAF7691FF751D33AF8B931FBC4EC612CE1D088E84248B173E` |
| `runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `web/monitor_composition.py` | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| `runtime/request_control.py` | `11AC5CBEDEB85BD651A1D28C0CA84F305EB815415D3FC950A2E9657A5A11B640` |
| `state/runtime_recovery.py` | `F4F762197F9A7FEAFB6BED6D5BCE911CE6DF3A0092B7911A5A4D8E6BE5F55AF3` |
| `test_s3_permission_reservation_process.py` | `C634BB3D21E01FCAE2E559FE42A6055C9D9DD9F431ABC5E4210289E256F18B4A` |

表中源码路径相对于 `src/trade_plan_monitor/`；测试位于 `tests/integration/`。

### 独立验证

独立审查者在 HEAD `3f111f73508049f263787b4ec2c1a4a87d4903fc` 加冻结 production 候选上复跑上述同一 pytest 命令：**2 passed in 7.74s**，无 warning。目标 Ruff、三个路径的 `git diff --check`、静态审查及英中 parity 均通过，这些文件无 P1/P2 发现。该计数与作者运行重叠，不相加。

审查者紧邻完整 pytest 运行的前后记录了未截断的完整路径和 64 位 hash。抽取的六个源码文件与测试均前后一致。采样文件为 `runtime/production.py`、`runtime/scheduler.py`、`runtime/service.py`、`runtime/recovery.py`、`runtime/recovery_targets.py`、`web/monitor_composition.py` 和 `test_s3_permission_reservation_process.py`。Production、scheduler、service、composition 与 test 的 hash 与作者表相应值一致。另两个源码 hash 如下：

| 文件 | SHA-256 |
|---|---|
| `runtime/recovery.py` | `E9F6D412042A4CB6A8A65ED8ED3E9FC4A9D1C9971186F8646AAD5581A2B9C051` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |

独立采样集合不包含作者表中的 `runtime/request_control.py` 或 `state/runtime_recovery.py`；其作者记录值保持原样，不重标为独立前后采样 hash。本次限定验收不批准更广的 S3 common dispatcher。另一个 future-defer 路径 P2 正由源码作者处理；本 R17 窗口不能作为该路径通过的证据。上述未提交源码的落地依赖仍适用。

## 边界

仅使用临时 SQLite、本地假凭据、虚拟 controller pacing 与假 SDK frames；不使用真实 provider、通知、服务或用户数据库，不改变 migration 政策或生产源码。本片证明顺序重启后的下限保持，不证明并行进程互斥、跨进程租约、恰好一次探测或预约与最终 SDK 入口原子性。Runner 被有意停在等待处，common 方法显式调用；UPD-R18 自动八 scope 推进、UPD-S4/S5、C1 和最终 S3 集成门禁仍开放。若候选源码变化，独立验收须重新使用连贯源码窗口；历史通过计数不相加。
